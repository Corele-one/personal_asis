from dataclasses import replace
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
import zipfile
from unittest.mock import patch

from personal_asis.config import Config, Source
from personal_asis.extractors import extract, ExtractionError
from personal_asis.index import Index


def package(parts):
    result = io.BytesIO()
    with zipfile.ZipFile(result, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, text in parts.items():
            archive.writestr(name, text)
    return result.getvalue()


def word(text="synthetic document evidence"):
    from xml.sax.saxutils import escape
    return package({
        "[Content_Types].xml": '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
        "_rels/.rels": '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>',
        "word/document.xml": '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>first paragraph</w:t></w:r></w:p><w:p><w:r><w:t>' + escape(text) + '</w:t></w:r></w:p><w:sectPr/></w:body></w:document>'})


class FormatTests(unittest.TestCase):
    def test_mac_worker_extracts_when_address_space_limit_is_unsupported(self):
        import resource
        from personal_asis.extractors import worker
        output = io.StringIO()
        def platform_limit(kind, value):
            if kind == resource.RLIMIT_AS:
                raise ValueError("unsupported on this platform")
        with patch("resource.setrlimit", side_effect=platform_limit), patch.object(sys, "platform", "darwin"), \
                patch.object(sys, "argv", ["worker", "docx"]), \
                patch.object(sys, "stdin", SimpleNamespace(buffer=io.BytesIO(word()))), patch.object(sys, "stdout", output):
            worker()
        self.assertIn("synthetic document evidence", json.loads(output.getvalue())["text"])

    def test_programmatic_extraction_works_without_exported_pythonpath(self):
        with patch.dict(os.environ, {"PYTHONPATH": ""}):
            self.assertIn("synthetic", extract(word(), "sample.docx")["text"])

    def test_word_paragraphs_and_entity_rejection(self):
        result = extract(word("synthetic 中文证据"), "sample.docx")
        self.assertIn("中文证据", result["text"])
        self.assertEqual(result["locations"][1]["paragraph"], 2)
        self.assertEqual(result["metadata"]["title"], "sample")
        bad = package({"word/document.xml": '<!DOCTYPE x [<!ENTITY x "EXPAND">]><x>&x;</x>'})
        with self.assertRaisesRegex(ExtractionError, "xml_entities_rejected"):
            extract(bad, "bad.docx")

    def test_slides_follow_presentation_order(self):
        result = extract(package({
            "ppt/presentation.xml": '<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><p:sldIdLst><p:sldId id="256" r:id="r2"/><p:sldId id="257" r:id="r1"/></p:sldIdLst></p:presentation>',
            "ppt/_rels/presentation.xml.rels": '<Relationships><Relationship Id="r1" Target="slides/slide1.xml"/><Relationship Id="r2" Target="slides/slide2.xml"/></Relationships>',
            "ppt/slides/slide1.xml": '<s xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><a:p><a:r><a:t>second visible slide</a:t></a:r></a:p></s>',
            "ppt/slides/slide2.xml": '<s xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><a:p><a:r><a:t>first visible slide</a:t></a:r></a:p></s>'}), "sample.pptx")
        self.assertLess(result["text"].index("first visible"), result["text"].index("second visible"))
        self.assertEqual([l["slide"] for l in result["locations"]], [1, 2])

    def test_spreadsheet_strings_cells_and_cached_formula_without_evaluation(self):
        result = extract(package({
            "xl/workbook.xml": '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="合成表" r:id="r1"/></sheets></workbook>',
            "xl/_rels/workbook.xml.rels": '<Relationships><Relationship Id="r1" Target="/xl/worksheets/sheet1.xml"/><Relationship Id="external" Target="https://example.invalid/private" TargetMode="External"/></Relationships>',
            "xl/sharedStrings.xml": '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><si><t>synthetic cell evidence</t></si></sst>',
            "xl/worksheets/sheet1.xml": '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1"><f>1+2</f><v>99</v></c></row></sheetData></worksheet>'}), "sample.xlsx")
        self.assertIn("synthetic cell evidence", result["text"])
        self.assertIn("cached value: 99", result["text"])
        self.assertEqual(result["locations"][0]["sheet"], "合成表")
        self.assertEqual(result["locations"][1]["cell"], "B1")

    @unittest.skipUnless(importlib.util.find_spec("reportlab"), "requires test-formats dependency")
    def test_pdf_text_pages_blank_pages_and_encryption(self):
        from reportlab.pdfgen import canvas
        raw = io.BytesIO()
        document = canvas.Canvas(raw)
        document.drawString(72, 700, "first page")
        document.showPage()
        document.drawString(72, 700, "unique second-page evidence")
        document.save()
        result = extract(raw.getvalue(), "sample.pdf")
        self.assertEqual(result["locations"][1]["page"], 2)
        self.assertIn("unique second-page", result["text"])
        blank = io.BytesIO()
        document = canvas.Canvas(blank)
        document.showPage()
        document.save()
        with self.assertRaisesRegex(ExtractionError, "no_text"):
            extract(blank.getvalue(), "scanned-or-blank.pdf")
        if importlib.util.find_spec("pypdf"):
            from pypdf import PdfReader, PdfWriter
            encrypted = io.BytesIO()
            writer = PdfWriter()
            writer.append_pages_from_reader(PdfReader(io.BytesIO(raw.getvalue())))
            writer.encrypt("test-only-password")
            writer.write(encrypted)
            with self.assertRaisesRegex(ExtractionError, "encrypted"):
                extract(encrypted.getvalue(), "encrypted.pdf")

    def test_binary_index_identity_stale_evidence_and_skipped_coverage(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name) / "source"
            root.mkdir()
            path = root / "sample.docx"
            path.write_bytes(word("unique binary evidence"))
            (root / "broken.docx").write_bytes(b"not a document")
            config = Config("rog", (Source("mixed", root, "normal", True, True, (), formats=("md", "docx")),))
            with Index(Path(name) / "index.sqlite3", config) as index:
                report = index.reconcile()
                self.assertEqual(report["sources"][0]["skipped_documents"], 1)
                hit = index.search("unique")["results"][0]["replicas"][0]
                self.assertEqual(hit["location"]["paragraph"], 2)
                self.assertEqual(hit["format"], "docx")
                doc_id = hit["document_id"]
                path.write_bytes(word("unique changed evidence"))
                self.assertEqual(index.search("unique")["results"], [])
                index.reconcile()
                self.assertEqual(index.search("unique")["results"][0]["replicas"][0]["document_id"], doc_id)
                renamed = root / "moved.docx"
                path.rename(renamed)
                self.assertEqual(index.reconcile()["moved"], 1)
                renamed.unlink()
                index.reconcile()
                self.assertEqual(index.search("unique")["results"], [])

    @unittest.skipUnless(shutil.which("libreoffice") and Path("/usr/lib/python3/dist-packages/uno.py").exists(), "requires LibreOffice and system UNO")
    def test_real_legacy_word_conversion_is_read_only(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            source = directory / "source.docx"
            source.write_bytes(word("legacywordproof synthetic evidence"))
            subprocess.run(["libreoffice", "--headless", "--nologo", "-env:UserInstallation=" + (directory / "profile").as_uri(),
                "--convert-to", "doc", "--outdir", str(directory), str(source)], capture_output=True, check=True, timeout=30)
            legacy = directory / "source.doc"
            self.assertTrue(legacy.exists())
            before = legacy.read_bytes(), legacy.stat().st_mtime_ns
            self.assertTrue(before[0].startswith(bytes.fromhex("d0cf11e0")))
            extracted = extract(before[0], legacy)
            self.assertIn("legacywordproof", extracted["text"])
            self.assertEqual((legacy.read_bytes(), legacy.stat().st_mtime_ns), before)

    @unittest.skipUnless(shutil.which("localc") and shutil.which("loimpress") and Path("/usr/lib/python3/dist-packages/uno.py").exists(), "requires Calc, Impress and system UNO")
    def test_real_legacy_spreadsheet_and_slides_are_read_only(self):
        namespace = 'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0" xmlns:presentation="urn:oasis:names:tc:opendocument:xmlns:presentation:1.0" xmlns:svg="urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0"'
        samples = {
            "xls": ("fods", "spreadsheet", '<office:spreadsheet><table:table table:name="Fixture"><table:table-row><table:table-cell office:value-type="string"><text:p>legacyxlsproof synthetic evidence</text:p></table:table-cell></table:table-row></table:table></office:spreadsheet>', "legacyxlsproof"),
            "ppt": ("fodp", "presentation", '<office:presentation><draw:page draw:name="Slide1"><draw:frame presentation:class="outline" svg:x="1cm" svg:y="1cm" svg:width="15cm" svg:height="8cm"><draw:text-box><text:p>legacypptproof synthetic evidence</text:p></draw:text-box></draw:frame></draw:page></office:presentation>', "legacypptproof")}
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            for fmt, (suffix, mime, body, marker) in samples.items():
                with self.subTest(format=fmt):
                    source = directory / ("source." + suffix)
                    source.write_text('<?xml version="1.0" encoding="UTF-8"?><office:document ' + namespace + ' office:version="1.2" office:mimetype="application/vnd.oasis.opendocument.' + mime + '"><office:body>' + body + '</office:body></office:document>')
                    converted = subprocess.run(["libreoffice", "--headless", "--nologo", "-env:UserInstallation=" + (directory / ("profile-" + fmt)).as_uri(),
                        "--convert-to", fmt, "--outdir", str(directory), str(source)], capture_output=True, check=True, timeout=30)
                    legacy = directory / ("source." + fmt)
                    self.assertTrue(legacy.exists(), converted.stdout.decode() + converted.stderr.decode())
                    before = legacy.read_bytes(), legacy.stat().st_mtime_ns
                    self.assertIn(marker, extract(before[0], legacy)["text"])
                    self.assertEqual((legacy.read_bytes(), legacy.stat().st_mtime_ns), before)


if __name__ == "__main__":
    unittest.main()
