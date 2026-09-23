import io
from html import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from . import speaker_names, summary_of, task_rows, timecode

FONT_DIR = "/usr/share/fonts/truetype/dejavu"
pdfmetrics.registerFont(TTFont("DejaVu", f"{FONT_DIR}/DejaVuSans.ttf"))
pdfmetrics.registerFont(TTFont("DejaVu-Bold", f"{FONT_DIR}/DejaVuSans-Bold.ttf"))
pdfmetrics.registerFontFamily("DejaVu", normal="DejaVu", bold="DejaVu-Bold")

BODY = ParagraphStyle("body", fontName="DejaVu", fontSize=10, leading=13)
CELL = ParagraphStyle("cell", parent=BODY, fontSize=9, leading=11)
H0 = ParagraphStyle("h0", parent=BODY, fontName="DejaVu-Bold", fontSize=16, leading=20, spaceAfter=6)
H1 = ParagraphStyle("h1", parent=BODY, fontName="DejaVu-Bold", fontSize=12, leading=16, spaceBefore=10, spaceAfter=4)


def _p(text: str, style=BODY) -> Paragraph:
    return Paragraph(escape(text or ""), style)


def build(meeting: dict) -> bytes:
    story = [_p("Протокол совещания", H0),
             _p(f"Тема: {meeting['title']}"), _p(f"Дата: {meeting['meeting_date']}")]

    story.append(_p("Участники", H1))
    for s in meeting["speakers"]:
        story.append(_p(f"• {s['name'] or s['label']}" + (f" — {s['role']}" if s["role"] else "")))

    summary = summary_of(meeting)
    story.append(_p("Краткое содержание", H1))
    if summary.get("overview"):
        story.append(_p(summary["overview"]))
    for topic in summary.get("topics", []):
        story += [Spacer(0, 4), Paragraph(f"<b>{escape(topic['title'])}</b>", BODY)]
        story += [_p(f"• {point}") for point in topic.get("points", [])]
    if summary.get("decisions"):
        story += [Spacer(0, 4), Paragraph("<b>Решения</b>", BODY)]
        story += [_p(f"• {d}") for d in summary["decisions"]]

    story.append(_p("Поручения", H1))
    data = [[Paragraph(f"<b>{h}</b>", CELL) for h in ["№", "Поручение", "Ответственный", "Срок"]]]
    data += [[_p(v, CELL) for v in row] for row in task_rows(meeting)]
    table = Table(data, colWidths=[10 * mm, 90 * mm, 40 * mm, 40 * mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeee")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(table)

    story.append(_p("Стенограмма", H1))
    names = speaker_names(meeting)
    for seg in meeting["segments"]:
        who = escape(names.get(seg["speaker"], seg["speaker"]))
        story.append(Paragraph(f"<b>[{timecode(seg['start'])}] {who}:</b> {escape(seg['text'])}", BODY))

    buffer = io.BytesIO()
    SimpleDocTemplate(buffer, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm,
                      topMargin=15 * mm, bottomMargin=15 * mm, title=meeting["title"]).build(story)
    return buffer.getvalue()
