"""Build FYP-assessment-presentation-v4.2.pptx from v4 (= Drive v4.1, 6 Oct 2026).

v4.2 (14 Oct 2026), from supervisor feedback:
- the research question is on screen early (slide 2) and every result slide
  says which part of it the slide answers;
- show more of the actual work: the rig video, our operator console and the
  trained phase model (new slide 4);
- 3 minutes per speaker: Zenan 1-4, Michael 5-8, Luke 9-12. Scripts are in the
  speaker notes, timed at about 140 words a minute.

    python3 presentation/build_v42.py
"""
from pptx import Presentation
from pptx.util import Inches

from build_v4 import BLUE, GREY, HERE, NAVY, WHITE, box, notes, text

SRC = HERE / "FYP-assessment-presentation-v4.pptx"
OUT = HERE / "FYP-assessment-presentation-v4.2.pptx"
MEDIA = HERE / "media"


def shape(s, name):
    return next(sh for sh in s.shapes if sh.name == name)


def set_runs(sh, runs):
    """Replace the first paragraph's runs' text, keeping their formatting."""
    p = sh.text_frame.paragraphs[0]
    for r, t in zip(p.runs, runs):
        r.text = t


def answers_tag(s, label):
    box(s, 0.55, 0.1, 3.6, 0.36, fill=BLUE)
    text(s, label, 0.62, 0.11, 3.5, 0.34, size=13, bold=True, color=WHITE)


def build():
    prs = Presentation(str(SRC))
    s1, s2, s3, s4, s5, s6, s7, s8, s9, s10, s11 = prs.slides

    # 02: problem -> research question
    set_runs(shape(s2, "TextBox 9"), ["Stop too late: injury.  Stop too often: no one uses it."])
    set_runs(shape(s2, "TextBox 11"), ["Our question: ",
             "can a robot that knows the task phase keep workers as safe as fixed zones, and still keep the work efficient?"])
    for r in shape(s2, "TextBox 11").text_frame.paragraphs[0].runs:
        r.font.color.rgb = WHITE
    shape(s2, "Rounded Rectangle 10").fill.fore_color.rgb = NAVY
    tb = shape(s2, "TextBox 9").text_frame
    tb.paragraphs[1].runs[0].text = "Crews and contractors need it right both ways."

    # 05 (was 04) and the result slides: say which part of the question they answer
    answers_tag(s6, "Answers: is it as safe?")
    answers_tag(s7, "Answers: is it still efficient?")
    answers_tag(s8, "Answers: where is the real gain?")

    # Rig: bottom-right photo becomes the participant video
    pic = shape(s5, "Picture 5")
    x, y, w, h = pic.left, pic.top, pic.width, pic.height
    pic._element.getparent().remove(pic._element)
    s5.shapes.add_movie(str(MEDIA / "clip-approach-xsens.mp4"), x, y, w, h,
                        poster_frame_image=str(MEDIA / "clip-poster.jpg"), mime_type="video/mp4")

    # New slide: what we built (console + trained model)
    layout = s3.slide_layout
    new = prs.slides.add_slide(layout)
    for ph in list(new.placeholders):
        ph._element.getparent().remove(ph._element)
    text(new, "What we built: the console and the trained model", 0.48, 0.42, 12.3, 0.8, size=32, bold=True)
    new.shapes.add_picture(str(MEDIA / "dashboard-participant.png"), Inches(0.6), Inches(1.4), width=Inches(5.6))
    new.shapes.add_picture(str(MEDIA / "model/held-out-trial.png"), Inches(6.5), Inches(1.4), width=Inches(6.25))
    text(new, [[("Our operator console", {"bold": True})],
               "Runs every session: checks the sensors, assigns the controller, records everything."],
         0.6, 4.75, 5.6, 1.2, size=16)
    text(new, [[("Our trained phase model on a new person", {"bold": True})],
               "Top: what they were doing. Bottom: what the model said, live."],
         6.5, 4.75, 6.25, 1.2, size=16)
    text(new, "Built and trained by the team: 32 labelled trials, about 90,000 motion frames, open on GitHub.",
         0.6, 5.95, 12.1, 0.5, size=15, color=GREY)

    # Order: 1 2 3 new 4 5 6 7 8 9 10 11
    lst = prs.slides._sldIdLst
    ids = list(lst)
    order = ids[:3] + [ids[-1]] + ids[3:-1]
    for e in ids:
        lst.remove(e)
    for e in order:
        lst.append(e)
    for i, s in enumerate(prs.slides, 1):
        for sh in s.shapes:
            if sh.has_text_frame and sh.top > Inches(6.8) and sh.text_frame.text.strip().isdigit():
                sh.text_frame.paragraphs[0].runs[0].text = f"{i:02d}"
    if not any(sh.has_text_frame and sh.text_frame.text == "04" for sh in new.shapes):
        text(new, "04", 0.51, 6.96, 0.6, 0.25, size=12, color=GREY)

    for s, body in zip(prs.slides, SCRIPTS):
        notes(s, body)
    prs.save(str(OUT))
    print("wrote", OUT)


SCRIPTS = [
"""ZENAN | 0:25

Good afternoon. I'm Zenan, and with Luke and Michael I'll show you how we taught a robot to understand what a construction worker is doing, so it keeps them safe without stopping all the time. I'll cover the problem and what we built, Michael the testing and results, and Luke the project and what it takes to use this on site.""",

"""ZENAN | 0:45

Installing ceiling panels means holding heavy boards above your head. A collaborative robot can take the weight while the worker aligns and fixes the panel.

The catch: the worker now stands next to a moving robot. Today's standard draws fixed zones around the robot and stops it whenever someone is inside. It can't tell someone walking in to work from someone walking away. Stop too late and someone gets hurt; stop too often and crews switch the robot off. Getting it right helps installation crews, contractors and the engineers who certify these robots.

So our question, in the dark box: can a robot that knows the task phase keep workers as safe as fixed zones, and still keep the work efficient?""",

"""ZENAN | 0:55

To answer it we compared three controllers, each adding one piece of information. Fixed zones use distance only; that's today's practice, so it's our baseline. Reactive control also looks at how fast you're approaching. Ours, the predictive controller, adds the task phase, whether you're approaching, working or walking away, plus a predictor that flags when you're about to step into the stop zone.

The key rule is the dark bar: the learned parts can only slow the robot, never speed it up. So a wrong guess can never make it less safe, and safety never depends on the machine learning being right.""",

"""ZENAN | 0:55

My part was the software, and this is what it looks like. On the left is the console we built to run every session: it checks every sensor before a trial, assigns the controller, and records everything the robot and the person did.

On the right is our trained model on a person it never saw during training. The top bar is what they were actually doing, the bottom bar is what the model said live. It follows the long working phase well and only hesitates at the changeovers.

Michael will now show you how we tested it and what we found.""",

"""MICHAEL | 0:40

Thanks Zenan. Twelve people took part under Monash ethics approval. Each did three blocks of the panel task, one controller per block in rotated order, with cued movements like a quick step toward the robot, and a short questionnaire after each block.

Our key method decision was logging every sensor input. That let us replay all three controllers on exactly the same movement, like three referees judging the same match footage, so any difference comes from the controller, not the person.""",

"""MICHAEL | 0:40

My main contribution was this physical setup: I positioned the robot and built the PVC pipe structure you can see.

The UR10 arm lifts a panel stand-in to ceiling height and holds it while the participant works underneath. Cameras on the frame track the head to about a millimetre, and the suit gives 23 body segments; the video shows that in action. The controller reads all of this about sixty times a second and decides how fast the robot may move.""",

"""MICHAEL | 0:50

This answers the first half of our question: is it as safe? Each time someone stepped into the stop zone, 970 times in total, all three controllers had already asked the robot to stop. On the measured distance, none of them failed.

The difference is timing. Ours asked for the stop about a tenth of a second earlier, for every one of the twelve people. That matters because the distance is always measured a little wrong: if it was five centimetres off, fixed zones would still have covered 31 percent of entries and ours 67. So yes, it is as safe, with more margin.""",

"""MICHAEL | 0:50

The second half: is it still efficient? Partly. Ours flicked between stop and go more often, because it releases the stop as soon as the risk dips, so a noisy speed estimate makes it flicker. A short release delay should fix most of that.

Overall it added under a second of unnecessary stopping per minute, and participants didn't notice: their picks for the safest block were spread three, five and three, which is chance. And once asked, the robot stopped within a quarter of a second.

Luke will now take us through what this means and how we ran the project.""",

"""LUKE | 0:40

Thanks Michael. The biggest lesson was not which controller is best. Under all three, the robot was stopped for about a third of every trial, because the task itself puts the worker in the stop zone: you have to be close to load the panel, work under it and unload it.

So the next real gain is switching to a contact-safe mode, like hand guiding, while the worker is under the panel. Our system already knows the phase, so it can make that switch.""",

"""LUKE | 0:50

My role was coordinating with the lab staff and our supervisors, Yihai and Will. We planned four stages: design and simulation in July, building and pilot-testing the rig in August, twelve participant sessions in September, and analysis and writing in October.

Three setbacks shaped the project. Some sessions restarted under a new ID, so we worked out from the data who was who. Midway, the distance reference changed, so we analysed the two versions separately and replayed the exact code that ran. And the paper was too technical, so we rewrote it in plain language.""",

"""LUKE | 0:50

Moving from the lab to a site brings real constraints. Safety: this is a research prototype on the robot's ordinary speed controls, not a certified safety function, and we'd allow half a second to react. Cost: cameras and suits need calibration, maintenance and training for every crew, weighed against the labour saved. Health: it takes overhead lifting off workers, and the suit was rated only mildly restrictive. Carbon: we didn't measure energy, so we make no claim. People and standards: crews have to accept a robot co-worker, and any site system must meet the robot safety standards.""",

"""LUKE | 0:40

So, back to our question. Can a task-aware robot be as safe as fixed zones and still efficient? On safety, yes: as safe on every measure, with more margin when the sensors are wrong. On efficiency, partly: same trial time, slightly more stopping. For industry, that means task awareness can sit on top of a standard safety limit without weakening it.

Next: a release delay, a contact-safe mode under the panel, and trials with real crews. If you're choosing an FYP, this mixes robotics, sensing, people and construction, and there's plenty left to do. Thank you, we welcome your questions.""",
]


if __name__ == "__main__":
    build()
