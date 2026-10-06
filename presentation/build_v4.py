"""Build FYP-assessment-presentation-v4.pptx from v3 (Monash template).

v4 (6 Oct 2026) follows the rolled-back FYP B presentation rubric and the
paper v3.2 results (12 participants, same-input replay). Slide 1 is kept from
v3; every other slide is rebuilt here. Numbers come from
paper/tables/publication_numbers.tex, same_input.tex and controller_summary.tex.

    python3 presentation/build_v4.py
"""
from pathlib import Path

from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SRC = HERE / "FYP-assessment-presentation-v3.pptx"
OUT = HERE / "FYP-assessment-presentation-v4.pptx"

NAVY = RGBColor(0x17, 0x2D, 0x3D)
BLUE = RGBColor(0x00, 0x6D, 0xAE)
GREY = RGBColor(0x53, 0x6B, 0x79)
MIST = RGBColor(0xE5, 0xED, 0xF2)
SOFT = RGBColor(0x9F, 0xB3, 0xC0)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
FONT = "Arial"


# ---------------------------------------------------------------- helpers
def drop_slides_after_first(prs):
    lst = prs.slides._sldIdLst
    for sld in list(lst)[1:]:
        prs.part.drop_rel(sld.rId)
        lst.remove(sld)


def new_slide(prs, number, title):
    layout = next(l for l in prs.slide_layouts if l.name == "Full slide copy_grey")
    s = prs.slides.add_slide(layout)
    for ph in list(s.placeholders):
        ph._element.getparent().remove(ph._element)
    text(s, title, 0.48, 0.42, 12.3, 0.8, size=32, bold=True)
    text(s, f"{number:02d}", 0.51, 6.96, 0.6, 0.25, size=12, color=GREY)
    return s


def text(s, content, x, y, w, h, size=20, bold=False, color=NAVY,
         align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP, name=None):
    """content: str, or list of paragraphs; a paragraph is str or list of
    (text, {bold, color, size}) runs."""
    tb = s.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    if name:
        tb.name = name
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = Inches(0.05)
    paras = content if isinstance(content, list) else [content]
    for i, para in enumerate(paras):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        if i:
            p.space_before = Pt(size * 0.45)
        runs = para if isinstance(para, list) else [(para, {})]
        for rt, ro in runs:
            r = p.add_run()
            r.text = rt
            f = r.font
            f.name = FONT
            f.size = Pt(ro.get("size", size))
            f.bold = ro.get("bold", bold)
            f.color.rgb = ro.get("color", color)
    return tb


def box(s, x, y, w, h, fill=MIST, line=None, shape=MSO_SHAPE.ROUNDED_RECTANGLE):
    b = s.shapes.add_shape(shape, Inches(x), Inches(y), Inches(w), Inches(h))
    b.fill.solid()
    b.fill.fore_color.rgb = fill
    if line is None:
        b.line.fill.background()
    else:
        b.line.color.rgb = line
        b.line.width = Pt(1.5)
    b.shadow.inherit = False
    if shape == MSO_SHAPE.ROUNDED_RECTANGLE:
        b.adjustments[0] = 0.08
    return b


def arrow(s, x, y, w=0.45, h=0.4, color=SOFT):
    a = s.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW, Inches(x), Inches(y), Inches(w), Inches(h))
    a.fill.solid()
    a.fill.fore_color.rgb = color
    a.line.fill.background()
    a.shadow.inherit = False
    return a


def stat(s, big, label, x, y, w, color=BLUE, big_size=48, label_size=17):
    text(s, big, x, y, w, 0.95, size=big_size, bold=True, color=color)
    text(s, label, x, y + 0.92, w, 0.9, size=label_size, color=NAVY)


def bar_chart(s, x, y, w, h, cats, values, fmt, title, highlight_last=True,
              vmax=None, horizontal=False):
    cd = CategoryChartData()
    cd.categories = cats
    cd.add_series(title, values)
    kind = XL_CHART_TYPE.BAR_CLUSTERED if horizontal else XL_CHART_TYPE.COLUMN_CLUSTERED
    gf = s.shapes.add_chart(kind, Inches(x), Inches(y), Inches(w), Inches(h), cd)
    ch = gf.chart
    ch.has_legend = False
    ch.has_title = True
    ch.chart_title.text_frame.text = title
    tp = ch.chart_title.text_frame.paragraphs[0]
    tp.runs[0].font.size = Pt(16)
    tp.runs[0].font.bold = True
    tp.runs[0].font.name = FONT
    tp.runs[0].font.color.rgb = NAVY
    plot = ch.plots[0]
    plot.gap_width = 60
    plot.has_data_labels = True
    dl = plot.data_labels
    dl.number_format = fmt
    dl.number_format_is_linked = False
    dl.position = XL_LABEL_POSITION.OUTSIDE_END
    dl.font.size = Pt(18)
    dl.font.bold = True
    dl.font.name = FONT
    dl.font.color.rgb = NAVY
    ser = plot.series[0]
    for i in range(len(values)):
        pt = ser.points[i]
        pt.format.fill.solid()
        last = highlight_last and i == len(values) - 1
        pt.format.fill.fore_color.rgb = BLUE if last else SOFT
    va = ch.value_axis
    va.visible = False
    va.has_major_gridlines = False
    if vmax is not None:
        va.maximum_scale = vmax
    va.minimum_scale = 0
    ca = ch.category_axis
    ca.tick_labels.font.size = Pt(16)
    ca.tick_labels.font.name = FONT
    ca.tick_labels.font.color.rgb = NAVY
    ca.format.line.color.rgb = SOFT
    ca.has_major_gridlines = False
    if horizontal:
        ca.reverse_order = True
    return gf


def table(s, rows, x, y, col_w, row_h=0.55, size=17):
    shape = s.shapes.add_table(len(rows), len(col_w), Inches(x), Inches(y),
                               Inches(sum(col_w)), Inches(row_h * len(rows)))
    t = shape.table
    tblPr = t._tbl.tblPr
    for attr in ("firstRow", "bandRow"):
        tblPr.set(attr, "0")
    style = tblPr.find("{http://schemas.openxmlformats.org/drawingml/2006/main}tableStyleId")
    if style is not None:
        tblPr.remove(style)
    for i, w in enumerate(col_w):
        t.columns[i].width = Inches(w)
    for r, row in enumerate(rows):
        t.rows[r].height = Inches(row_h)
        for c, val in enumerate(row):
            cell = t.cell(r, c)
            cell.fill.solid()
            cell.fill.fore_color.rgb = MIST if r == 0 else WHITE
            cell.margin_left = cell.margin_right = Inches(0.1)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            tf = cell.text_frame
            tf.word_wrap = True
            p = tf.paragraphs[0]
            run = p.add_run()
            run.text = val
            run.font.name = FONT
            run.font.size = Pt(size)
            run.font.bold = r == 0 or c == 0
            run.font.color.rgb = NAVY
            tcPr = cell._tc.get_or_add_tcPr()
            for pos, tag in enumerate(("a:lnL", "a:lnR", "a:lnT", "a:lnB")):
                ln = tcPr.makeelement(qn(tag), {"w": "12700"})
                fill = ln.makeelement(qn("a:solidFill"), {})
                fill.append(fill.makeelement(qn("a:srgbClr"), {"val": "9FB3C0"}))
                ln.append(fill)
                tcPr.insert(pos, ln)  # borders must precede the cell fill
    return shape


def notes(s, body):
    s.notes_slide.notes_text_frame.text = body.strip()


# ---------------------------------------------------------------- slides
def build():
    prs = Presentation(str(SRC))
    drop_slides_after_first(prs)

    # 01 Title (kept from v3; subtitle and notes refreshed)
    s = prs.slides[0]
    for sh in s.shapes:
        if sh.has_text_frame and sh.text_frame.text.startswith("Human"):
            sh.text_frame.paragraphs[0].runs[0].text = (
                "Keeping workers safe without stopping the robot for no reason")
    notes(s, """
ZENAN | 0:30

Good afternoon. I'm Zenan, and with Luke and Michael I'll show you how we taught a robot to understand what a construction worker is doing, so it keeps them safe without stopping all the time. I'll cover the problem and our solution, Michael the rig and results, and Luke the project management and what it takes to use this on site.
""")

    # 02 Why it matters
    s = new_slide(prs, 2, "Why this problem matters")
    s.shapes.add_picture(str(ROOT / "paper/figures/task-frame.jpg"),
                         Inches(0.6), Inches(1.45), height=Inches(4.95))
    rows = [
        ("Overhead panel work is heavy and awkward",
         "A robot can hold the panel while the worker does the skilled part."),
        ("So the worker stands next to a moving robot",
         "Safety zones stop the robot whenever someone is close."),
        ("Stop too late: injury.  Stop too often: no one uses it.",
         "The safety system has to be right in both directions."),
    ]
    for i, (head, sub) in enumerate(rows):
        y = 1.45 + i * 1.35
        c = s.shapes.add_shape(MSO_SHAPE.OVAL, Inches(5.85), Inches(y + 0.05), Inches(0.55), Inches(0.55))
        c.fill.solid(); c.fill.fore_color.rgb = BLUE; c.line.fill.background(); c.shadow.inherit = False
        c.text_frame.text = str(i + 1)
        r = c.text_frame.paragraphs[0].runs[0]
        r.font.size = Pt(18); r.font.bold = True; r.font.color.rgb = WHITE; r.font.name = FONT
        c.text_frame.paragraphs[0].alignment = PP_ALIGN.CENTER
        text(s, [[(head, {"bold": True})], sub], 6.6, y, 6.2, 1.3, size=19)
    box(s, 5.85, 5.6, 6.95, 0.8)
    text(s, [[("Who benefits: ", {"bold": True}),
              ("installation crews, contractors, and the engineers who design and certify collaborative robots", {})]],
         6.0, 5.63, 6.7, 0.75, size=16, anchor=MSO_ANCHOR.MIDDLE)
    notes(s, """
ZENAN | 0:50

Installing ceiling panels means holding heavy boards above your head. A collaborative robot can take the weight while the worker does what people are good at: aligning and fixing the panel.

The catch is that the worker now stands next to a moving robot. Today's standard approach draws fixed zones around the robot and stops it whenever someone is inside. It can't tell someone walking in to work from someone walking away.

Stop too late and someone gets hurt. Stop too often and crews switch the robot off. Getting this right helps installation crews, contractors, and the engineers who design and certify these systems.
""")

    # 03 Our solution and why we chose it
    s = new_slide(prs, 3, "Our solution: a robot that knows the task phase")
    cards = [
        ("Fixed zones", "Distance only", "Today's practice: the baseline", SOFT),
        ("Reactive", "Distance + how fast you approach", "Shows what movement adds", SOFT),
        ("Predictive (ours)", "+ task phase\n+ 'about to step in' predictor", "Shows what context adds", BLUE),
    ]
    for i, (name, info, why, col) in enumerate(cards):
        x = 0.6 + i * 4.2
        box(s, x, 1.45, 3.85, 2.55, fill=MIST, line=col if col == BLUE else None)
        text(s, name, x + 0.2, 1.55, 3.5, 0.5, size=22, bold=True, color=BLUE if col == BLUE else NAVY)
        text(s, info, x + 0.2, 2.15, 3.5, 1.0, size=18)
        text(s, why, x + 0.2, 3.3, 3.5, 0.6, size=15, color=GREY)
        if i < 2:
            arrow(s, x + 3.88, 2.5, 0.3, 0.4)
    box(s, 0.6, 4.25, 12.25, 0.85, fill=NAVY)
    text(s, "Safety rule: the learned parts can only slow the robot, never speed it up",
         0.8, 4.3, 11.9, 0.75, size=21, bold=True, color=WHITE, anchor=MSO_ANCHOR.MIDDLE)
    whys = [
        ("Why speed and separation?", "The robot carries a panel, so contact while moving is not acceptable"),
        ("Why a hidden Markov model?", "Explainable phases, little training data, runs in real time"),
        ("Why the 'slow-only' rule?", "Safety never depends on the machine-learning being right"),
    ]
    for i, (q, a) in enumerate(whys):
        x = 0.6 + i * 4.2
        text(s, [[(q, {"bold": True, "color": BLUE})], a], x, 5.3, 3.9, 1.5, size=16)
    notes(s, """
ZENAN | 1:15

My part of the project was the software: the controllers, the sensing and the link to the robot. We compared three controllers, each adding one piece of information.

Fixed zones use distance only; that's today's practice, so it's our baseline. Reactive control also looks at how fast you're approaching. Our predictive controller adds the task phase, whether you're approaching, working or walking away, plus a predictor that flags when you're about to step into the stop zone.

The key rule is in the dark bar: the learned parts can only slow the robot, never speed it up. So a wrong guess can never make it less safe than the reactive controller.

Why these choices? The robot carries a panel, so contact while it moves is not acceptable; that points to speed and separation monitoring from the robot safety standard. The hidden Markov model gives explainable phases from very little training data. And the slow-only rule means safety never depends on the machine learning being right.
""")

    # 04 How we tested it
    s = new_slide(prs, 4, "How we tested it")
    steps = [("12", "participants (ethics approved)"), ("3", "blocks, one controller each, order rotated"),
             ("105", "trials of the panel task, with cued moves"), ("31", "questionnaires, one after each block")]
    for i, (big, lab) in enumerate(steps):
        x = 0.6 + i * 3.15
        box(s, x, 1.45, 2.75, 1.95)
        text(s, big, x, 1.5, 2.75, 0.9, size=44, bold=True, color=BLUE, align=PP_ALIGN.CENTER)
        text(s, lab, x + 0.1, 2.4, 2.55, 1.1, size=16, align=PP_ALIGN.CENTER)
        if i < 3:
            arrow(s, x + 2.78, 2.3, 0.33, 0.35)
    box(s, 0.6, 3.65, 12.25, 2.7, fill=WHITE, line=BLUE)
    text(s, "The key idea: same-input replay", 0.9, 3.8, 11.6, 0.55, size=22, bold=True, color=BLUE)
    text(s, ["Every sensor input was logged, so we re-ran all three controllers on exactly the same human movement.",
             [("Like three referees judging the same match footage: ", {"bold": True}),
              ("differences come from the controller, not the person.", {})],
             "The replay matched every robot command the live system actually sent."],
         0.9, 4.4, 11.7, 1.9, size=18)
    notes(s, """
ZENAN | 0:45

Twelve people took part under Monash ethics approval. Each did three blocks of the panel task, one controller per block, in rotated order, with cued movements like a quick step toward the robot, and a short questionnaire after each block.

Our key method decision was logging every sensor input. That let us replay all three controllers on exactly the same movement, like three referees judging the same match footage, so differences come from the controller, not the person. The replay matched every command the robot actually received.

Michael will now show you the rig we tested on and what we found.
""")

    # 05 The rig
    s = new_slide(prs, 5, "The test rig")
    s.shapes.add_picture(str(ROOT / "paper/figures/apparatus-a.jpg"), Inches(0.6), Inches(1.35), width=Inches(7.3))
    s.shapes.add_picture(str(ROOT / "paper/figures/apparatus-b.jpg"), Inches(8.45), Inches(1.35), width=Inches(4.4))
    s.shapes.add_picture(str(ROOT / "paper/figures/apparatus-c.jpg"), Inches(8.45), Inches(3.93), width=Inches(4.4))
    labels = [("UR10 robot arm", "holds a panel stand-in at ceiling height"),
              ("OptiTrack cameras", "head position to about a millimetre"),
              ("Xsens suit", "positions of 23 body segments")]
    for i, (h, sub) in enumerate(labels):
        text(s, [[(h, {"bold": True, "color": BLUE})], sub], 0.6 + i * 2.45, 5.55, 2.4, 0.95, size=15)
    text(s, "Faces blurred", 10.85, 0.95, 2.0, 0.3, size=11, color=GREY, align=PP_ALIGN.RIGHT)
    notes(s, """
MICHAEL | 0:40

My main contribution was the physical setup and assembly of this cell. [Michael: name one or two concrete things you set up.]

The UR10 arm lifts a light panel stand-in to ceiling height and holds it while the participant works underneath. The cameras on the overhead frame track a marker cap on the head to about a millimetre. The suit uses small motion sensors to give 23 body segments. The controller reads all of this about sixty times a second and decides how fast the robot may move.
""")

    # 06 Result 1: safety
    s = new_slide(prs, 6, "Result 1: all three stopped in time; ours stopped earliest")
    stat(s, "970 / 970", "entries into the stop zone where a stop had already been requested, for all three controllers", 0.6, 1.5, 5.4)
    stat(s, "+0.11\u00a0s", "earlier stop request than fixed zones, for all 12 people", 0.6, 3.75, 5.4)
    bar_chart(s, 6.4, 1.4, 6.45, 4.7, ["Fixed zones", "Reactive", "Predictive"], [31, 42, 67],
              '0"%"', "If the distance is misread by 5 cm: entries still covered", vmax=80)
    text(s, "Same-input replay, 12 people, 105 trials", 6.4, 6.2, 6.45, 0.4, size=13, color=GREY)
    notes(s, """
MICHAEL | 0:50

First, safety. Each time someone stepped into the stop zone, 970 times in total, all three controllers had already asked the robot to stop. On the measured distance, none of them failed.

The difference is timing. Ours asked for the stop about a tenth of a second earlier than fixed zones, for every one of the twelve people.

That matters when the distance is measured wrongly, which it always is a little. If the true distance was 5 centimetres smaller than measured, fixed zones would still have covered 31 percent of entries, reactive 42, and ours 67. The prediction buys a safety margin against sensing error.
""")

    # 07 Result 2: the cost
    s = new_slide(prs, 7, "Result 2: the cost was brief, unnoticed extra stops")
    bar_chart(s, 0.6, 1.4, 6.3, 4.7, ["Fixed zones", "Reactive", "Predictive"], [2.2, 6.7, 15.3],
              "0.0", "Brief stop requests (under 0.5 s) per minute", vmax=18)
    stat(s, "+0.9\u00a0s", "of unnecessary stopping per minute, compared with fixed zones", 7.3, 1.4, 5.5, big_size=44)
    stat(s, "3 · 5 · 3", "times each controller was picked as 'safest': no better than chance", 7.3, 3.05, 5.5, big_size=44)
    stat(s, "0.16\u00a0s", "median time for the robot to actually stop (max 0.23\u00a0s)", 7.3, 4.7, 5.5, big_size=44)
    notes(s, """
MICHAEL | 0:45

The cost: our controller flicked between stop and go far more often, about fifteen brief stop requests a minute against two for fixed zones. It releases the stop as soon as the risk dips, so a noisy speed estimate makes it flicker. A short release delay should remove most of this.

Overall it added under a second of unnecessary stopping per minute, and participants didn't notice. Their picks for the safest block were spread three, five and three across the controllers, which is chance.

And once asked, the robot stopped in a median of 0.16 seconds, never more than 0.23.
""")

    # 08 The task limits the gain
    s = new_slide(prs, 8, "The bigger limit is the task, not the controller")
    bar_chart(s, 0.6, 1.4, 6.3, 4.7, ["Fixed zones", "Reactive", "Predictive"], [29.7, 33.6, 36.7],
              '0.0"%"', "Share of each trial the robot was stopped (median, logged trials)", highlight_last=False, vmax=45)
    text(s, [[("About a third of every trial was stopped, ", {"bold": True}),
              ("whichever controller ran.", {})],
             "The worker has to be close to load, work under and unload the panel, so the stop zone is occupied by design."],
         7.3, 1.6, 5.5, 2.6, size=19)
    box(s, 7.3, 4.35, 5.55, 1.75, fill=NAVY)
    text(s, [[("Next gain: ", {"bold": True, "color": WHITE}),
              ("switch to a contact-safe mode while the worker is under the panel", {"color": WHITE})]],
         7.5, 4.45, 5.2, 1.55, size=19, anchor=MSO_ANCHOR.MIDDLE)
    notes(s, """
MICHAEL | 0:45

The biggest lesson was not which controller is best. Under all three, the robot was stopped for about a third of every trial, because the task puts the worker in the stop zone: you have to be close to load the panel, work under it and unload it.

So the next real gain is switching to a contact-safe mode, like hand guiding, while the worker is under the panel. Our system already knows the phase, so it can make that switch.

Luke will now explain how we managed the project and what it would take to use this on a real site.
""")

    # 09 Project management
    s = new_slide(prs, 9, "Project management: plan, setbacks and responses")
    phases = [("Jul", "Design and simulation"), ("Aug", "Rig integration and pilot tests"),
              ("Sep", "12 participant sessions"), ("Oct", "Analysis, reviews and paper")]
    for i, (m, lab) in enumerate(phases):
        x = 0.6 + i * 3.15
        box(s, x, 1.4, 2.8, 1.3, fill=BLUE if m == "Sep" else MIST)
        col = WHITE if m == "Sep" else NAVY
        text(s, [[(m, {"bold": True, "size": 20, "color": col})], [(lab, {"color": col})]],
             x + 0.15, 1.45, 2.5, 1.2, size=15)
        if i < 3:
            arrow(s, x + 2.82, 1.85, 0.3, 0.35)
    table(s, [["Setback", "How we responded"],
              ["Some sessions restarted under new IDs", "Checked identity from the data (helmet height, intake answers)"],
              ["Distance reference changed mid-study", "Analysed each version separately; replayed the exact code"],
              ["Supervisors: paper too technical", "Weekly meetings; plain-language rewrite for a civil audience"]],
          0.6, 3.0, [4.6, 7.65], row_h=0.78, size=16)
    notes(s, """
LUKE | 0:55

My role was coordinating with the lab staff and our supervisors, Yihai and Will. We planned four stages: design and simulation in July, building and pilot-testing the rig in August, twelve participant sessions in September, and analysis and writing in October.

Three setbacks shaped the project. Some sessions restarted under a new participant ID, so we worked out from the data who was who, using helmet height and intake answers. Midway through, the software's distance reference changed, so we analysed the two versions separately and replayed the exact code that ran. And our supervisors found the paper too technical, so we rewrote it in plain language. Each setback narrowed what we could claim, and we reported that honestly.
""")

    # 10 Constraints and context
    s = new_slide(prs, 10, "What it would take to use this on site")
    cards = [
        ("Safety", "A research prototype, not a certified safety function. Allow 0.5\u00a0s to react, not 0.4."),
        ("Whole-life cost", "Cameras, body suits, calibration, maintenance and training for every crew."),
        ("Worker health", "Removes overhead lifting strain; the suit itself was rated low restriction (2 of 5)."),
        ("Net zero carbon", "Not measured. Robot energy and any saving from less rework need their own study."),
        ("People and trust", "Participants rated all three as safe. Crews must accept a robot as a co-worker."),
        ("Standards", "ISO 10218 and ISO/TS 15066 set the bar any site system must meet."),
    ]
    for i, (h, b) in enumerate(cards):
        x = 0.6 + (i % 3) * 4.15
        y = 1.4 + (i // 3) * 2.55
        box(s, x, y, 3.9, 2.35)
        text(s, [[(h, {"bold": True, "color": BLUE, "size": 21})], b], x + 0.2, y + 0.15, 3.5, 2.15, size=18)
    notes(s, """
LUKE | 0:50

Moving from the lab to a site brings real constraints.

Safety: this is a research prototype using the robot's ordinary speed controls, not a certified safety function, and our measurements suggest allowing half a second to react, not 0.4.

Cost: cameras and suits need calibration, maintenance and training for every crew, weighed against the labour saved.

Health: the aim is to take overhead lifting off workers, and the suit was rated only mildly restrictive.

Carbon: we didn't measure energy use, so we make no carbon claim.

People: participants felt safe, but crews have to accept a robot as a co-worker, and any site system must meet the robot safety standards.
""")

    # 11 Answer, next steps, team
    s = new_slide(prs, 11, "Our answer, and what comes next")
    box(s, 0.6, 1.4, 6.0, 2.6, fill=NAVY)
    text(s, [[("Can a task-aware robot be as safe as fixed zones and still efficient?", {"bold": True})],
             [("Safety: yes, ", {"bold": True}), ("with more margin against sensing error.", {})],
             [("Efficiency: partly. ", {"bold": True}), ("Same trial time, slightly more stopping.", {})]],
         0.85, 1.5, 5.6, 2.45, size=18, color=WHITE)
    text(s, [[("Next", {"bold": True, "color": BLUE})],
             "Release delay on the predictor",
             "Contact-safe mode under the panel",
             "Trials with real crews on site"],
         7.0, 1.4, 5.8, 2.6, size=18)
    team = [("Zenan Wu", "Software and technical integration"),
            ("Luke Siniakov", "Coordination with lab staff and supervisors"),
            ("Michael Magila", "Physical setup and assembly")]
    for i, (n, r) in enumerate(team):
        x = 0.6 + i * 4.15
        box(s, x, 4.35, 3.9, 1.3)
        text(s, [[(n, {"bold": True})], r], x + 0.2, 4.42, 3.5, 1.2, size=16)
    text(s, "All three designed the experiment and wrote the paper. Thank you; we welcome your questions.",
         0.6, 5.9, 12.25, 0.6, size=18, bold=True, color=BLUE)
    notes(s, """
LUKE | 0:35

So, our answer. On safety, yes: our controller was as safe as fixed zones on every measure, with more margin when the sensors are wrong. On efficiency, partly: trials took the same time, but the robot stopped slightly more.

Next: a release delay, a contact-safe mode under the panel, and trials with real crews.

If you're choosing an FYP, this area combines robotics, sensing, human factors and construction, and there's plenty left to do.

Thank you, we welcome your questions.
""")

    prs.save(str(OUT))
    print("wrote", OUT)


if __name__ == "__main__":
    build()
