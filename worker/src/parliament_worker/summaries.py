"""Immutable local explanation drafts with provenance and mandatory human review."""

import json
from dataclasses import asdict
from datetime import datetime
from hashlib import sha256
from pathlib import Path

from parliament_worker.models import SourceDocument
from parliament_worker.provider import OpenAISummaryProvider
from parliament_worker.review import ReviewLedger, generate_draft


def prepare_summary(
    document: SourceDocument,
    provider: OpenAISummaryProvider,
    ledger: ReviewLedger,
    root: Path,
    now: datetime,
) -> Path:
    """Save a grounded explanation draft; retries reuse identical request inputs.

    Args:
        document: An original version with verified text reuse permission.
        provider: Explicitly configured optional paid HTTP provider.
        ledger: Persistent monthly budget reservations and measured usage.
        root: Explicit local output directory; no backend is contacted.
        now: Cost reservation time in the operator's timezone.

    Returns:
        Immutable draft file path, including its content hash.
    """
    cache_key = provider.cache_key(document)
    directory = root / "summary_drafts" / document.identity / document.payload_hash
    pointer = directory / f"request_{cache_key}.json"
    if pointer.exists():
        cached = json.loads(pointer.read_text(encoding="utf-8"))
        existing = directory / cached["file"]
        if existing.parent != directory or not existing.is_file():
            raise ValueError("immutable draft index invalid")
        return existing
    draft, errors = generate_draft(provider, document, ledger, now)
    if draft.provenance is None:
        raise ValueError("provider provenance required")
    provenance = draft.provenance
    value = {
        "sourceKey": document.source_key,
        "recordKey": document.record_key,
        "sourceUrl": document.source_url,
        "sourceHash": document.payload_hash,
        "parserVersion": provenance.parser_version,
        "promptVersion": provenance.prompt_version,
        "provider": {
            "requestedModel": provenance.requested_model,
            "model": provenance.actual_model,
            "responseId": provenance.response_id,
            "generatedAt": provenance.generated_at,
            "promptTokens": provenance.prompt_tokens,
            "completionTokens": provenance.completion_tokens,
            "measuredCostKrw": (
                str(provenance.actual_cost_krw)
                if provenance.actual_cost_krw is not None
                else None
            ),
            "priceBasis": "operator_configured_token_rates",
            "inputKrwPerMillion": provenance.input_krw_per_million,
            "outputKrwPerMillion": provenance.output_krw_per_million,
        },
        "sourceTextTruncated": provenance.source_text_truncated,
        "oneLine": draft.one_line,
        "claims": [asdict(claim) for claim in draft.claims],
        "validationErrors": errors,
        "status": "blocked" if errors else "pending_review",
        "requiresHumanReview": True,
    }
    digest = sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()
    value["draftHash"] = digest
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{digest}.json"
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
    with pointer.open("x", encoding="utf-8") as handle:
        json.dump({"file": path.name, "draftHash": digest}, handle)
    return path
