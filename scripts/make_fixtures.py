"""Generate CLEARLY SYNTHETIC demo/test contracts (PDF in English, DOCX in Russian).

Usage (from repo root):  uv run --project apps/api python scripts/make_fixtures.py
"""

from __future__ import annotations

from pathlib import Path

import docx
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "fixtures"
FONTS = ROOT / "apps" / "api" / "app" / "pdf" / "fonts"

EN_CONTRACT: list[tuple[str, str]] = [
    ("title", "SYNTHETIC DEMO CONTRACT — Website Development Agreement No. WD-2026-014"),
    (
        "p",
        "This is a fictional contract created for ScopeLock demonstrations and tests. It does not describe a real "
        "agreement between real parties.",
    ),
    ("p", "Parties: Northwind Studio LLP (the Contractor) and Aster Logistics LLP (the Client)."),
    ("h", "1. Subject and price"),
    (
        "p",
        "The Contractor designs and develops a corporate website for the Client for a fixed price of "
        "1,000,000 KZT. The price covers only the work listed in Section 2.",
    ),
    ("h", "2. Scope of work (included)"),
    ("b", "- Home page with company overview and key services."),
    ("b", "- About page describing the company history and team."),
    ("b", "- Contacts page with address, phone number and an embedded map."),
    ("b", "- Feedback form on the Contacts page that sends submitted messages to the Client's email address."),
    ("b", "- Responsive layout for desktop and mobile browsers."),
    ("b", "- Two rounds of design revisions for the agreed page layouts."),
    ("h", "3. Exclusions (not included in the price)"),
    (
        "p",
        "The following work is not included in the price and requires a separate change order: online "
        "payments by card, a personal account (user registration and login area), integration with CRM "
        "systems, and content copywriting.",
    ),
    ("h", "4. Acceptance"),
    (
        "p",
        "The Client reviews the delivered website within 5 business days. Acceptance is confirmed by a signed "
        "acceptance certificate.",
    ),
    ("h", "5. Warranty"),
    (
        "p",
        "For 60 days after acceptance the Contractor fixes, free of charge, defects where delivered "
        "functionality does not work as described in Section 2.",
    ),
    ("h", "6. Changes"),
    (
        "p",
        "Any additional work outside Section 2 is performed only on the basis of a written change order "
        "agreed by both parties, specifying the scope, price and timeline.",
    ),
]

RU_CONTRACT: list[tuple[str, str]] = [
    ("title", "СИНТЕТИЧЕСКИЙ ДЕМО-ДОГОВОР — Договор на разработку сайта № WD-2026-015"),
    ("p", "Это вымышленный договор для демонстраций и тестов ScopeLock. Он не описывает реальное соглашение."),
    ("h", "1. Предмет и стоимость"),
    ("p", "Исполнитель разрабатывает корпоративный сайт Заказчика по фиксированной цене 1 000 000 тенге."),
    ("h", "2. Объём работ (входит в стоимость)"),
    ("b", "- Страница «Главная» с описанием компании."),
    ("b", "- Страница «О компании»."),
    ("b", "- Страница «Контакты» с адресом и картой."),
    ("b", "- Форма обратной связи, отправляющая сообщения на e-mail Заказчика."),
    ("h", "3. Не входит в стоимость"),
    ("p", "В стоимость не входят: онлайн-оплата картой, личный кабинет пользователя, интеграция с CRM."),
    ("h", "4. Гарантия"),
    (
        "p",
        "В течение 60 дней после приёмки Исполнитель бесплатно исправляет ошибки в функциональности, "
        "описанной в разделе 2.",
    ),
    ("h", "5. Изменения"),
    ("p", "Дополнительные работы выполняются только по письменному дополнительному соглашению."),
]

CLIENT_MESSAGE_EN = (
    "Hi team! Please add card payments and a personal account for our customers. "
    "Also, the feedback form on the Contacts page does not send messages, please fix it. "
    "And make the design more modern. Thanks!"
)

CLIENT_MESSAGE_RU = (
    "Добавьте оплату картой и личный кабинет. Ещё форма контактов не отправляет сообщения, исправьте. "
    "И сделайте дизайн посовременнее."
)


def make_pdf(path: Path, content: list[tuple[str, str]]) -> None:
    pdfmetrics.registerFont(TTFont("DejaVu", str(FONTS / "DejaVuSans.ttf")))
    pdfmetrics.registerFont(TTFont("DejaVu-Bold", str(FONTS / "DejaVuSans-Bold.ttf")))
    styles = {
        "title": ParagraphStyle("t", fontName="DejaVu-Bold", fontSize=13, leading=17, spaceAfter=8),
        "h": ParagraphStyle("h", fontName="DejaVu-Bold", fontSize=11, leading=15, spaceBefore=10, spaceAfter=4),
        "p": ParagraphStyle("p", fontName="DejaVu", fontSize=10, leading=14, spaceAfter=4),
        "b": ParagraphStyle("b", fontName="DejaVu", fontSize=10, leading=14, leftIndent=8),
    }
    doc = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        title="Synthetic demo contract",
        author="ScopeLock fixtures",
    )
    story = []
    for kind, text in content:
        story.append(Paragraph(text, styles[kind]))
        if kind == "title":
            story.append(Spacer(1, 4))
    doc.build(story)


def make_docx(path: Path, content: list[tuple[str, str]]) -> None:
    d = docx.Document()
    for kind, text in content:
        if kind == "title":
            d.add_heading(text, level=1)
        elif kind == "h":
            d.add_heading(text, level=2)
        else:
            d.add_paragraph(text)
    table = d.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Этап"
    table.cell(0, 1).text = "Срок"
    table.cell(1, 0).text = "Дизайн макетов"
    table.cell(1, 1).text = "10 рабочих дней"
    d.save(str(path))


def main() -> None:
    FIX.mkdir(exist_ok=True)
    make_pdf(FIX / "scope_contract.pdf", EN_CONTRACT)
    make_docx(FIX / "scope_contract_ru.docx", RU_CONTRACT)
    (FIX / "client_change_message.txt").write_text(CLIENT_MESSAGE_EN + "\n", encoding="utf-8")
    (FIX / "client_change_message_ru.txt").write_text(CLIENT_MESSAGE_RU + "\n", encoding="utf-8")
    # A "scanned" PDF with no text layer, to test the NEEDS_OCR_OR_REVIEW path.
    import pymupdf

    scan = pymupdf.open()
    page = scan.new_page()
    page.draw_rect(pymupdf.Rect(50, 50, 500, 700), color=(0.2, 0.2, 0.2), fill=(0.9, 0.9, 0.9))
    scan.save(str(FIX / "scanned_no_text.pdf"))
    print("fixtures written to", FIX)


if __name__ == "__main__":
    main()
