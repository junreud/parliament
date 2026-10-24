"""Disposable PDF extraction subprocess; stdout is a bounded JSON protocol."""

import io
import json
import sys

MAX_BYTES = 10_000_000
MAX_PAGES = 30
MAX_TEXT_CHARS = 2_000_000


def main() -> int:
    """Read one bounded PDF and return its page text or a safe failure category."""
    try:
        from pypdf import PdfReader
    except ImportError:
        sys.stdout.write("missing_pdf_dependency")
        return 1
    try:
        raw = sys.stdin.buffer.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError("size_limit")
        reader = PdfReader(io.BytesIO(raw))
        if reader.is_encrypted:
            raise ValueError("encrypted_pdf")
        page_count = len(reader.pages)
        requested = (
            json.loads(sys.argv[2])
            if len(sys.argv) == 3 and sys.argv[1] == "--pages"
            else None
        )
        if requested is not None and (
            not isinstance(requested, list)
            or not requested
            or any(type(page) is not int or page < 1 for page in requested)
            or len(set(requested)) != len(requested)
        ):
            raise ValueError("invalid_page_selection")
        if requested is not None and len(requested) > MAX_PAGES:
            raise ValueError("page_selection_limit")
        if requested is not None and any(page > page_count for page in requested):
            raise ValueError("page_selection_out_of_range")
        if requested is None and page_count > MAX_PAGES:
            raise ValueError("page_limit")
        selected = (
            sorted(requested)
            if requested is not None
            else list(range(1, page_count + 1))
        )
        texts = []
        length = 0
        for number in selected:
            page = reader.pages[number - 1]
            text = page.extract_text() or ""
            length += len(text)
            if length > MAX_TEXT_CHARS:
                raise ValueError("text_limit")
            texts.append(text)
        sys.stdout.write(
            json.dumps(
                {"pageCount": page_count, "extractedPages": selected, "texts": texts},
                ensure_ascii=False,
            )
        )
        return 0
    except Exception as error:
        category = str(error)
        sys.stdout.write(
            category
            if category
            in {
                "size_limit",
                "encrypted_pdf",
                "page_limit",
                "text_limit",
                "invalid_page_selection",
                "page_selection_limit",
                "page_selection_out_of_range",
            }
            else "invalid_pdf"
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
