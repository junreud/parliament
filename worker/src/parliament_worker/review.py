"""Mechanical claim validation and persistent human-review/model-cost limits."""

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from parliament_worker.content import require_summary_body
from parliament_worker.models import SEOUL, SourceDocument


@dataclass(frozen=True)
class Claim:
    """A proposed sentence and the exact raw-version excerpt that supports it."""

    text: str
    evidence_id: str
    excerpt: str
    source_version: str


@dataclass(frozen=True)
class DraftProvenance:
    """Immutable source/parser/model versions and measured, configured-rate cost."""

    source_hash: str
    parser_version: str
    prompt_version: str
    requested_model: str
    actual_model: str
    response_id: str
    generated_at: str
    prompt_tokens: int | None
    completion_tokens: int | None
    actual_cost_krw: Decimal | None
    source_text_truncated: bool = False
    input_krw_per_million: str | None = None
    output_krw_per_million: str | None = None


@dataclass(frozen=True)
class SummaryDraft:
    """Unpublished text that still requires a human semantic review."""

    one_line: str
    claims: list[Claim]
    provenance: DraftProvenance | None = None


class SummaryProvider(Protocol):
    """Optional model integration; no provider is invoked automatically."""

    def estimate_krw(self, document: SourceDocument) -> Decimal:
        """Return a conservative maximum cost in KRW before making a request."""
        ...

    def generate(self, document: SourceDocument) -> SummaryDraft:
        """Generate a draft with claim-to-evidence references, never a public event."""
        ...


def validate_draft(draft: SummaryDraft, document: SourceDocument) -> list[str]:
    """Validate reference integrity; semantic entailment still needs human review."""
    errors: set[str] = set()
    if not draft.one_line.strip() or not draft.claims:
        errors.add("claims_required")
    expected_id = f"ev_{document.identity}"
    for claim in draft.claims:
        if claim.evidence_id != expected_id:
            errors.add("evidence_missing")
        if claim.source_version != document.payload_hash:
            errors.add("source_version_mismatch")
        if not claim.excerpt or claim.excerpt not in document.body:
            errors.add("excerpt_not_in_source")
        if not claim.text.strip():
            errors.add("claim_text_missing")
    return sorted(errors)


class ReviewLedger:
    """Atomic persistent caps: at most three approvals/day, finite monthly spend."""

    def __init__(
        self,
        path: Path,
        *,
        monthly_budget: Decimal = Decimal("100000"),
        daily_cap: int = 3,
    ) -> None:
        if (
            not monthly_budget.is_finite()
            or monthly_budget < 0
            or not 1 <= daily_cap <= 3
        ):
            raise ValueError("invalid budget or review cap")
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, isolation_level=None)
        self.monthly_budget = monthly_budget
        self.daily_cap = daily_cap
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS approvals (identity TEXT PRIMARY KEY, day TEXT NOT NULL)"
        )
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS costs (month TEXT PRIMARY KEY, amount TEXT NOT NULL)"
        )
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS provider_requests (request_id TEXT PRIMARY KEY, "
            "month TEXT NOT NULL, reserved TEXT NOT NULL, actual TEXT, status TEXT NOT NULL)"
        )

    def approve(self, identity: str, now: datetime) -> None:
        """Record one version-bound approval without exceeding the Seoul daily cap."""
        day = now.astimezone(SEOUL).date().isoformat()
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            if self.connection.execute(
                "SELECT 1 FROM approvals WHERE identity=?", (identity,)
            ).fetchone():
                self.connection.commit()
                return
            count = self.connection.execute(
                "SELECT COUNT(*) FROM approvals WHERE day=?", (day,)
            ).fetchone()[0]
            if count >= self.daily_cap:
                raise ValueError("daily review cap exceeded")
            self.connection.execute(
                "INSERT INTO approvals VALUES (?,?)", (identity, day)
            )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    def available(self, now: datetime) -> Decimal:
        """Return the remaining monthly reserved cost allowance in KRW."""
        month = now.astimezone(SEOUL).strftime("%Y-%m")
        row = self.connection.execute(
            "SELECT amount FROM costs WHERE month=?", (month,)
        ).fetchone()
        spent = Decimal(row[0]) if row else Decimal("0")
        return max(Decimal("0"), self.monthly_budget - spent)

    def record_cost(self, amount: Decimal, now: datetime) -> None:
        """Reserve cost before a provider call, atomically and conservatively."""
        if not amount.is_finite() or amount < 0:
            raise ValueError("invalid cost")
        month = now.astimezone(SEOUL).strftime("%Y-%m")
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            remaining = self.available(now)
            if amount > remaining:
                raise ValueError("monthly budget exceeded")
            row = self.connection.execute(
                "SELECT amount FROM costs WHERE month=?", (month,)
            ).fetchone()
            total = (Decimal(row[0]) if row else Decimal("0")) + amount
            self.connection.execute(
                "INSERT INTO costs VALUES (?,?) ON CONFLICT(month) DO UPDATE SET amount=excluded.amount",
                (month, str(total)),
            )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    def reserve_request(self, amount: Decimal, now: datetime) -> str:
        """Atomically reserve a provider request before any paid HTTP call."""
        if not amount.is_finite() or amount < 0:
            raise ValueError("invalid cost")
        month = now.astimezone(SEOUL).strftime("%Y-%m")
        request_id = uuid4().hex
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            if self.connection.execute(
                "SELECT 1 FROM provider_requests WHERE month=? AND status='overrun' LIMIT 1",
                (month,),
            ).fetchone():
                raise ValueError(
                    "budget estimate overrun requires operator reconciliation"
                )
            row = self.connection.execute(
                "SELECT amount FROM costs WHERE month=?", (month,)
            ).fetchone()
            spent = Decimal(row[0]) if row else Decimal("0")
            if spent + amount > self.monthly_budget:
                raise ValueError("monthly budget exceeded")
            self.connection.execute(
                "INSERT INTO costs VALUES (?,?) ON CONFLICT(month) DO UPDATE SET amount=excluded.amount",
                (month, str(spent + amount)),
            )
            self.connection.execute(
                "INSERT INTO provider_requests VALUES (?,?,?,?,?)",
                (request_id, month, str(amount), None, "reserved"),
            )
            self.connection.commit()
            return request_id
        except Exception:
            self.connection.rollback()
            raise

    def settle_request(self, request_id: str, actual: Decimal) -> None:
        """Replace a reservation with measured usage; record an overrun honestly."""
        if not actual.is_finite() or actual < 0:
            raise ValueError("invalid measured cost")
        self.connection.execute("BEGIN IMMEDIATE")
        overrun = False
        try:
            row = self.connection.execute(
                "SELECT month,reserved,actual,status FROM provider_requests WHERE request_id=?",
                (request_id,),
            ).fetchone()
            if row is None:
                raise ValueError("provider reservation missing")
            month, reserved, previous, status = row
            if status != "reserved":
                if previous != str(actual):
                    raise ValueError("immutable measured cost conflict")
                self.connection.commit()
                return
            spent = Decimal(
                self.connection.execute(
                    "SELECT amount FROM costs WHERE month=?", (month,)
                ).fetchone()[0]
            )
            reserved_amount = Decimal(reserved)
            updated = spent - reserved_amount + actual
            overrun = actual > reserved_amount or updated > self.monthly_budget
            self.connection.execute(
                "UPDATE costs SET amount=? WHERE month=?", (str(updated), month)
            )
            self.connection.execute(
                "UPDATE provider_requests SET actual=?,status=? WHERE request_id=?",
                (str(actual), "overrun" if overrun else "settled", request_id),
            )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        if overrun:
            raise ValueError("provider measured cost exceeded reserved budget")

    def close(self) -> None:
        """Close the ledger connection."""
        self.connection.close()


def generate_draft(
    provider: SummaryProvider,
    document: SourceDocument,
    ledger: ReviewLedger,
    now: datetime,
) -> tuple[SummaryDraft, list[str]]:
    """Explicitly invoke an injected provider within budget, returning a draft only.

    A failed provider call retains its conservative cost reservation. Generated
    claims are never implicitly approved or published by this function.
    """
    if document.license_status != "allowed":
        raise ValueError("source reuse permission not verified")
    require_summary_body(document)
    reservation = ledger.reserve_request(provider.estimate_krw(document), now)
    draft = provider.generate(document)
    if draft.provenance and draft.provenance.actual_cost_krw is not None:
        ledger.settle_request(reservation, draft.provenance.actual_cost_krw)
    return draft, validate_draft(draft, document)
