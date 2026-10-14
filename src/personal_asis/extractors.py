"""Local text extraction only: no OCR, media decoding, macros or link updates."""

import io
import json
import logging
import os
from pathlib import Path
import posixpath
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import zipfile
from xml.etree import ElementTree as ET

from .markdown import parse


FORMATS = ("md", "pdf", "docx", "docm", "xlsx", "xlsm", "pptx", "pptm", "doc", "xls", "ppt")
MAX_SOURCE_BYTES = 128 * 1024 * 1024
MAX_XML_BYTES = 64 * 1024 * 1024
MAX_TEXT_CHARS = 4_000_000
MAX_UNITS = 200_000
EXTRACTOR_VERSION = "text-v1"
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


class ExtractionError(ValueError):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


def _xml(archive, name):
    info = archive.getinfo(name)
    if info.file_size > MAX_XML_BYTES:
        raise ExtractionError("xml_too_large")
    data = archive.read(name)
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise ExtractionError("xml_entities_rejected")
    return ET.fromstring(data)


def _relations(archive, name, base):
    if name not in archive.namelist():
        return {}
    return {r.attrib["Id"]: posixpath.normpath(posixpath.join(base, r.attrib["Target"])).lstrip("/")
            for r in _xml(archive, name)
            if r.attrib.get("TargetMode") != "External"}


def _assemble(units, filename, fmt):
    lines, locations = [], []
    chars, total = 0, 0
    for location, text in units:
        total += 1
        if total > MAX_UNITS:
            raise ExtractionError("too_many_units")
        text = text.replace("\x00", "").strip()
        if not text:
            continue
        chars += len(text)
        if chars > MAX_TEXT_CHARS:
            raise ExtractionError("text_too_large")
        start = len(lines) + 1
        lines.extend(text.splitlines())
        locations.append({**location, "line_start": start, "line_end": len(lines)})
        lines.append("")
    if not locations:
        raise ExtractionError("no_text")
    return {"text": "\n".join(lines), "metadata": {"title": filename, "private": False, "links": []},
            "locations": locations, "format": fmt, "units": total, "text_units": len(locations),
            "extractor_version": EXTRACTOR_VERSION}


def _ooxml(raw, filename, fmt):
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        if sum(i.file_size for i in archive.infolist()) > 256 * 1024 * 1024:
            raise ExtractionError("expanded_archive_too_large")
        units = []
        if fmt in {"docx", "docm"}:
            parts = ["word/document.xml"] + sorted(n for n in archive.namelist()
                if re.fullmatch(r"word/(?:header\d+|footer\d+|footnotes|endnotes)\.xml", n))
            for part in parts:
                for n, p in enumerate(_xml(archive, part).iter(W + "p"), 1):
                    units.append(({"kind": "paragraph", "part": part, "paragraph": n},
                                  "".join(t.text or "" for t in p.iter(W + "t"))))
        elif fmt in {"pptx", "pptm"}:
            rels = _relations(archive, "ppt/_rels/presentation.xml.rels", "ppt")
            root = _xml(archive, "ppt/presentation.xml")
            slide_ids = root.findall(".//{http://schemas.openxmlformats.org/presentationml/2006/main}sldId")
            for n, item in enumerate(slide_ids, 1):
                part = rels[item.attrib[R + "id"]]
                slide = _xml(archive, part)
                units.append(({"kind": "slide", "slide": n},
                              "\n".join("".join(t.text or "" for t in p.iter(A + "t")) for p in slide.iter(A + "p"))))
                note_rels = _relations(archive, posixpath.join(posixpath.dirname(part), "_rels", posixpath.basename(part) + ".rels"), posixpath.dirname(part))
                for note in note_rels.values():
                    if note.startswith("ppt/notesSlides/notesSlide") and note.endswith(".xml"):
                        units.append(({"kind": "speaker_notes", "slide": n},
                                      "\n".join(t.text or "" for t in _xml(archive, note).iter(A + "t"))))
        else:
            strings = []
            if "xl/sharedStrings.xml" in archive.namelist():
                strings = ["".join(t.text or "" for t in si.iter(S + "t"))
                           for si in _xml(archive, "xl/sharedStrings.xml").iter(S + "si")]
            rels = _relations(archive, "xl/_rels/workbook.xml.rels", "xl")
            for sheet in _xml(archive, "xl/workbook.xml").iter(S + "sheet"):
                part = rels[sheet.attrib[R + "id"]]
                # Absolute package targets are relative to the ZIP root.
                part = part.lstrip("/")
                for cell in _xml(archive, part).iter(S + "c"):
                    value = cell.findtext(S + "v", "")
                    typ = cell.attrib.get("t")
                    if typ == "s":
                        value = strings[int(value)] if value else ""
                    elif typ == "inlineStr":
                        value = "".join(t.text or "" for t in cell.iter(S + "t"))
                    formula = cell.findtext(S + "f")
                    if formula:
                        value = f"formula: {formula}; cached value: {value}"
                    if value:
                        address = cell.attrib.get("r", "")
                        units.append(({"kind": "cell", "sheet": sheet.attrib["name"], "cell": address},
                                      address + "\t" + value))
        return _assemble(units, filename, fmt)


def _legacy(raw, filename, fmt):
    executable = shutil.which("libreoffice") or shutil.which("soffice")
    if not executable or not shutil.which("unshare"):
        raise ExtractionError("legacy_converter_unavailable")
    target = {"doc": "docx", "xls": "xlsx", "ppt": "pptx"}[fmt]
    with tempfile.TemporaryDirectory(prefix="asis-office-") as name:
        directory = Path(name)
        directory.chmod(0o700)
        profile = directory / "profile"
        (profile / "user").mkdir(parents=True)
        # A fresh profile has no trusted sources. Disable all macros explicitly.
        (profile / "user/registrymodifications.xcu").write_text('''<?xml version="1.0"?>
<oor:items xmlns:oor="http://openoffice.org/2001/registry">
<item oor:path="/org.openoffice.Office.Common/Security/Scripting">
<prop oor:name="DisableMacrosExecution" oor:op="fuse"><value>true</value></prop>
<prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop>
</item></oor:items>''')
        source = directory / ("input." + fmt)
        source.write_bytes(raw)
        output = directory / "out"
        output.mkdir()
        # The converter has no network namespace access, so no external links load.
        argv = ["unshare", "-Urn", "--", "/usr/bin/python3", str(Path(__file__).with_name("legacy_office.py")),
                str(directory), fmt, executable]
        process = subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        try:
            code = process.wait(timeout=45)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            raise ExtractionError("converter_timeout") from None
        converted = output / ("input." + target)
        if code or not converted.is_file():
            raise ExtractionError("legacy_conversion_failed")
        if converted.stat().st_size > MAX_SOURCE_BYTES:
            raise ExtractionError("converted_file_too_large")
        result = _ooxml(converted.read_bytes(), filename, target)
        result["format"] = fmt
        result["converted"] = True
        return result


def _extract(raw, filename, fmt):
    if len(raw) > MAX_SOURCE_BYTES:
        raise ExtractionError("source_too_large")
    if fmt == "md":
        text = raw.decode("utf-8-sig")
        return {"text": text, "metadata": parse(text, filename), "locations": [], "format": fmt,
                "extractor_version": EXTRACTOR_VERSION, "units": 1, "text_units": bool(text.strip())}
    if fmt == "pdf":
        if shutil.which("pdftotext"):
            process = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", "-", "-"],
                                     input=raw, capture_output=True, timeout=60)
            if process.returncode:
                reason = "encrypted" if b"password" in process.stderr.lower() else "pdf_parse_error"
                raise ExtractionError(reason)
            pages = process.stdout.decode("utf-8").split("\f")
            if pages and not pages[-1]:
                pages.pop()
            return _assemble((({"kind": "page", "page": n}, text) for n, text in enumerate(pages, 1)), filename, fmt)
        try:
            from pypdf import PdfReader
        except ImportError:
            raise ExtractionError("pdf_dependency_unavailable") from None
        logging.getLogger("pypdf").setLevel(logging.CRITICAL)
        reader = PdfReader(io.BytesIO(raw), strict=False)
        if reader.is_encrypted and not reader.decrypt(""):
            raise ExtractionError("encrypted")
        if len(reader.pages) > 5000:
            raise ExtractionError("too_many_pages")
        return _assemble((({"kind": "page", "page": n}, page.extract_text() or "")
                          for n, page in enumerate(reader.pages, 1)), filename, fmt)
    if fmt in {"docx", "docm", "xlsx", "xlsm", "pptx", "pptm"}:
        if raw.startswith(bytes.fromhex("d0cf11e0")) and "EncryptedPackage".encode("utf-16-le") in raw:
            raise ExtractionError("encrypted")
        return _ooxml(raw, filename, fmt)
    if fmt in {"doc", "xls", "ppt"}:
        return _legacy(raw, filename, fmt)
    raise ExtractionError("unsupported_format")


def extract(raw, path):
    fmt = Path(path).suffix.lower().lstrip(".")
    if fmt == "md":
        return _extract(raw, Path(path).stem, fmt)
    # A damaged parser cannot hang the daemon or emit document contents to logs.
    env = os.environ.copy()
    # Programmatic callers may set sys.path without exporting PYTHONPATH.
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1]) + os.pathsep + env.get("PYTHONPATH", "")
    process = subprocess.Popen([sys.executable, "-m", "personal_asis.extractors", fmt],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, start_new_session=True, env=env)
    try:
        stdout, _ = process.communicate(raw, timeout=90)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()
        raise ExtractionError("extractor_timeout") from None
    if process.returncode or len(stdout) > 32 * 1024 * 1024:
        raise ExtractionError("extractor_failed")
    try:
        result = json.loads(stdout)
    except (ValueError, UnicodeError):
        raise ExtractionError("extractor_failed") from None
    if "error" in result:
        raise ExtractionError(result["error"])
    result["metadata"]["title"] = Path(path).stem
    return result


def worker():
    os.umask(0o077)
    try:
        import resource
        # macOS does not provide a usable RLIMIT_AS for this worker. Its byte,
        # ZIP expansion, text, unit and wall-clock limits still apply.
        if sys.platform == "linux":
            # Calc reserves over 2 GiB of virtual address space even for a tiny
            # workbook; this finite limit covers the converter too.
            address_limit = (4 if sys.argv[1] in {"doc", "xls", "ppt"} else 2) * 1024**3
            resource.setrlimit(resource.RLIMIT_AS, (address_limit, address_limit))
        resource.setrlimit(resource.RLIMIT_CPU, (75, 80))
        result = _extract(sys.stdin.buffer.read(MAX_SOURCE_BYTES + 1), "document", sys.argv[1])
    except ExtractionError as exc:
        result = {"error": exc.reason}
    except Exception:
        result = {"error": "parse_error"}
    sys.stdout.write(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    worker()
