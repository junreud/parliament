"""PDF processing limits and safe diagnostic categories are explicit."""

import io

from pypdf import PdfWriter
from pypdf.generic import (
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
)

from parliament_worker.knowledge.extract import extract_document


def pdf_bytes(count):
    """Build a synthetic text PDF; no source-government records are fabricated."""
    writer = PdfWriter()
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    for number in range(count):
        page = writer.add_blank_page(width=100, height=100)
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
        )
        content = DecodedStreamObject()
        content.set_data(
            f"BT /F1 10 Tf 5 5 Td (synthetic page {number + 1}) Tj ET".encode()
        )
        page[NameObject("/Contents")] = writer._add_object(content)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def test_pdf_page_limit_remains_visible_in_private_extraction(monkeypatch):
    def too_long(raw):
        raise ValueError("page_limit")

    monkeypatch.setattr("parliament_worker.knowledge.extract.pdf_pages", too_long)
    result = extract_document(
        b"%PDF synthetic", {"id": "synthetic-doc", "format": "pdf"}, []
    )
    assert result["bodyStatus"] == "extraction_failed"
    assert result["failureCategory"] == "page_limit"


def test_pdf_untrusted_error_details_are_not_copied_to_extraction(monkeypatch):
    def fail(raw):
        raise ValueError("sensitive local path or content")

    monkeypatch.setattr("parliament_worker.knowledge.extract.pdf_pages", fail)
    result = extract_document(
        b"%PDF synthetic", {"id": "synthetic-doc", "format": "pdf"}, []
    )
    assert result["failureCategory"] == "invalid_pdf"


def test_explicit_selected_pages_obey_30_page_processing_limit_and_show_partial():
    result = extract_document(
        pdf_bytes(50), {"id": "synthetic-doc", "format": "pdf", "pdfPages": [1, 2]}, []
    )
    assert result["bodyStatus"] == "partial"
    assert result["pageCount"] == 50 and result["extractedPages"] == [1, 2]
    assert [segment["locator"] for segment in result["segments"]] == [
        "pdf:page[1]",
        "pdf:page[2]",
    ]
    assert [segment["text"].strip() for segment in result["segments"]] == [
        "synthetic page 1",
        "synthetic page 2",
    ]


def test_selected_page_outside_original_is_explicit_failure():
    result = extract_document(
        pdf_bytes(2), {"id": "synthetic-doc", "format": "pdf", "pdfPages": [3]}, []
    )
    assert result["bodyStatus"] == "extraction_failed"
    assert result["failureCategory"] == "page_selection_out_of_range"


def test_selected_more_than_30_pages_is_rejected_before_processing():
    result = extract_document(
        pdf_bytes(50),
        {"id": "synthetic-doc", "format": "pdf", "pdfPages": list(range(1, 32))},
        [],
    )
    assert result["bodyStatus"] == "extraction_failed"
    assert result["failureCategory"] == "page_selection_limit"


def test_all_selected_pages_of_a_small_pdf_are_available():
    result = extract_document(
        pdf_bytes(2), {"id": "synthetic-doc", "format": "pdf", "pdfPages": [1, 2]}, []
    )
    assert result["bodyStatus"] == "available"
    assert result["pageCount"] == 2 and result["extractedPages"] == [1, 2]
