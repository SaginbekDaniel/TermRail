"""Render a change-order revision to PDF. Every number comes from the stored revision content;
the footer carries the revision number and content hash so the document can be verified."""

from __future__ import annotations

import io
from decimal import Decimal
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

FONT_DIR = Path(__file__).parent / "fonts"
_registered = False

LABELS: dict[str, dict[str, str]] = {
    "en": {
        "doc": "Change order",
        "draft": "DRAFT — NOT APPROVED. Not for sending.",
        "approved": "Internally approved revision",
        "project": "Project",
        "client": "Client",
        "baseline": "Approved scope baseline",
        "request": "Client request received",
        "summary": "Summary",
        "items": "Requested changes",
        "requirement": "Requirement",
        "why": "Why this is a change",
        "evidence": "Contract evidence",
        "work": "Work",
        "role": "Role",
        "hours": "Hours",
        "rate": "Rate",
        "amount": "Amount",
        "fixed": "Fixed price",
        "subtotal": "Subtotal",
        "total": "Total additional cost",
        "timeline": "Timeline impact",
        "days": "days",
        "terms": "Terms",
        "acceptance": "Acceptance criteria",
        "exclusions": "Exclusions",
        "valid_until": "Valid until",
        "revision": "Revision",
        "hash": "Content hash",
        "approved_by": "Approved by",
        "disclaimer": "Prepared with TermRail. This proposal requires review by an authorised person and "
        "becomes binding only when accepted by both parties in accordance with the contract.",
        "version": "v",
        "page": "Page",
    },
    "ru": {
        "doc": "Дополнительное соглашение (проект)",
        "draft": "ЧЕРНОВИК — НЕ УТВЕРЖДЁН. Не для отправки.",
        "approved": "Внутренне утверждённая редакция",
        "project": "Проект",
        "client": "Заказчик",
        "baseline": "Утверждённый объём работ",
        "request": "Запрос заказчика получен",
        "summary": "Описание",
        "items": "Запрошенные изменения",
        "requirement": "Требование",
        "why": "Почему это изменение",
        "evidence": "Основание в договоре",
        "work": "Работы",
        "role": "Роль",
        "hours": "Часы",
        "rate": "Ставка",
        "amount": "Сумма",
        "fixed": "Фиксированная цена",
        "subtotal": "Итого по пункту",
        "total": "Итого дополнительная стоимость",
        "timeline": "Влияние на сроки",
        "days": "дн.",
        "terms": "Условия",
        "acceptance": "Критерии приёмки",
        "exclusions": "Исключения",
        "valid_until": "Действительно до",
        "revision": "Редакция",
        "hash": "Хеш содержимого",
        "approved_by": "Утвердил",
        "disclaimer": "Подготовлено в TermRail. Предложение требует проверки уполномоченным лицом и становится "
        "обязательным только после согласования обеими сторонами в порядке, предусмотренном договором.",
        "version": "в",
        "page": "Стр.",
    },
}


def _register_fonts() -> None:
    global _registered
    if not _registered:
        pdfmetrics.registerFont(TTFont("SL", str(FONT_DIR / "DejaVuSans.ttf")))
        pdfmetrics.registerFont(TTFont("SL-Bold", str(FONT_DIR / "DejaVuSans-Bold.ttf")))
        _registered = True


def format_money(value: str | Decimal, currency: str) -> str:
    d = Decimal(str(value))
    whole, _, frac = f"{d:.2f}".partition(".")
    sign = "-" if whole.startswith("-") else ""
    whole = whole.lstrip("-")
    groups: list[str] = []
    while whole:
        groups.insert(0, whole[-3:])
        whole = whole[:-3]
    return f"{sign}{' '.join(groups)}.{frac} {currency}"


def render_change_order_pdf(content: dict[str, Any], meta: dict[str, Any]) -> bytes:
    _register_fonts()
    lang = content.get("language", "en")
    L = LABELS.get(lang, LABELS["en"])
    currency = content["currency"]

    base = ParagraphStyle("base", fontName="SL", fontSize=9.5, leading=13, textColor=colors.HexColor("#1f2933"))
    small = ParagraphStyle("small", parent=base, fontSize=8, leading=10.5, textColor=colors.HexColor("#52606d"))
    h1 = ParagraphStyle("h1", parent=base, fontName="SL-Bold", fontSize=16, leading=20, spaceAfter=2)
    h2 = ParagraphStyle("h2", parent=base, fontName="SL-Bold", fontSize=11, leading=15, spaceBefore=10, spaceAfter=4)
    h3 = ParagraphStyle("h3", parent=base, fontName="SL-Bold", fontSize=10, leading=13, spaceBefore=6)
    quote = ParagraphStyle(
        "quote",
        parent=base,
        fontSize=8.5,
        leading=11.5,
        leftIndent=8,
        textColor=colors.HexColor("#323f4b"),
        borderPadding=(2, 4, 2, 4),  # type: ignore[arg-type]  # reportlab accepts a 4-tuple; stub says float
    )
    right = ParagraphStyle("right", parent=base, alignment=TA_RIGHT)
    banner = ParagraphStyle("banner", parent=base, fontName="SL-Bold", textColor=colors.white, fontSize=10)

    def p(text: Any, style: ParagraphStyle = base) -> Paragraph:
        return Paragraph(escape(str(text or "")).replace("\n", "<br/>"), style)

    story: list[Any] = []
    is_draft = bool(meta.get("draft"))
    banner_text = L["draft"] if is_draft else f"{L['approved']} · {L['revision']} {meta['revision_no']}"
    banner_tbl = Table([[p(banner_text, banner)]], colWidths=[170 * mm])
    banner_tbl.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#b42318" if is_draft else "#1f6f43")),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story += [banner_tbl, Spacer(1, 8)]
    story.append(p(f"{L['doc']} #{content['number']}: {content['title']}", h1))

    proj = content["project"]
    bl = content["baseline"]
    req = content["request"]
    info = [
        [p(L["project"], small), p(proj["title"])],
        [p(L["client"], small), p(proj["client_name"])],
        [p(L["baseline"], small), p(f"{L['version']}{bl['version']} · {str(bl.get('hash') or '')[:16]}…")],
        [p(L["request"], small), p(f"{req['received_at'][:10]} {req.get('sender') or ''}".strip())],
    ]
    t = Table(info, colWidths=[45 * mm, 125 * mm])
    t.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    story.append(t)

    if content.get("summary"):
        story += [p(L["summary"], h2), p(content["summary"])]

    story.append(p(L["items"], h2))
    for idx, item in enumerate(content["items"], start=1):
        block: list[Any] = [
            p(f"{idx}. {item['summary'] or item['requirement']}", h3),
            p(f"{L['requirement']}: «{item['requirement']}»", small),
        ]
        if item.get("reason"):
            block += [Spacer(1, 2), p(f"{L['why']}: {item['reason']}")]
        if item.get("evidence"):
            block.append(p(f"{L['evidence']}:", small))
            for ev in item["evidence"]:
                block.append(
                    p(
                        f"“{ev['quote']}” — {ev['document_title']} ({L['version']}{ev['document_version']}, "
                        f"{ev['anchor']})",
                        quote,
                    )
                )
        est = item["estimate"]
        rows: list[list[Paragraph | str]] = [
            [p(L["work"], small), p(L["role"], small), p(L["hours"], small), p(L["rate"], small), p(L["amount"], small)]
        ]
        for ln in est["lines"]:
            if ln["kind"] == "HOURLY":
                rows.append(
                    [
                        p(ln["description"] or "—"),
                        p(ln["role"]),
                        p(ln["hours"], right),
                        p(format_money(ln["rate"], currency), right),
                        p(format_money(ln["amount"], currency), right),
                    ]
                )
            else:
                rows.append(
                    [
                        p(ln["description"] or L["fixed"]),
                        p(L["fixed"]),
                        p("—", right),
                        p("—", right),
                        p(format_money(ln["amount"], currency), right),
                    ]
                )
        rows.append([p(L["subtotal"], h3), "", "", "", p(format_money(est["subtotal"], currency), right)])
        lt = Table(rows, colWidths=[62 * mm, 30 * mm, 18 * mm, 28 * mm, 32 * mm], repeatRows=1)
        lt.setStyle(
            TableStyle(
                [
                    ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.HexColor("#9aa5b1")),
                    ("LINEABOVE", (0, -1), (-1, -1), 0.5, colors.HexColor("#9aa5b1")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 2),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 2),
                ]
            )
        )
        block += [Spacer(1, 4), lt]
        story.append(KeepTogether(block))

    tot = Table(
        [
            [
                p(L["total"], h3),
                p(
                    format_money(content["total"], currency),
                    ParagraphStyle("tot", parent=right, fontName="SL-Bold", fontSize=12, leading=15),
                ),
            ]
        ],
        colWidths=[120 * mm, 50 * mm],
    )
    tot.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f0f4f8")),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story += [Spacer(1, 10), tot]
    if content.get("timeline_days") is not None:
        story.append(p(f"{L['timeline']}: +{content['timeline_days']} {L['days']}"))

    for key, label in (("acceptance_criteria", "acceptance"), ("terms", "terms"), ("exclusions", "exclusions")):
        if content.get(key):
            story += [p(L[label], h2), p(content[key])]
    if content.get("valid_until"):
        story += [Spacer(1, 6), p(f"{L['valid_until']}: {content['valid_until']}")]

    story += [Spacer(1, 14), p(L["disclaimer"], small)]
    if not is_draft and meta.get("approved_by"):
        story.append(p(f"{L['approved_by']}: {meta['approved_by']} · {str(meta.get('approved_at') or '')[:19]}", small))

    footer = f"{L['revision']} {meta['revision_no']} · {L['hash']} {meta['content_hash']}"

    def on_page(canvas: Any, doc: Any) -> None:
        canvas.saveState()
        canvas.setFont("SL", 7)
        canvas.setFillColor(colors.HexColor("#7b8794"))
        canvas.drawString(20 * mm, 10 * mm, footer)
        canvas.drawRightString(190 * mm, 10 * mm, f"{L['page']} {doc.page}")
        if is_draft:
            canvas.setFont("SL-Bold", 60)
            canvas.setFillColor(colors.Color(0.8, 0.1, 0.1, alpha=0.08))
            canvas.translate(105 * mm, 150 * mm)
            canvas.rotate(35)
            canvas.drawCentredString(0, 0, "DRAFT" if lang == "en" else "ЧЕРНОВИК")
        canvas.restoreState()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=16 * mm,
        bottomMargin=18 * mm,
        title=f"{L['doc']} #{content['number']}",
        author="TermRail",
        subject=meta["content_hash"],
    )
    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    return buf.getvalue()
