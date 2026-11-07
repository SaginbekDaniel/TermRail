"""Unit tests: parser anchors, requirement splitting, evidence gates, money, LLM adapter, config guards."""

from __future__ import annotations

import json
import uuid
from decimal import Decimal

import httpx
import pymupdf
import pytest

from app.core.config import Settings
from app.core.errors import Unprocessable
from app.domains.evidence import Candidate, check_refs, gate, locate_requirements, query_terms
from app.domains.money import line_amount, to_decimal, total
from app.llm.base import LLMInvalidOutput, LLMNotConfigured, LLMUnavailable
from app.llm.openai_compat import OpenAICompatibleProvider
from app.parsing.parser import DOCX_MIME, PDF_MIME, ParseError, parse_document, sniff_mime
from tests.conftest import FIXTURES

# ------------------------------------------------------------------------------------- parser


def test_pdf_spans_have_exact_page_offsets() -> None:
    data = (FIXTURES / "scope_contract.pdf").read_bytes()
    doc = parse_document(data, sniff_mime(data, "x.pdf"))
    assert doc.status == "PARSED"
    assert doc.page_count == 1
    pdf = pymupdf.open(stream=data, filetype="pdf")
    for span in doc.spans:
        page = pdf[span.page - 1]
        blocks = [b[4].rstrip("\n") for b in page.get_text("blocks", sort=True) if b[6] == 0]
        canonical = "\n".join(blocks)
        assert canonical[span.char_start : span.char_end] == span.exact_quote
        assert span.page == 1  # never invents pages
    texts = [s.normalized_text for s in doc.spans]
    assert any("not included in the price" in t for t in texts)
    excl = next(s for s in doc.spans if "online payments" in s.normalized_text)
    assert excl.heading and excl.heading.startswith("3. Exclusions")


def test_docx_spans_reference_paragraphs_and_table_cells() -> None:
    import docx

    data = (FIXTURES / "scope_contract_ru.docx").read_bytes()
    doc = parse_document(data, sniff_mime(data, "x.docx"))
    assert doc.mime == DOCX_MIME and doc.page_count is None and doc.status == "PARSED"
    paragraphs = docx.Document(str(FIXTURES / "scope_contract_ru.docx")).paragraphs
    for s in doc.spans:
        assert s.page is None  # DOCX never reports a page number
        if s.anchor_type == "DOCX_PARAGRAPH":
            assert paragraphs[s.paragraph_index].text[s.char_start : s.char_end] == s.exact_quote
    cells = {s.table_ref: s.exact_quote for s in doc.spans if s.anchor_type == "DOCX_TABLE_CELL"}
    assert cells == {"t0:r0:c0": "Этап", "t0:r0:c1": "Срок", "t0:r1:c0": "Дизайн макетов", "t0:r1:c1": "10 рабочих дней"}


def test_scanned_pdf_needs_review_instead_of_fake_text() -> None:
    data = (FIXTURES / "scanned_no_text.pdf").read_bytes()
    doc = parse_document(data, PDF_MIME)
    assert doc.status == "NEEDS_OCR_OR_REVIEW"
    assert doc.spans == []
    assert "LOW_TEXT" in doc.quality["issues"]


@pytest.mark.parametrize("payload", [b"hello world", b"PK\x03\x04garbage", b"\x89PNG\r\n"])
def test_unsupported_files_rejected_by_magic_bytes(payload: bytes) -> None:
    with pytest.raises(ParseError) as exc:
        sniff_mime(payload, "contract.pdf")  # extension is irrelevant
    assert exc.value.code == "UNSUPPORTED_FILE_TYPE"


# ------------------------------------------------------------------------------------- splitting


def test_split_keeps_exact_substrings_and_order() -> None:
    msg = "Add card payments and a personal account. Also the contact form is broken."
    items, notes = locate_requirements(
        msg,
        [
            {"exact_text": "Add card payments", "summary": "Add payments"},
            {"exact_text": "a personal account", "summary": "Add account"},
            {"exact_text": "the contact form is broken", "summary": "Fix form"},
        ],
    )
    assert [i.exact_text for i in items] == ["Add card payments", "a personal account", "the contact form is broken"]
    for i in items:
        assert msg[i.start : i.end] == i.exact_text
    assert notes == []


def test_split_drops_paraphrases_and_falls_back_to_whole_message() -> None:
    msg = "Please make everything better"
    items, notes = locate_requirements(msg, [{"exact_text": "Improve the site overall", "summary": ""}])
    assert len(items) == 1 and items[0].exact_text == msg
    assert "SPLIT_TEXT_NOT_IN_MESSAGE" in notes and "SPLIT_FALLBACK_WHOLE_MESSAGE" in notes


def test_query_terms_are_sanitized_prefixes() -> None:
    terms = query_terms("Добавьте оплату картой; DROP TABLE users;--")
    assert all(t.isalnum() for t in terms)
    assert "опла" in terms  # prefix matches оплата/оплату/оплатой


# ------------------------------------------------------------------------------------- gates


class _Span:
    def __init__(self, text: str) -> None:
        self.id = uuid.uuid4()
        self.normalized_text = text
        self.anchor_type = "PDF_PAGE"
        self.page = 1
        self.paragraph_index = None
        self.table_ref = None


class _Doc:
    title = "Contract"
    version = 1


def cand(ref: str, text: str, kind: str | None) -> Candidate:
    items = [(uuid.uuid4(), text[:20], kind)] if kind else []
    return Candidate(ref=ref, span=_Span(text), doc=_Doc(), scope_items=items, retrieved=kind is None)  # type: ignore[arg-type]


CANDS = {
    "E1": cand("E1", "Online payments by card are not included in the price.", "EXCLUDED"),
    "E2": cand("E2", "Feedback form on the Contacts page that sends messages.", "INCLUDED"),
    "E3": cand("E3", "For 60 days after acceptance the Contractor fixes defects free of charge.", "CONDITION"),
}


def raw(category: str, sup: list[tuple[str, str]] | None = None, counter: list[tuple[str, str]] | None = None,
        conf: float = 0.8) -> dict:
    return {
        "category": category, "summary": "s", "reason": "r",
        "supporting_evidence": [{"ref": r, "quote": q} for r, q in (sup or [])],
        "counter_evidence": [{"ref": r, "quote": q} for r, q in (counter or [])],
        "uncertainties": [], "clarifying_questions": [], "model_confidence": conf,
    }


def test_explicit_exclusion_gives_change_candidate_with_valid_citation() -> None:
    g = gate(raw("CHANGE_CANDIDATE", [("E1", "Online payments by card are not included")]), CANDS)
    assert g.category == "CHANGE_CANDIDATE"
    assert g.needs_review  # never final without a human
    assert g.supporting[0].quote == "Online payments by card are not included"
    assert g.validation_errors == []


def test_silence_is_never_a_paid_change() -> None:
    g = gate(raw("CHANGE_CANDIDATE", []), CANDS)
    assert g.category == "AMBIGUOUS"
    assert "POLICY_SILENCE_IS_NOT_CHANGE" in g.policy_notes


def test_in_scope_requires_supporting_included_evidence() -> None:
    assert gate(raw("IN_SCOPE", []), CANDS).category == "INSUFFICIENT_EVIDENCE"
    g = gate(raw("IN_SCOPE", [("E1", "Online payments")]), CANDS)  # citing an exclusion as proof of inclusion
    assert g.category == "AMBIGUOUS"


def test_bug_fix_with_warranty_is_clean_and_without_is_reviewed() -> None:
    ok = gate(raw("BUG_FIX", [("E2", "Feedback form"), ("E3", "60 days")]), CANDS)
    assert ok.category == "BUG_FIX" and not ok.needs_review
    unknown = gate(raw("BUG_FIX", [("E2", "Feedback form")]), CANDS)
    assert unknown.category == "BUG_FIX" and unknown.needs_review
    assert "POLICY_WARRANTY_UNVERIFIED" in unknown.policy_notes


def test_fabricated_reference_rejects_output() -> None:
    data = raw("CHANGE_CANDIDATE", [("E99", "invented clause")])
    bad = check_refs(data, CANDS)
    assert bad == ["E99"]
    g = gate(data, CANDS, fabricated=bad)
    assert g.category == "INSUFFICIENT_EVIDENCE"
    assert g.supporting == [] and g.needs_review
    assert any(e.startswith("UNKNOWN_EVIDENCE_REF") for e in g.validation_errors)


def test_paraphrased_quote_is_replaced_by_source_text() -> None:
    g = gate(raw("CHANGE_CANDIDATE", [("E1", "the contract excludes online payments")]), CANDS)
    assert g.supporting[0].quote == CANDS["E1"].span.normalized_text
    assert "QUOTE_NOT_IN_SOURCE:E1" in g.validation_errors


def test_conflicting_evidence_goes_to_review() -> None:
    g = gate(raw("IN_SCOPE", [("E2", "Feedback form")], [("E1", "Online payments")]), CANDS)
    assert g.needs_review and "POLICY_CONFLICTING_EVIDENCE" in g.policy_notes


def test_invalid_category_fails_closed() -> None:
    g = gate({**raw("IN_SCOPE"), "category": "PAY_NOW"}, CANDS)
    assert g.category == "INSUFFICIENT_EVIDENCE" and g.needs_review


# ------------------------------------------------------------------------------------- money


def test_decimal_line_amounts_and_rounding() -> None:
    assert line_amount("HOURLY", hours=Decimal("12.5"), rate=Decimal("10000"), fixed=None) == Decimal("125000.00")
    assert line_amount("HOURLY", hours=Decimal("0.33"), rate=Decimal("33.33"), fixed=None) == Decimal("11.00")
    assert line_amount("FIXED", hours=None, rate=None, fixed=Decimal("99.995")) == Decimal("100.00")
    assert total([Decimal("0.10")] * 3) == Decimal("0.30")  # no float drift


@pytest.mark.parametrize(
    ("kind", "kw", "code"),
    [
        ("HOURLY", {"hours": Decimal("-1"), "rate": Decimal("1"), "fixed": None}, "NEGATIVE_AMOUNT"),
        ("HOURLY", {"hours": None, "rate": Decimal("1"), "fixed": None}, "ESTIMATE_INCOMPLETE"),
        ("HOURLY", {"hours": Decimal("1.234"), "rate": Decimal("1"), "fixed": None}, "INVALID_AMOUNT"),
        ("FIXED", {"hours": None, "rate": None, "fixed": Decimal("-5")}, "NEGATIVE_AMOUNT"),
        ("HOURLY", {"hours": Decimal("99999"), "rate": Decimal("1"), "fixed": None}, "AMOUNT_TOO_LARGE"),
    ],
)
def test_invalid_money_inputs_rejected(kind: str, kw: dict, code: str) -> None:
    with pytest.raises(Unprocessable) as exc:
        line_amount(kind, **kw)
    assert exc.value.code == code


def test_to_decimal_rejects_nan() -> None:
    with pytest.raises(Unprocessable):
        to_decimal("NaN", "x")


# ------------------------------------------------------------------------------------- LLM adapter


def _provider(handler, **kw) -> OpenAICompatibleProvider:  # type: ignore[no-untyped-def]
    return OpenAICompatibleProvider(
        name="gemini", base_url="https://llm.test/v1", api_key="k", model="m1", max_retries=2,
        transport=httpx.MockTransport(handler), **kw,
    )


def _ok(data: dict) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(data)}}],
                                     "usage": {"total_tokens": 42, "prompt_tokens": 30, "completion_tokens": 12}})


async def test_adapter_sends_strict_schema_and_parses_json() -> None:
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen.update(json.loads(req.content))
        assert req.headers["authorization"] == "Bearer k"
        return _ok({"category": "IN_SCOPE"})

    res = await _provider(handler).generate_json(task="t", system="s", user="u", schema={"type": "object"})
    assert res.data == {"category": "IN_SCOPE"} and res.usage["total_tokens"] == 42
    assert seen["response_format"]["json_schema"]["strict"] is True


async def test_adapter_retries_overload_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(OpenAICompatibleProvider, "_backoff", staticmethod(lambda a: 0))
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503, json=[{"error": {"message": "high demand"}}]) if calls["n"] < 2 else _ok({"a": 1})

    res = await _provider(handler).generate_json(task="t", system="s", user="u", schema={})
    assert res.data == {"a": 1} and calls["n"] == 2


async def test_adapter_falls_back_to_next_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(OpenAICompatibleProvider, "_backoff", staticmethod(lambda a: 0))

    def handler(req: httpx.Request) -> httpx.Response:
        model = json.loads(req.content)["model"]
        return httpx.Response(404, json={"error": {"message": "gone"}}) if model == "m1" else _ok({"m": model})

    res = await _provider(handler, fallback_models=["m2"]).generate_json(task="t", system="s", user="u", schema={})
    assert res.model == "m2"


async def test_adapter_auth_failure_is_not_configured() -> None:
    p = _provider(lambda r: httpx.Response(401, json={"error": {"message": "bad key"}}))
    with pytest.raises(LLMNotConfigured) as exc:
        await p.generate_json(task="t", system="s", user="u", schema={})
    assert exc.value.code == "AI_PROVIDER_AUTH_FAILED" and not exc.value.retryable


async def test_adapter_unavailable_after_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(OpenAICompatibleProvider, "_backoff", staticmethod(lambda a: 0))
    p = _provider(lambda r: httpx.Response(429, json={"error": {"message": "quota"}}))
    with pytest.raises(LLMUnavailable):
        await p.generate_json(task="t", system="s", user="u", schema={})


async def test_adapter_non_json_output() -> None:
    p = _provider(lambda r: httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}]}))
    with pytest.raises(LLMInvalidOutput):
        await p.generate_json(task="t", system="s", user="u", schema={})


def test_missing_key_is_reported_not_faked() -> None:
    with pytest.raises(LLMNotConfigured):
        OpenAICompatibleProvider(name="gemini", base_url="x", api_key="", model="m")


# ------------------------------------------------------------------------------------- config guards


def test_fake_provider_forbidden_outside_tests() -> None:
    with pytest.raises(ValueError, match="only allowed when APP_ENV=test"):
        Settings(app_env="development", ai_provider="fake")


def test_external_send_cannot_be_enabled_in_p0() -> None:
    with pytest.raises(ValueError, match="ALLOW_EXTERNAL_SEND"):
        Settings(app_env="test", allow_external_send=True)


def test_production_requires_jwt_secret() -> None:
    with pytest.raises(ValueError, match="JWT_SECRET"):
        Settings(app_env="production", ai_provider="gemini", jwt_secret="")
