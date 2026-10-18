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

    # Rig: the participant video takes the large spot; the large photo moves to
    # the bottom right, replacing the smaller photo there.
    big, small = shape(s5, "Picture 3"), shape(s5, "Picture 5")
    x, y, w, h = big.left, big.top, big.width, big.height
    big.left, big.top, big.width, big.height = small.left, small.top, small.width, small.height
    small._element.getparent().remove(small._element)
    s5.shapes.add_movie(str(MEDIA / "clip-approach-xsens.mp4"), x, y, w, h,
                        poster_frame_image=str(MEDIA / "clip-poster.jpg"), mime_type="video/mp4")
    box(s5, x / 914400 + 0.12, y / 914400 + 0.12, 2.6, 0.42, fill=NAVY)
    text(s5, "\u25B6  Video: click to play (16 s)", x / 914400 + 0.18, y / 914400 + 0.15, 2.5, 0.38,
         size=13, bold=True, color=WHITE)

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

Good afternoon. I am Zenan, and with Luke and Michael I will present our project: a context-aware safety system that lets a collaborative robot recognise what a construction worker is doing, so it can keep them safe without stopping unnecessarily. I will introduce the problem and the system we developed, Michael will present our testing and results, and Luke will cover project management and deployment on site.""",

"""ZENAN | 0:45

Installing ceiling panels requires workers to hold heavy boards overhead. A collaborative robot can support the panel while the worker aligns and fixes it.

However, the worker now stands beside a moving robot. Current practice defines fixed safety zones around the robot and stops it whenever a person is inside. These zones cannot distinguish a worker approaching to begin a task from one moving away. If the robot stops too late, the worker may be injured; if it stops too often, crews are likely to disable it. Solving this benefits installation crews, contractors and the engineers who certify these systems.

This leads to our research question, shown in the dark box: can a robot that is aware of the task phase keep workers as safe as fixed zones, while maintaining task efficiency?""",

"""ZENAN | 0:55

To answer this, we compared three controllers, each adding one source of information. The fixed-zone controller uses separation distance only; this is current practice and our baseline. The reactive controller also considers approach speed. Our predictive controller adds the task phase, whether the worker is approaching, working or moving away, together with a predictor that anticipates entry into the stop zone.

The key design principle is shown in the dark bar: the learned components can only reduce the robot's speed, never increase it. An incorrect prediction therefore cannot make the system less safe, and safety never depends on the machine-learning model being correct.""",

"""ZENAN | 0:55

My contribution was the software. On the left is the operator console we developed to run each session. It verifies every sensor before a trial, assigns the controller, and records the motion of both the robot and the participant.

On the right is our trained phase model, evaluated on a participant it never saw during training. The upper bar shows what the participant was actually doing, and the lower bar shows the model's live prediction. It tracks the long working phase closely, with uncertainty mainly at the transitions between phases.

Michael will now present how we tested the system and what we found.""",

"""MICHAEL | 0:40

Thank you, Zenan. Twelve participants took part under Monash ethics approval. Each completed three blocks of the panel task, with one controller per block in a rotated order. The task included cued movements, such as a quick step towards the robot, and a short questionnaire followed each block.

Our key methodological decision was to log every sensor input. This allowed us to replay all three controllers on identical movement data, much like three referees reviewing the same match footage, so any difference in outcome comes from the controller rather than the participant.""",

"""MICHAEL | 0:40

My main contribution was the physical setup: I positioned the robot and built the PVC pipe structure shown here.

The UR10 arm raises a panel substitute to ceiling height and holds it while the participant works beneath it. Cameras on the frame track the participant's head to about one millimetre, and the motion-capture suit records 23 body segments. [Click the video.] This clip shows a participant approaching while the suit streams their movement to the controller. The controller reads these data about sixty times per second and sets the speed the robot is permitted to move at.""",

"""MICHAEL | 0:50

This answers the first part of our question: is it as safe? Across all 970 entries into the stop zone, every controller had already commanded the robot to stop. On the measured distance, none of them failed.

The difference is timing. Our controller requested the stop about a tenth of a second earlier, for every one of the twelve participants. This matters because distance measurement always carries some error. With a five-centimetre error, the fixed zones would still have covered 31 per cent of entries, compared with 67 per cent for our controller. It is therefore as safe, with a larger margin.""",

"""MICHAEL | 0:50

The second part: is it still efficient? Partly. Our controller switched between stopping and resuming more often, because it releases the stop as soon as the estimated risk falls, so noise in the speed estimate causes it to toggle. A short release delay should resolve most of this.

Overall, it added less than one second of unnecessary stopping per minute, and participants did not notice a difference: their choices of the safest block were split three, five and three, consistent with chance. When a stop was commanded, the robot halted within a quarter of a second.

Luke will now discuss what these results mean and how we managed the project.""",

"""LUKE | 0:40

Thank you, Michael. Our most important finding was not which controller was best. Under all three, the robot was stopped for about one third of every trial, because the task itself requires the worker to be inside the stop zone: to load the panel, to work beneath it and to unload it.

The next real gain is therefore to switch to a contact-safe mode, such as hand guiding, while the worker is beneath the panel. Because our system already identifies the task phase, it provides the information needed to make that switch.""",

"""LUKE | 0:50

My role was coordinating with the laboratory staff and our supervisors, Yihai and Will. We planned four stages: design and simulation in July, building and pilot testing the rig in August, twelve participant sessions in September, and analysis and writing in October.

Three setbacks shaped the project. First, some sessions were restarted under a new participant ID, so we matched sessions to participants using the recorded data. Second, the distance reference changed midway through testing, so we analysed the two versions separately and replayed the exact code that had run. Third, our paper was initially too technical, so we rewrote it for a broader audience.""",

"""LUKE | 0:50

Moving from the laboratory to a site introduces real constraints. For safety, this is a research prototype running on the robot's standard speed controls, not a certified safety function, and we would allow half a second to react. For cost, the cameras and suits require calibration, maintenance and training for every crew, weighed against the labour saved. For health, it removes overhead lifting from workers, and participants rated the suit as only mildly restrictive. For carbon, we did not measure energy use, so we make no claim. Finally, crews must accept a robotic co-worker, and any site system must meet the relevant robot safety standards.""",

"""LUKE | 0:40

To return to our research question: can a task-aware robot be as safe as fixed zones and remain efficient? On safety, yes: it was as safe on every measure, with a larger margin under sensor error. On efficiency, partly: trial times were unchanged, with slightly more stopping. For industry, this shows that task awareness can be layered on top of a standard safety limit without weakening it.

Next steps are a release delay, a contact-safe mode beneath the panel, and trials with real installation crews. For students choosing a final-year project, it combines robotics, sensing, human factors and construction, with plenty left to do. Thank you; we welcome your questions.""",
]


if __name__ == "__main__":
    build()
