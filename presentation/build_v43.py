"""Build FYP-assessment-presentation-v4.3.pptx from v4.2.

v4.3 (23 Oct 2026), from team feedback:
- a quick Acknowledgement of Country opens Zenan's script (unit staff on Ed
  #112: "a quick one would suffice");
- slide 2 shows the task on a real site above our lab version of it. Photo:
  "Drywalling the Ceiling" by Qole Pejorian, CC BY 2.0,
  https://www.flickr.com/photos/36824782@N00/34589819 (credited on the slide);
- slide 4: the console screenshot and the model plot are cropped to their
  content;
- carbon is off slide 11 and out of its script. The cost and carbon answer
  stays in the guide's prepared questions.

Zenan's script stays at about 400 words: the opening and slide 2 grew, slides
3 and 4 were tightened.

    python3 presentation/build_v43.py
"""
from pptx import Presentation
from pptx.enum.text import MSO_ANCHOR
from pptx.util import Inches

from build_v4 import BLUE, GREY, HERE, NAVY, ROOT, WHITE, box, notes, text
from build_v42 import shape

SRC = HERE / "FYP-assessment-presentation-v4.2.pptx"
OUT = HERE / "FYP-assessment-presentation-v4.3.pptx"
MEDIA = HERE / "media"


def remove(sh):
    sh._element.getparent().remove(sh._element)


def crop(pic, left, top, right, bottom, x, y, w):
    """Crop by source pixels (left, top, right, bottom) and size the frame to
    the cropped aspect at width w."""
    pw, ph = pic.image.size
    pic.crop_left, pic.crop_right = left / pw, (pw - right) / pw
    pic.crop_top, pic.crop_bottom = top / ph, (ph - bottom) / ph
    pic.left, pic.top, pic.width = Inches(x), Inches(y), Inches(w)
    pic.height = Inches(w * (bottom - top) / (right - left))


def build():
    prs = Presentation(str(SRC))
    s1, s2, s3, s4, s5, s6, s7, s8, s9, s10, s11, s12 = prs.slides

    # 02: the task on a real site, with our lab version below it
    remove(shape(s2, "Picture 3"))
    site = s2.shapes.add_picture(str(MEDIA / "site-ceiling-board.jpg"), Inches(0.6), Inches(1.45))
    crop(site, 0, 23, 1024, 694, 0.6, 1.45, 4.58)
    box(s2, 0.72, 1.57, 1.75, 0.38, fill=NAVY)
    text(s2, "On site today", 0.78, 1.6, 1.65, 0.34, size=13, bold=True, color=WHITE)
    text(s2, "Photo: Qole Pejorian, CC BY 2.0", 0.6, 4.47, 4.58, 0.22, size=9, color=GREY)
    s2.shapes.add_picture(str(ROOT / "paper/figures/task-frame.jpg"), Inches(0.6), Inches(4.75), height=Inches(1.65))
    text(s2, [[("In our lab", {"bold": True, "color": BLUE})],
              "The robot holds the panel; the worker aligns and fixes it."],
         2.3, 4.75, 2.9, 1.65, size=15, anchor=MSO_ANCHOR.MIDDLE)

    # 04: crop the console and the plot to their content; the console gets
    # more of the width because it is text, and the shorter plot sits level
    # with the console's middle
    console, plot = shape(s4, "Picture 2"), shape(s4, "Picture 3")
    crop(console, 330, 0, 2870, 1380, 0.6, 1.4, 6.0)
    crop(plot, 20, 18, 2180, 815, 6.9, 1.4, 5.9)
    plot.top = console.top + (console.height - plot.height) // 2
    for name, x, w in (("TextBox 4", 0.6, 6.0), ("TextBox 5", 6.9, 5.9)):
        tb = shape(s4, name)
        tb.left, tb.width = Inches(x), Inches(w)

    # 11: five cards, carbon removed; the bottom two take the full width
    for sh in list(s11.shapes):
        if Inches(1.3) < sh.top < Inches(6.8):
            remove(sh)
    cards = [
        ("Safety", "A research prototype, not a certified safety function. Allow 0.5 s to react, not 0.4."),
        ("Whole-life cost", "Cameras, body suits, calibration, maintenance and training for every crew."),
        ("Worker health", "Removes overhead lifting strain; the suit itself was rated low restriction (2 of 5)."),
        ("People and trust", "Participants rated all three as safe. Crews must accept a robot as a co-worker."),
        ("Standards", "ISO 10218 and ISO/TS 15066 set the bar any site system must meet."),
    ]
    for i, (h, b) in enumerate(cards):
        if i < 3:
            x, y, w = 0.6 + i * 4.15, 1.4, 3.9
        else:
            x, y, w = 0.6 + (i - 3) * 6.225, 3.95, 5.975
        box(s11, x, y, w, 2.35)
        text(s11, [[(h, {"bold": True, "color": BLUE, "size": 21})], b], x + 0.2, y + 0.15, w - 0.4, 2.15, size=18)

    for i, body in SCRIPTS.items():
        notes(prs.slides[i - 1], body)
    prs.save(str(OUT))
    print("wrote", OUT)


SCRIPTS = {
1: """ZENAN | 0:30

Good afternoon. We acknowledge the Traditional Owners of the land we are meeting on, and pay our respects to their Elders.

I am Zenan, and with Luke and Michael I will present our project: a context-aware safety system that lets a collaborative robot recognise what a construction worker is doing, so it can keep them safe without stopping unnecessarily. I will introduce the problem and our system, Michael will present our testing and results, and Luke will cover project management and use on site.""",

2: """ZENAN | 0:50

Installing ceiling panels requires workers to hold heavy boards overhead. On a typical site, shown here, one person simply holds the board while another fixes it. In our laboratory, below, a collaborative robot does the holding.

However, the worker now stands beside a moving robot. Current practice defines fixed safety zones around the robot and stops it whenever a person is inside. These zones cannot distinguish a worker approaching to begin a task from one moving away. If the robot stops too late, the worker may be injured; if it stops too often, crews are likely to disable it. Solving this benefits installation crews, contractors and the engineers who certify these systems.

This leads to our research question, shown in the dark box: can a robot that is aware of the task phase keep workers as safe as fixed zones, while maintaining task efficiency?""",

3: """ZENAN | 0:50

To answer this, we compared three controllers, each adding one source of information. The fixed-zone controller uses separation distance only; this is current practice and our baseline. The reactive controller also considers approach speed. Our predictive controller adds the task phase, whether the worker is approaching, working or moving away, together with a predictor that anticipates entry into the stop zone.

The key design principle is shown in the dark bar: the learned components can only reduce the robot's speed, never increase it, so safety never depends on the machine-learning model being correct.""",

4: """ZENAN | 0:50

My contribution was the software. On the left is the operator console we developed to run each session. It verifies every sensor, assigns the controller, and records both the robot and the participant.

On the right is our trained phase model, tested on a participant it never saw. The upper bar shows what the participant was actually doing, and the lower bar shows the model's live prediction. It tracks the long working phase closely and is least certain at the transitions.

Michael will now present how we tested the system and what we found.""",

11: """LUKE | 0:45

Moving from the laboratory to a site introduces real constraints. For safety, this is a research prototype running on the robot's standard speed controls, not a certified safety function, and we would allow half a second to react. For cost, the cameras and suits require calibration, maintenance and training for every crew, weighed against the labour saved. For health, it removes overhead lifting from workers, and participants rated the suit as only mildly restrictive. Finally, crews must accept a robotic co-worker, and any site system must meet the relevant robot safety standards.""",
}


if __name__ == "__main__":
    build()
