"""Deterministic rule-based provider for AUTOMATED TESTS ONLY.

It refuses to be constructed unless APP_ENV=test (also enforced in Settings). It never runs in
development, staging or production, so the product can never show a fake AI answer as real.
"""

from __future__ import annotations

import re
from typing import Any

from app.core.config import get_settings
from app.llm.base import LLMNotConfigured, LLMResult

_EXCLUDE = ("not included", "excluded", "out of scope", "does not include", "не входит", "не входят", "исключ")
_CONDITION = ("warranty", "acceptance", "bug", "defect", "change request", "гарант", "приёмк", "приемк", "ошиб")
_BUG = (
    "broken",
    "not working",
    "doesn't work",
    "does not work",
    "fix",
    "error",
    "bug",
    "не работает",
    "не отправляет",
    "исправ",
    "ошибк",
    "слома",
)
_VAGUE = ("modern", "nicer", "better", "prettier", "fresh", "современ", "красив", "лучше", "посовременнее")
_STOP = {
    "the",
    "and",
    "add",
    "please",
    "also",
    "our",
    "for",
    "with",
    "that",
    "this",
    "make",
    "добавьте",
    "сделайте",
    "ещё",
    "еще",
    "также",
    "пожалуйста",
    "нужно",
}


def _tokens(text: str) -> set[str]:
    words = re.findall(r"[\w-]+", text.lower())
    return {w[:5] for w in words if len(w) >= 4 and w not in _STOP}


class FakeLLMProvider:
    name = "fake"

    def __init__(self) -> None:
        if get_settings().app_env != "test":
            raise LLMNotConfigured("The fake AI provider is only available in the automated test environment")
        self.model = "fake-test-model"
        self.calls: list[str] = []

    async def generate_json(
        self,
        *,
        task: str,
        system: str,
        user: str,
        schema: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> LLMResult:
        self.calls.append(task)
        ctx = context or {}
        if task == "extract_scope":
            data = self._extract(ctx["spans"])
        elif task == "split_requirements":
            data = self._split(ctx["message"])
        elif task == "classify_requirement":
            data = self._classify(ctx["requirement"], ctx["evidence"])
        else:  # pragma: no cover
            raise ValueError(task)
        return LLMResult(data=data, provider=self.name, model=self.model, usage={"total_tokens": 10})

    # ----------------------------------------------------------------------------------------
    @staticmethod
    def _extract(spans: list[dict[str, Any]]) -> dict[str, Any]:
        items = []
        section = ""
        for s in spans:
            text = s["text"].strip()
            low = text.lower()
            if s.get("heading"):
                section = s["heading"].lower()
            if len(text) < 12 or text.endswith(":"):
                continue
            if any(k in low for k in _EXCLUDE) or "exclu" in section or "не входит" in section:
                kind = "EXCLUDED"
            elif any(k in low for k in _CONDITION):
                kind = "CONDITION"
            elif low.startswith(("-", "•", "–")) or "includ" in section or "входит" in section:
                kind = "INCLUDED"
            else:
                continue
            title = re.sub(r"^[-•–\s\d.]+", "", text)[:70]
            items.append(
                {
                    "title": title,
                    "description": text[:240],
                    "inclusion_type": kind,
                    "acceptance_criteria": "",
                    "source_refs": [s["ref"]],
                }
            )
        return {"items": items}

    @staticmethod
    def _split(message: str) -> dict[str, Any]:
        parts = [p for p in re.split(r"(?<=[.!?])\s+|\n+", message) if p.strip()]
        reqs = []
        for p in parts:
            p = p.strip()
            if len(p) < 6 or (
                len(p) < 20 and re.match(r"(?i)^(hi|hello|hey|thanks|thank you|привет|здравствуйте|спасибо)\b", p)
            ):
                continue
            # Split "X and Y" requests that share a verb.
            sub = re.split(r"\s+(?:and|и)\s+(?=[a-zа-яё])", p, maxsplit=1)
            for chunk in sub:
                chunk = chunk.strip().rstrip(".!")
                if len(chunk) >= 4:
                    reqs.append({"exact_text": chunk, "summary": chunk})
        return {"requirements": reqs}

    @staticmethod
    def _classify(requirement: str, evidence: list[dict[str, Any]]) -> dict[str, Any]:
        low = requirement.lower()
        req_tokens = _tokens(requirement)

        def overlap(e: dict[str, Any]) -> int:
            return len(req_tokens & _tokens(e["text"] + " " + (e.get("scope_item_title") or "")))

        ranked = sorted(evidence, key=overlap, reverse=True)
        best = [e for e in ranked if overlap(e) > 0]
        excluded = [e for e in best if e.get("inclusion_type") == "EXCLUDED"]
        included = [e for e in best if e.get("inclusion_type") == "INCLUDED"]
        conditions = [e for e in evidence if e.get("inclusion_type") == "CONDITION"]

        def cite(es: list[dict[str, Any]]) -> list[dict[str, str]]:
            return [{"ref": e["ref"], "quote": e["text"][:80]} for e in es[:2]]

        base = {"uncertainties": [], "clarifying_questions": [], "counter_evidence": []}
        if any(k in low for k in _VAGUE) and not excluded:
            return {
                **base,
                "category": "AMBIGUOUS",
                "summary": requirement,
                "reason": "Subjective request without measurable acceptance criteria.",
                "supporting_evidence": [],
                "clarifying_questions": ["Which specific screens and what measurable outcome are expected?"],
                "model_confidence": 0.6,
            }
        if any(k in low for k in _BUG) and included:
            warranty = [
                c
                for c in conditions
                if any(
                    k in (c["text"] + " " + (c.get("scope_item_title") or "")).lower()
                    for k in ("warrant", "defect", "гарант", "ошиб")
                )
            ]
            return {
                **base,
                "category": "BUG_FIX",
                "summary": requirement,
                "reason": "Defect in an included feature covered by the warranty clause.",
                "supporting_evidence": cite(included[:1] + warranty[:1]),
                "model_confidence": 0.8,
            }
        if excluded:
            return {
                **base,
                "category": "CHANGE_CANDIDATE",
                "summary": requirement,
                "reason": "The approved scope explicitly excludes this work.",
                "supporting_evidence": cite(excluded),
                "uncertainties": ["Check for a newer agreed amendment."],
                "model_confidence": 0.85,
            }
        if included:
            return {
                **base,
                "category": "IN_SCOPE",
                "summary": requirement,
                "reason": "Covered by an included scope item.",
                "supporting_evidence": cite(included),
                "model_confidence": 0.75,
            }
        return {
            **base,
            "category": "AMBIGUOUS",
            "summary": requirement,
            "reason": "The approved scope does not address this request.",
            "supporting_evidence": [],
            "clarifying_questions": ["Please describe the expected result in more detail."],
            "model_confidence": 0.4,
        }
