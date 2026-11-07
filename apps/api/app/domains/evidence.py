"""Evidence retrieval, citation validation and server-side policy gates.

The model proposes; this module decides what may be stored:
- only refs from the server-built candidate list are accepted (fabricated refs reject the output);
- displayed quotes are always taken from the stored source span, never from model text;
- category gates are applied deterministically (e.g. "contract is silent" can never become a paid change).
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DocumentVersion, ScopeEvidence, ScopeItem, SourceSpan
from app.parsing.parser import anchor_label, normalize

CATEGORIES = ("IN_SCOPE", "BUG_FIX", "CHANGE_CANDIDATE", "AMBIGUOUS", "INSUFFICIENT_EVIDENCE")
ALWAYS_REVIEW = {"CHANGE_CANDIDATE", "AMBIGUOUS", "INSUFFICIENT_EVIDENCE"}
WARRANTY_WORDS = ("warrant", "guarantee", "defect", "bug", "acceptance", "гарант", "дефект", "ошиб", "приёмк", "приемк")
_WORD = re.compile(r"[\w]+", re.UNICODE)
_STOP = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "please",
    "also",
    "add",
    "make",
    "our",
    "your",
    "from",
    "into",
    "will",
    "would",
    "could",
    "should",
    "need",
    "want",
    "have",
    "has",
    "can",
    "you",
    "are",
    "was",
    "что",
    "это",
    "для",
    "как",
    "ещё",
    "еще",
    "также",
    "нужно",
    "надо",
    "пожалуйста",
    "сделайте",
    "добавьте",
    "чтобы",
    "или",
    "при",
    "все",
    "наш",
    "нам",
    "вас",
}


@dataclass
class Candidate:
    ref: str
    span: SourceSpan
    doc: DocumentVersion
    scope_items: list[tuple[uuid.UUID, str, str]] = field(default_factory=list)  # (id, title, inclusion_type)
    retrieved: bool = False

    @property
    def inclusion_types(self) -> set[str]:
        return {t for _, _, t in self.scope_items}

    def prompt_dict(self) -> dict[str, Any]:
        primary = self.scope_items[0] if self.scope_items else None
        return {
            "ref": self.ref,
            "text": self.span.normalized_text,
            "inclusion_type": " / ".join(sorted(self.inclusion_types)) if primary else None,
            "scope_item_title": "; ".join(t for _, t, _ in self.scope_items) if primary else None,
            "retrieved": self.retrieved,
            "location": f"{self.doc.title}, {anchor_label(self.span.anchor_type, self.span.page, self.span.paragraph_index, self.span.table_ref)}",
        }


def query_terms(text_: str, limit: int = 12) -> list[str]:
    """Prefix terms for PostgreSQL full-text search ('simple' config, crude stemming via prefixes)."""
    seen: dict[str, None] = {}
    for w in _WORD.findall(text_.lower()):
        if len(w) < 3 or w in _STOP or w.isdigit():
            continue
        stem = w[: max(4, len(w) - 2)] if len(w) > 5 else w
        seen.setdefault(stem, None)
    return list(seen)[:limit]


async def baseline_candidates(session: AsyncSession, baseline_id: uuid.UUID) -> list[Candidate]:
    """All source spans cited by the approved baseline's scope items (always part of the context)."""
    rows = await session.execute(
        select(ScopeItem, SourceSpan, DocumentVersion)
        .join(ScopeEvidence, ScopeEvidence.scope_item_id == ScopeItem.id)
        .join(SourceSpan, SourceSpan.id == ScopeEvidence.source_span_id)
        .join(DocumentVersion, DocumentVersion.id == SourceSpan.document_version_id)
        .where(ScopeItem.baseline_id == baseline_id)
        .order_by(ScopeItem.ordinal, SourceSpan.ordinal)
    )
    by_span: dict[uuid.UUID, Candidate] = {}
    for item, span, doc in rows.all():
        cand = by_span.get(span.id)
        if cand is None:
            cand = Candidate(ref="", span=span, doc=doc)
            by_span[span.id] = cand
        cand.scope_items.append((item.id, item.title, item.inclusion_type))
    return list(by_span.values())


async def retrieve_text_matches(
    session: AsyncSession,
    *,
    document_version_ids: list[uuid.UUID],
    requirement: str,
    exclude_span_ids: set[uuid.UUID],
    limit: int = 8,
) -> list[Candidate]:
    """Full-text matches in the baseline documents that are NOT already scope-item evidence
    (e.g. warranty clauses or broad wording the manager did not turn into items)."""
    terms = query_terms(requirement)
    if not terms or not document_version_ids:
        return []
    tsquery = " | ".join(f"{t}:*" for t in terms)
    rows = await session.execute(
        text(
            """
            SELECT s.id, ts_rank(s.tsv, q) AS rank
            FROM source_spans s, to_tsquery('simple', :q) q
            WHERE s.document_version_id = ANY(:docs) AND s.tsv @@ q
            ORDER BY rank DESC, s.ordinal
            LIMIT :lim
            """
        ),
        {"q": tsquery, "docs": document_version_ids, "lim": limit + len(exclude_span_ids)},
    )
    ids = [r[0] for r in rows.all() if r[0] not in exclude_span_ids][:limit]
    if not ids:
        return []
    found = await session.execute(
        select(SourceSpan, DocumentVersion)
        .join(DocumentVersion, DocumentVersion.id == SourceSpan.document_version_id)
        .where(SourceSpan.id.in_(ids))
    )
    by_id = {s.id: Candidate(ref="", span=s, doc=d, retrieved=True) for s, d in found.all()}
    return [by_id[i] for i in ids if i in by_id]


def assemble_candidates(
    scope_cands: list[Candidate], retrieved: list[Candidate], requirement: str, max_chars: int
) -> list[Candidate]:
    """Order and budget the evidence: exclusions and conditions are always kept (they are the
    counter-evidence that prevents one-sided answers), then the most relevant included items."""
    req_terms = set(query_terms(requirement, limit=30))

    def relevance(c: Candidate) -> int:
        words = set(query_terms(c.span.normalized_text + " " + " ".join(t for _, t, _ in c.scope_items), 60))
        return sum(1 for w in words if any(w.startswith(t[:4]) or t.startswith(w[:4]) for t in req_terms))

    must = [c for c in scope_cands if c.inclusion_types & {"EXCLUDED", "CONDITION"}]
    rest = sorted((c for c in scope_cands if c not in must), key=relevance, reverse=True)
    ordered = must + rest + retrieved
    out: list[Candidate] = []
    used = 0
    for c in ordered:
        size = len(c.span.normalized_text)
        if out and used + size > max_chars:
            continue
        out.append(c)
        used += size
    for i, c in enumerate(out, start=1):
        c.ref = f"E{i}"
    return out


# ------------------------------------------------------------------------------------------------
# Validation + policy gates (pure)
# ------------------------------------------------------------------------------------------------


@dataclass
class Citation:
    candidate: Candidate
    quote: str


@dataclass
class GatedFinding:
    category: str
    ai_category: str | None
    summary: str
    reason: str
    supporting: list[Citation]
    counter: list[Citation]
    uncertainties: list[str]
    clarifying_questions: list[str]
    model_confidence: Decimal | None
    needs_review: bool
    policy_notes: list[str]
    validation_errors: list[str]


class FabricatedEvidence(Exception):
    def __init__(self, refs: list[str]) -> None:
        super().__init__(f"unknown evidence refs: {refs}")
        self.refs = refs


def _match_quote(candidate: Candidate, quote: str) -> tuple[str, bool]:
    """Return (server-sourced quote, matched). The quote shown to users is always a substring of
    the stored span text; if the model's quote does not match, the whole span is shown."""
    source = candidate.span.normalized_text
    q = normalize(quote or "").strip(" \"'«»“”.")
    if q:
        idx = source.casefold().find(q.casefold())
        if idx >= 0 and len(q) >= 3:
            return source[idx : idx + len(q)], True
    return source, False


def _str_list(value: Any, limit: int = 10) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(v).strip()[:500] for v in value if str(v).strip()][:limit]


def check_refs(raw: dict[str, Any], candidates: dict[str, Candidate]) -> list[str]:
    refs = []
    for key in ("supporting_evidence", "counter_evidence"):
        for ev in raw.get(key) or []:
            ref = ev.get("ref") if isinstance(ev, dict) else None
            if not isinstance(ref, str) or ref not in candidates:
                refs.append(str(ref))
    return refs


def gate(raw: dict[str, Any], candidates: dict[str, Candidate], *, fabricated: list[str] | None = None) -> GatedFinding:
    notes: list[str] = []
    errors: list[str] = []
    ai_category = raw.get("category") if raw.get("category") in CATEGORIES else None
    summary = str(raw.get("summary") or "").strip()[:500]
    reason = str(raw.get("reason") or "").strip()[:2000]
    uncertainties = _str_list(raw.get("uncertainties"))
    questions = _str_list(raw.get("clarifying_questions"))
    try:
        conf_raw = float(raw.get("model_confidence"))  # type: ignore[arg-type]
        confidence: Decimal | None = Decimal(str(round(min(1.0, max(0.0, conf_raw)), 3)))
    except (TypeError, ValueError):
        confidence = None

    if fabricated:
        errors.append("UNKNOWN_EVIDENCE_REF:" + ",".join(fabricated))
        notes.append("POLICY_REJECTED_FABRICATED_EVIDENCE")
        return GatedFinding(
            "INSUFFICIENT_EVIDENCE",
            ai_category,
            summary,
            reason,
            [],
            [],
            uncertainties,
            questions,
            confidence,
            True,
            notes,
            errors,
        )
    if ai_category is None:
        errors.append("INVALID_CATEGORY")
        return GatedFinding(
            "INSUFFICIENT_EVIDENCE",
            None,
            summary,
            reason,
            [],
            [],
            uncertainties,
            questions,
            confidence,
            True,
            ["POLICY_INVALID_MODEL_OUTPUT"],
            errors,
        )

    def cites(key: str) -> list[Citation]:
        out: list[Citation] = []
        seen: set[str] = set()
        for ev in raw.get(key) or []:
            ref = ev["ref"]
            if ref in seen:
                continue
            seen.add(ref)
            quote, matched = _match_quote(candidates[ref], str(ev.get("quote") or ""))
            if not matched:
                errors.append(f"QUOTE_NOT_IN_SOURCE:{ref}")
            out.append(Citation(candidates[ref], quote))
        return out

    supporting = cites("supporting_evidence")
    counter = cites("counter_evidence")
    category = ai_category
    support_types = {t for c in supporting for t in c.candidate.inclusion_types}
    retrieved_support = any(c.candidate.retrieved for c in supporting)

    if not supporting:
        if category == "CHANGE_CANDIDATE":
            category = "AMBIGUOUS"
            notes.append("POLICY_SILENCE_IS_NOT_CHANGE")
        elif category in ("IN_SCOPE", "BUG_FIX"):
            category = "INSUFFICIENT_EVIDENCE"
            notes.append("POLICY_NO_SUPPORTING_EVIDENCE")
    elif category in ("IN_SCOPE", "BUG_FIX"):
        if "INCLUDED" not in support_types and not retrieved_support:
            category = "AMBIGUOUS"
            notes.append("POLICY_INCONSISTENT_EVIDENCE")
    elif category == "CHANGE_CANDIDATE":
        if not support_types & {"EXCLUDED", "CONDITION"} and not retrieved_support:
            # Only "included" items were cited as proof of a change: the model's reasoning is about
            # exceeding what's included; keep it but flag it.
            notes.append("POLICY_CHANGE_WITHOUT_EXPLICIT_EXCLUSION")

    needs_review = category in ALWAYS_REVIEW
    if counter:
        needs_review = True
        notes.append("POLICY_CONFLICTING_EVIDENCE")
    if category == "BUG_FIX":
        cited = supporting + counter
        has_warranty = any(
            "CONDITION" in c.candidate.inclusion_types
            or any(w in c.candidate.span.normalized_text.lower() for w in WARRANTY_WORDS)
            for c in cited
        )
        if not has_warranty:
            needs_review = True
            notes.append("POLICY_WARRANTY_UNVERIFIED")
    if confidence is not None and confidence < Decimal("0.5"):
        needs_review = True
        notes.append("POLICY_LOW_MODEL_CONFIDENCE")
    if any(e.startswith("QUOTE_NOT_IN_SOURCE") for e in errors):
        needs_review = True
    return GatedFinding(
        category,
        ai_category,
        summary,
        reason,
        supporting,
        counter,
        uncertainties,
        questions,
        confidence,
        needs_review,
        notes,
        errors,
    )


# ------------------------------------------------------------------------------------------------
# Requirement splitting validation (pure)
# ------------------------------------------------------------------------------------------------


@dataclass
class SplitItem:
    exact_text: str
    start: int
    end: int
    summary: str


def locate_requirements(message: str, raw_items: list[dict[str, Any]]) -> tuple[list[SplitItem], list[str]]:
    """Map model-proposed requirement texts to exact substrings of the message.

    Only verbatim (or case-insensitive verbatim) substrings are accepted; anything else is
    dropped and reported. If nothing valid remains, the whole message becomes one requirement.
    """
    notes: list[str] = []
    out: list[SplitItem] = []
    cursor = 0
    lowered = message.casefold()
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        frag = str(raw.get("exact_text") or "").strip()
        if len(frag) < 2:
            continue
        idx = message.find(frag, cursor)
        if idx < 0:
            idx = message.find(frag)
        if idx < 0:
            idx = lowered.find(frag.casefold(), cursor)
        if idx < 0:
            notes.append("SPLIT_TEXT_NOT_IN_MESSAGE")
            continue
        end = idx + len(frag)
        if any(not (end <= o.start or idx >= o.end) for o in out):
            notes.append("SPLIT_OVERLAP_DROPPED")
            continue
        out.append(SplitItem(message[idx:end], idx, end, str(raw.get("summary") or "").strip()[:300]))
        cursor = end
    out.sort(key=lambda s: s.start)
    if not out and message.strip():
        stripped = message.strip()
        start = message.find(stripped)
        out = [SplitItem(stripped, start, start + len(stripped), "")]
        notes.append("SPLIT_FALLBACK_WHOLE_MESSAGE")
    return out, notes
