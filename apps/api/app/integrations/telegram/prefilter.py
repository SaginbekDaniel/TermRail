"""Cheap deterministic triage of client chat messages before any AI call.

Labels:
- NOISE: greetings, thanks, acknowledgements, emoji -> dropped, no AI call.
- STATUS: a progress/status question with no request in it -> dropped, no commercial signal.
- TIMELINE: talks about moving/shortening a deadline -> non-monetary TIMELINE_CHANGE_CANDIDATE signal.
- PAYMENT: mentions agreeing to/paying an amount -> PAYMENT_COMMITMENT_MENTION context signal
  (never "payment received", never legal acceptance).
- CANDIDATE: anything that may ask for work -> goes to the evidence-gated analysis.

Rule of thumb: when unsure, a message is a CANDIDATE. Losing a real request is worse than one extra
analysis; the analysis itself is conservative (silence in the contract is never a paid change).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_SMALLTALK = [
    r"привет\w*",
    r"здравствуй\w*",
    r"добр\w+ (?:день|утро|вечер|ночи)",
    r"доброе утро",
    r"как (?:дела|ты|вы|жизнь|поживаете)",
    r"спасибо\w*",
    r"благодар\w*",
    r"пожалуйста",
    r"ок(?:ей)?",
    r"хорошо",
    r"отлично",
    r"супер",
    r"понятно",
    r"понял\w*",
    r"ага",
    r"угу",
    r"да",
    r"нет",
    r"до связи",
    r"всего доброго",
    r"hi",
    r"hello",
    r"hey",
    r"good (?:morning|afternoon|evening)",
    r"how are you(?: doing)?",
    r"thanks?(?: you)?(?: so much| a lot)?",
    r"ok(?:ay)?",
    r"great",
    r"cool",
    r"got it",
    r"sure",
    r"yes",
    r"no",
    r"bye",
    r"cheers",
]
_SMALLTALK_RE = re.compile(r"\b(?:" + "|".join(_SMALLTALK) + r")\b", re.IGNORECASE)

_REQUEST = re.compile(
    r"(?:добав|сдела|нужн|надо|хоч|хотел|можно ли|можете|сможете|измени|поменя|исправ|переделай|переделать|"
    r"убер|убра|реализ|подключ|интегр|давай|давайте|замени|обнов|настро|разработ|"
    r"\badd\b|\bmake\b|\bchange\b|\bneed\b|\bwant\b|could you|can you|would you|\bplease\b|\bfix\b|\bremove\b|"
    r"implement|integrat|\bbuild\b|\bcreate\b|\bupdate\b|\breplace\b|\bredo\b|\bswitch\b|\bset up\b)",
    re.IGNORECASE,
)
_STATUS = re.compile(
    r"(?:когда (?:будет|будут|сможете|закончите|сдадите|готов)|как продвигается|как успехи|какой статус|"
    r"на каком этапе|есть новости|\bwhen will\b|\bwhen is\b|\bstatus\b|how is it going|any (?:update|news)|"
    r"how far along|\beta\b)",
    re.IGNORECASE,
)
_TIMELINE = re.compile(
    r"(?:\bсрок|дедлайн|дата запуска|дату запуска|сократ\w* срок|перенес\w*|перенос\w*|ускор\w*|раньше на|"
    r"позже на|\bdeadline|\btimeline|launch date|due date|postpone|reschedule|\bsooner\b|\bearlier\b|"
    r"push (?:it|the date) back|move (?:the )?(?:date|deadline|launch))",
    re.IGNORECASE,
)
_AMOUNT = re.compile(
    r"\d[\d\s.,]*\s*(?:₸|тг\b|тенге|kzt|руб\w*|₽|\$|usd|eur|€|тыс\w*|k\b|млн)|(?:\$|€|₸)\s*\d", re.IGNORECASE
)
_PAYMENT_WORDS = re.compile(
    r"(?:согласен|согласна|согласны|соглас\w+ на|оплат\w*|заплат\w*|переведу|перевела|перевёл|перевел|"
    r"предоплат\w*|аванс|сч[её]т на|\bpay\b|\bpaid\b|\bpayment\b|\binvoice\b|agree(?:d)? to|deal at|"
    r"\bdeposit\b|\bprepay)",
    re.IGNORECASE,
)

# A payment *act* by a party ("I'll pay", "оплатил"), as opposed to a payment *feature* ("оплата картой").
_PAY_ACT = re.compile(
    r"(?:оплачу|оплатил\w*|оплатим|заплачу|заплатил\w*|заплатим|переведу|перевел\w*|перевёл|"
    r"\b(?:i|we)(?:'ll| will)? pay\b|\b(?:i|we) paid\b|send (?:me |us )?(?:the |an )?invoice)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Triage:
    labels: frozenset[str]

    @property
    def send_to_analysis(self) -> bool:
        return "CANDIDATE" in self.labels

    @property
    def primary(self) -> str:
        for name in ("CANDIDATE", "TIMELINE", "PAYMENT", "STATUS", "NOISE"):
            if name in self.labels:
                return name
        return "NOISE"


def _is_smalltalk(text: str) -> bool:
    rest = _SMALLTALK_RE.sub(" ", text)
    return not re.search(r"\w", rest)


def triage(text: str) -> Triage:
    t = " ".join(text.split())
    if len(re.findall(r"\w", t)) < 2 or _is_smalltalk(t):
        return Triage(frozenset({"NOISE"}))
    labels: set[str] = set()
    has_request = bool(_REQUEST.search(t))
    if _TIMELINE.search(t):
        labels.add("TIMELINE")
    if _PAYMENT_WORDS.search(t) and (_AMOUNT.search(t) or _PAY_ACT.search(t)):
        labels.add("PAYMENT")
    if has_request:
        labels.add("CANDIDATE")
    elif not labels:
        if _STATUS.search(t):
            labels.add("STATUS")
        else:
            labels.add("CANDIDATE")  # unsure -> escalate, never silently drop
    return Triage(frozenset(labels))
