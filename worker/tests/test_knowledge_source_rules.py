"""Source-shaped synthetic DOMs verify pilot selectors without political claims."""

from parliament_worker.knowledge.extract import extract_document


def source_spec(document_id):
    """Use source-shaped selectors with synthetic identities and no live input."""
    selectors = {
        "doc-bill-2201707": {
            "bodySelector": "#containerWrap",
            "titleSelector": "#containerWrap h2.subjectHead_tit",
        },
        "doc-child-support-followup": {
            "bodySelector": "td.brdViewCont",
            "titleSelector": ".brdView01 th[colspan]",
            "publishedSelector": 'td[headers="W_th03"]',
        },
    }
    return {
        "id": document_id,
        "sourceKey": "synthetic-selector",
        "recordKey": document_id,
        "sourceUrl": "https://www.mogef.go.kr/synthetic",
        "format": "html",
        **selectors[document_id],
    }


def test_legislative_content_selector_keeps_bill_detail_without_site_navigation():
    raw = b"<nav>site navigation</nav><div id='containerWrap'><h2 class='subjectHead_tit'>synthetic bill</h2><table><tr><td>synthetic proposer</td></tr></table></div>"
    result = extract_document(raw, source_spec("doc-bill-2201707"), [])
    assert result["bodyStatus"] == "available"
    assert result["title"] == "synthetic bill"
    assert "synthetic proposer" in [item["text"] for item in result["segments"]]
    assert all("site navigation" not in item["text"] for item in result["segments"])


def test_ministry_press_title_is_current_article_not_related_previous_article():
    raw = b"<table class='brdView01'><tr><th colspan='4'>synthetic current article</th></tr><tr><td headers='W_th03'>2024-01-01</td></tr><tr><td class='brdViewCont'><p>synthetic announced plan</p></td></tr></table><table class='brdView01'><tbody><tr><td>synthetic previous article</td></tr></tbody></table>"
    result = extract_document(raw, source_spec("doc-child-support-followup"), [])
    assert result["title"] == "synthetic current article"
    assert result["publishedAt"].startswith("2024-01-01")
    assert result["publishedPrecision"] == "day"
    assert [item["text"] for item in result["segments"]] == ["synthetic announced plan"]
