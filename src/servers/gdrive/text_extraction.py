"""Bounded, in-memory extraction without filesystem access or remote requests."""

import io
import re
import zipfile
from defusedxml import ElementTree

from pypdf import PdfReader

MAX_EXPANDED_BYTES = 20 * 1024 * 1024
MAX_TEXT_CHARS = 2 * 1024 * 1024
MAX_PDF_PAGES = 1000
OFFICE_TYPES = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
}


def extract_text(content, mime):
    if isinstance(content, str):
        return content
    if mime == "application/pdf":
        reader = PdfReader(io.BytesIO(content))
        if reader.is_encrypted:
            raise ValueError("Encrypted PDFs are not supported")
        if len(reader.pages) > MAX_PDF_PAGES:
            raise ValueError("PDF exceeds the 1000 page extraction limit")
        parts, length = [], 0
        for page in reader.pages:
            stream = page.get_contents()
            if stream is not None and len(stream.get_data()) > MAX_EXPANDED_BYTES:
                raise ValueError("PDF page content exceeds the extraction limit")
            text = page.extract_text() or ""
            length += len(text)
            if length > MAX_TEXT_CHARS:
                raise ValueError("Extracted text exceeds the 2 Mi character limit")
            parts.append(text)
        text = "\n\n".join(parts)
        if not text.strip():
            raise ValueError(
                "No extractable PDF text; scanned/image-only PDFs require OCR"
            )
        return text
    kind = OFFICE_TYPES.get(mime)
    if kind is None:
        raise ValueError(
            f"Text extraction is not supported for {mime}; use read_file for original bytes"
        )
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        if sum(info.file_size for info in archive.infolist()) > MAX_EXPANDED_BYTES:
            raise ValueError("Office document exceeds the 20 MiB expanded size limit")
        if len(archive.infolist()) > 10000:
            raise ValueError("Office document contains too many entries")

        def xml(path):
            raw = archive.read(path)
            # OOXML needs no DTDs or entity definitions. Reject them explicitly.
            if b"<!DOCTYPE" in raw or b"<!ENTITY" in raw:
                raise ValueError(
                    "DTD/entity declarations are not supported in Office XML"
                )
            return ElementTree.fromstring(raw, forbid_dtd=True)

        def tag(element):
            return element.tag.rsplit("}", 1)[-1]

        def sort_key(path):
            return [
                int(part) if part.isdigit() else part
                for part in re.split(r"(\d+)", path)
            ]

        parts = []
        if kind == "docx":
            root = xml("word/document.xml")
            for paragraph in root.iter():
                if tag(paragraph) == "p":
                    parts.append(
                        "".join(
                            (
                                node.text or ""
                                if tag(node) == "t"
                                else "\t" if tag(node) == "tab" else "\n"
                            )
                            for node in paragraph.iter()
                            if tag(node) in ("t", "tab", "br", "cr")
                        )
                    )
        elif kind == "pptx":
            slides = sorted(
                (
                    name
                    for name in archive.namelist()
                    if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)
                ),
                key=sort_key,
            )
            for name in slides:
                parts.append(
                    "\n".join(
                        node.text or "" for node in xml(name).iter() if tag(node) == "t"
                    )
                )
        else:
            shared = []
            if "xl/sharedStrings.xml" in archive.namelist():
                shared = [
                    "".join(node.text or "" for node in item.iter() if tag(node) == "t")
                    for item in xml("xl/sharedStrings.xml")
                    if tag(item) == "si"
                ]
            sheets = sorted(
                (
                    name
                    for name in archive.namelist()
                    if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name)
                ),
                key=sort_key,
            )
            for name in sheets:
                parts.append(f"[{name}]")
                for row in xml(name).iter():
                    if tag(row) != "row":
                        continue
                    cells = []
                    for cell in row:
                        if tag(cell) != "c":
                            continue
                        value = "".join(
                            node.text or "" for node in cell.iter() if tag(node) == "v"
                        )
                        if cell.get("t") == "s":
                            value = shared[int(value)]
                        elif cell.get("t") == "inlineStr":
                            value = "".join(
                                node.text or ""
                                for node in cell.iter()
                                if tag(node) == "t"
                            )
                        formula = next(
                            (node.text for node in cell if tag(node) == "f"), None
                        )
                        if formula and not value:
                            value = f"={formula}"
                        cells.append(f"{cell.get('r', '?')}={value}")
                    parts.append("\t".join(cells))
        text = "\n".join(parts)
        if len(text) > MAX_TEXT_CHARS:
            raise ValueError("Extracted text exceeds the 2 Mi character limit")
        return text
