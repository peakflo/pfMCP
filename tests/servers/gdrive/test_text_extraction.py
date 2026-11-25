"""Exercise parsers with real in-memory PDF/Office files, not mocked text."""

import io
import zipfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

from src.servers.gdrive import main as drive
from src.servers.gdrive import text_extraction as extraction
from mcp import types

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


def office(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def pdf(text="Hello PDF", encrypted=False):
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    if text:
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        page[NameObject("/Resources")] = DictionaryObject(
            {
                NameObject("/Font"): DictionaryObject(
                    {NameObject("/F1"): writer._add_object(font)}
                )
            }
        )
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode())
        page[NameObject("/Contents")] = writer._add_object(stream)
    if encrypted:
        writer.encrypt("password")
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def test_pdf_text():
    assert "Hello PDF" in extraction.extract_text(pdf(), "application/pdf")


def test_scanned_pdf_reports_ocr_requirement():
    with pytest.raises(ValueError, match="require OCR"):
        extraction.extract_text(pdf(text=""), "application/pdf")


def test_encrypted_pdf_is_reported():
    with pytest.raises(ValueError, match="Encrypted"):
        extraction.extract_text(pdf(encrypted=True), "application/pdf")


def test_pdf_page_and_stream_limits():
    with patch.object(extraction, "MAX_PDF_PAGES", 0):
        with pytest.raises(ValueError, match="page extraction limit"):
            extraction.extract_text(pdf(), "application/pdf")
    with patch.object(extraction, "MAX_EXPANDED_BYTES", 1):
        with pytest.raises(ValueError, match="page content"):
            extraction.extract_text(pdf(), "application/pdf")


def test_docx_paragraphs_and_tables():
    data = office(
        {
            "word/document.xml": """<w:document xmlns:w="urn:test"><w:body>
    <w:p><w:r><w:t>Hello</w:t><w:tab/><w:t>world</w:t></w:r></w:p>
    <w:tbl><w:tr><w:tc><w:p><w:r><w:t>Cell</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
    </w:body></w:document>"""
        }
    )
    assert extraction.extract_text(data, DOCX) == "Hello\tworld\nCell"


def test_xlsx_shared_inline_and_sparse_cells():
    data = office(
        {
            "xl/sharedStrings.xml": "<sst><si><t>Shared</t></si></sst>",
            "xl/worksheets/sheet1.xml": '<worksheet><sheetData><row><c r="A1" t="s"><v>0</v></c><c r="C1"><v>42</v></c><c r="D1" t="inlineStr"><is><t>Inline</t></is></c><c r="E1"><f>SUM(C1)</f></c></row></sheetData></worksheet>',
            "xl/worksheets/sheet2.xml": '<worksheet><sheetData><row><c r="A1"><v>2</v></c></row></sheetData></worksheet>',
        }
    )
    text = extraction.extract_text(data, XLSX)
    assert "A1=Shared\tC1=42\tD1=Inline\tE1==SUM(C1)" in text
    assert "[xl/worksheets/sheet2.xml]" in text and "A1=2" in text


def test_pptx_natural_slide_order():
    data = office(
        {
            f"ppt/slides/slide{n}.xml": f"<slide><p><t>Slide {n}</t></p></slide>"
            for n in (10, 2, 1)
        }
    )
    assert extraction.extract_text(data, PPTX) == "Slide 1\nSlide 2\nSlide 10"


def test_zip_expansion_limit():
    data = office({"word/document.xml": "x" * 100})
    with patch.object(extraction, "MAX_EXPANDED_BYTES", 10):
        with pytest.raises(ValueError, match="expanded size"):
            extraction.extract_text(data, DOCX)


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16"])
def test_entities_rejected(encoding):
    data = office(
        {
            "word/document.xml": '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "expanded">]><document>&a;</document>'.encode(
                encoding
            )
        }
    )
    with pytest.raises(Exception):
        extraction.extract_text(data, DOCX)


def test_output_limit_and_unknown_format():
    data = office({"word/document.xml": "<doc><p><t>long text</t></p></doc>"})
    with patch.object(extraction, "MAX_TEXT_CHARS", 2):
        with pytest.raises(ValueError, match="text exceeds"):
            extraction.extract_text(data, DOCX)
    with pytest.raises(ValueError, match="not supported"):
        extraction.extract_text(b"legacy", "application/msword")


async def test_extraction_tool_returns_paged_text():
    import json

    content = office({"word/document.xml": "<doc><p><t>Hello world</t></p></doc>"})
    api = MagicMock()
    api.files().get().execute.return_value = {
        "id": "doc",
        "name": "Doc",
        "mimeType": DOCX,
    }
    with patch.object(
        drive, "create_drive_service", AsyncMock(return_value=api)
    ), patch.object(drive, "download_content", return_value=content):
        result = await drive.create_server("test").dispatch(
            types.CallToolRequest(
                method="tools/call",
                params=types.CallToolRequestParams(
                    name="extract_file_text",
                    arguments={"file_id": "doc", "offset": 6, "max_chars": 3},
                ),
            )
        )
    assert not result.is_error
    data = json.loads(result.content[0].text)
    assert data["content"] == "wor" and data["next_offset"] == 9
