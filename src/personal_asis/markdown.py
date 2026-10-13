import hashlib
import re


PRIVATE_MARKER = re.compile(
    r"^\s*(?:sensitivity|policy|classification)\s*:\s*['\"]?private['\"]?\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse(text: str, filename: str) -> dict:
    lines = text.splitlines()
    frontmatter = ""
    if lines and lines[0].strip() == "---":
        end = next((i for i in range(1, len(lines)) if lines[i].strip() in {"---", "..."}), None)
        if end is not None:
            frontmatter = "\n".join(lines[1:end])
    title_match = re.search(r"^title:\s*(.+)$", frontmatter, re.MULTILINE)
    heading = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
    title = (title_match.group(1).strip().strip("\"'") if title_match
             else heading.group(1).strip() if heading else filename)
    attachments = re.findall(r"!?\[\[[^\]\n]+\]\]|!?\[[^\]\n]*\]\([^\)\n]+\)", text)
    return {"title": title, "private": bool(PRIVATE_MARKER.search(frontmatter)),
            "links": attachments}


def excerpt(text: str, terms: list[str], max_chars: int = 240) -> dict:
    # Read current source rather than retaining a second plaintext body archive.
    lines = text.splitlines() or [""]
    lowered = [line.lower() for line in lines]
    best = max(range(len(lines)), key=lambda i: sum(term.lower() in lowered[i] for term in terms))
    line = lines[best]
    positions = [line.lower().find(term.lower()) for term in terms if term.lower() in line.lower()]
    offset = max(0, (min(positions) if positions else 0) - 60)
    return {"line_start": best + 1, "line_end": best + 1,
            "excerpt": line[offset:offset + max_chars], "column_start": offset + 1}
