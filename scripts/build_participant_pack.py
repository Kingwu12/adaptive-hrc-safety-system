"""Render the participant handout and operator script from one Markdown source.

Requires reportlab. Run from any directory; outputs are print-ready A4 PDFs.
"""
from pathlib import Path
import re
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, PageBreak

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs/participant-session-pack.md"
OUTPUT = ROOT / "output/pdf"
GREEN = colors.HexColor("#17634c")
INK = colors.HexColor("#182723")

STYLES = {
    "h1": ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=22,
                         leading=26, spaceAfter=10, textColor=INK),
    "h2": ParagraphStyle("heading", fontName="Helvetica-Bold", fontSize=11.5,
                         leading=14, spaceBefore=8, spaceAfter=4,
                         textColor=GREEN, keepWithNext=True),
    "body": ParagraphStyle("body", fontName="Helvetica", fontSize=10.3,
                           leading=13.1, spaceAfter=5, textColor=INK),
    "quote": ParagraphStyle("quote", fontName="Helvetica", fontSize=10.3,
                            leading=13.1, spaceAfter=5, leftIndent=10,
                            borderColor=GREEN, borderWidth=0,
                            textColor=INK),
    "list": ParagraphStyle("list", fontName="Helvetica", fontSize=10.3,
                           leading=12.8, spaceAfter=4, leftIndent=9,
                           firstLineIndent=-9, textColor=INK),
    "meta": ParagraphStyle("meta", fontName="Helvetica", fontSize=8.5,
                           leading=11, spaceAfter=7,
                           textColor=colors.HexColor("#55655d")),
}


def inline(text):
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escape(text))


def flow(source):
    story = []
    for section in source.strip().split("\n\n"):
        section = section.strip()
        if not section or section.startswith("<!--"):
            continue
        if section.startswith("# "):
            story.append(Paragraph(inline(section[2:]), STYLES["h1"]))
        elif section.startswith("## "):
            story.append(Paragraph(inline(section[3:]), STYLES["h2"]))
        elif section.startswith(">"):
            paragraphs = re.split(r"\n>\s*\n", section)
            for paragraph in paragraphs:
                clean = re.sub(r"(?m)^> ?", "", paragraph).replace("\n", " ")
                story.append(Paragraph(inline(clean), STYLES["quote"]))
        elif re.match(r"(?:\d+\. |\- )", section):
            for line in section.splitlines():
                story.append(Paragraph(inline(line), STYLES["list"]))
        else:
            style = "meta" if "|" in section and "v1.1" in section else "body"
            story.append(Paragraph(inline(section.replace("\n", " ")), STYLES[style]))
    return story


def render(path, pages, label):
    doc = SimpleDocTemplate(str(path), pagesize=A4, rightMargin=43,
                            leftMargin=43, topMargin=36, bottomMargin=39,
                            title=label, author="Monash FYP team")
    story = []
    for index, page in enumerate(pages):
        if index:
            story.append(PageBreak())
        story.extend(flow(page))

    def footer(canvas, _doc):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#d1dcd5"))
        canvas.line(43, 30, A4[0] - 43, 30)
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#55655d"))
        canvas.drawString(43, 18, label + " | 9 September 2026 | v1.1")
        canvas.drawRightString(A4[0] - 43, 18, str(_doc.page))
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    print(path)


if __name__ == "__main__":
    source = SOURCE.read_text(encoding="utf-8")
    participant, operator = source.split("<!-- operator -->")
    participant = participant.replace("<!-- participant -->", "")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    render(OUTPUT / "participant-handout.pdf", [participant], "Participant handout")
    render(OUTPUT / "operator-session-script.pdf", operator.split("<!-- page -->"),
           "Operator session script | Team only")
