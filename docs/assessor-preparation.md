# FYP assessor preparation

These are likely questions inferred from the official ENG4702 presentation rubric, the manuscript and the implemented system. They are preparation prompts, not a prediction of the actual questions. The rubric addresses a general engineering audience and assigns 15% to clear, complete answers.

## How much you need to know

Everyone should explain the problem, task, three controllers, main findings, limitations and their own contribution. Zenan should be ready for deeper questions about features, the HMM, the predictor, the command constraint and analysis. Luke should lead on coordination and deployment constraints; Michael should explain the physical setup and measurement limitations. These are suggested Q&A leads, not additional claims about past responsibilities. Each person still needs an overview of the whole project.

You do not need to memorise the repository, every matrix entry or a full HMM derivation. You should understand each equation in the paper well enough to identify its inputs, output, units, assumptions and failure modes. You should be able to trace one observation through the system and explain how the technical work you claim was implemented and checked. If asked for a detail you cannot recall, explain the principle and say you would check the implementation for the exact setting. Do not guess a parameter or invent a result.

## The project in one minute

“Our project investigates how a robot and worker can coordinate during ceiling-panel installation. We built a physical prototype with motion tracking and robot telemetry. We compared the design of fixed distance bands, a controller using distance and approach speed, and a context-aware controller that adds task-phase recognition and short-horizon boundary prediction. The context-aware layer is constrained so it cannot request more speed than the reactive envelope in SSM mode. Development validation gave 79.4% causal task-phase accuracy. The experimental records provide exploratory geometry and participant-experience findings, but they do not establish that predictive control improves safety or efficiency. The contribution is the integrated prototype, its evaluation, and the requirements identified for a stronger controlled comparison.”

## Questions to practise first

### What problem are you solving and who benefits?

A worker must approach, align and fasten a panel while the robot supports it. Constant distance rules do not distinguish approach from retreat or stationary work. The intended beneficiaries are workers and system designers seeking coordinated operation with fewer unnecessary interruptions. We did not measure injury reduction, commercial cost savings or site productivity.

### Why compare three controllers?

They progressively add information: fixed distance bands; distance plus measured closing speed; then task context and boundary prediction. The reactive controller is the key comparison for determining whether context and prediction add value beyond motion-aware control. Blocks A, B and C are presentation order labels, not permanent controller identities.

### What did you actually find?

The development model achieved 79.4% causal phase accuracy and 72.5% balanced accuracy. Fourteen telemetry trials exposed sensitivity to geometry reference choice and variability in cued movements. Questionnaire responses were generally favourable; eight of eleven matched safety ratings rose between expected and experienced ratings. Those findings do not establish a controller-specific safety or efficiency benefit.

### Did predictive control beat reactive control?

The current analysis does not establish that. At identical inputs, settings and SSM mode, the context-aware command cannot exceed the reactive envelope. A benefit might arise through intervention timing and later coordination, but that requires validated response and task-performance measurements. Recognition accuracy alone is not evidence of that benefit.

### What is new if adaptive safety control already exists?

Adaptive speed control and task-aware robot coordination already exist. Our contribution is their integration and exploratory evaluation in a physical ceiling-panel task, with robot telemetry and item-level experience measurements. We do not claim a new general HMM algorithm, the first adaptive SSM method or superiority over prior systems.

### How many participants and observations were there?

The team reports twelve physical participants. The analysed material contains fourteen telemetry trials under three study IDs, 31 block forms under eleven IDs, and eleven matched intake/end response sets. Nine response sets contain all three blocks. Session restarts prevent verified one-to-one linkage of every code to a person. State the record counts explicitly; do not present trials, forms, IDs or frames as independent participants.

### Why not run a significance test or fill in the missing data?

The main problem is uncertain participant linkage and controller exposure, not just a small sample. A test relying on independent people or verified within-person conditions would be difficult to justify. We used descriptive summaries and checked sensitivity to incomplete block responses. We did not invent observations or substitute simulation. Twenty-nine of thirty block-item medians were unchanged when restricting analysis to the nine complete sets; that does not remove possible missingness bias.

### What do the questionnaires tell you about safety?

They describe perceived safety, trust and experience, not measured physical protection. Expected and experienced safety means were 3.82 and 4.45 on the original five-point items; eight matched ratings rose, one stayed the same and two fell. Trust means were 4.00 and 4.18, with five increases, three ties and three decreases. Familiarity, order and other influences were not isolated. We report individual items rather than claiming a validated NASA-TLX total or an invented trust composite.

### What caused the distance discrepancy?

Recorded head-distance values in earlier geometry versions differed from a same-row calculation using live robot TCP position by about 0.41–0.53 m on the reported summary measure. This reveals a geometric reference inconsistency. It is not proof that a person's true protective clearance was wrong by that amount. The later live-reference implementation was arithmetically consistent, but point proxies still do not validate complete body, robot, tool and panel clearance.

### Was the robot safety-certified or proved safe?

This was a laboratory research prototype. The software constrains speed requests, but the sensing geometry, reaction/stopping assumptions and output chain were not validated as an installed safety function. A command acknowledgement or Dashboard pause is not a measured or safety-rated protective stop. The SSM command constraint also does not validate separate hand-guiding and monitored-stop modes.

### What would you change if you repeated the experiment?

Keep a persistent study identifier across restarts, verify the actual controller assigned to each trial, use one validated geometry, and synchronise physical movement onset, command output and robot deceleration. Measure calibrated clearance, response latency, unnecessary stops and isolated task duration. Use a properly planned comparison with the relevant worker population. These changes target the evidence needed for the original research question.

### How did the team manage the project and constraints?

Explain real examples: integrating tracking with the robot, coordinating access and assistance, assembling the panel setup, separating geometry versions in analysis, and accounting for incomplete sessions. Zenan led software and technical integration; Luke coordinated laboratory staff and supervisors; Michael supported physical setup and assembly; all contributed to experiment design and final-report preparation. Describe cost, worker experience and environmental implications as deployment considerations because the study did not quantify those effects.

## Technical follow-ups for Zenan

### What does the HMM do?

It estimates whether the observed motion belongs to approaching, working or retreating. The phase is hidden; the inputs are observable distance, projected closing speed, speed magnitude and velocity alignment toward the robot proxy. The transition matrix describes persistence and change between phases. A three-component diagonal Gaussian mixture describes the range of input patterns expected in each phase.

The online filter combines the previous state probabilities with the transition matrix, weights them by how plausible the new observation is in each state, and normalises. In compact notation:

`new_probability(state i) ∝ likelihood(observation | i) × Σ_j(previous_probability(j) × transition(j → i))`

You should know what each term does. You do not need to recite all fitted means, variances and probabilities. An HMM is a reasonable interpretable temporal model for these phases, but this study does not demonstrate it is the best possible model. Highly persistent states can lag brief movements.

### What is causal accuracy and why also report balanced accuracy?

Causal filtering uses only present and past observations, as live operation must. Offline Viterbi decoding can use later observations and scored about 82.1%; that is not the live filter's performance. Ordinary accuracy counts correctly classified frames. Balanced accuracy averages recall across the three phases, reducing the dominance of the much larger working class. Development validation held out each of three operators in turn across 32 accepted labelled trials. The small development pool and use of those folds during development limit generalisation; the 90,487 frames are not independent human subjects.

### Does the HMM recognise a trip or hazard?

No. It recognises task phase. A separate kinematic predictor estimates approach to the configured red boundary. A person could move dangerously in any phase, so “hazard” is not treated as a fourth mutually exclusive activity. Neither channel recognises every possible fall or intention.

### Explain the separation equation and its units

`S = max(0, v_proj) × T + C + S_a`

`S` is a distance in metres. `v_proj` is the velocity component toward the proxy in metres per second; negative retreating velocity is clamped to zero. `T` is a configured combined reaction/stopping-time allowance in seconds. `C` and `S_a` are configured intrusion and uncertainty allowances in metres. The prototype uses T = 0.4 s, C = 0.2 m and S_a = 0.1 m, with a 0.3 m ramp. These are research settings, not experimentally validated installed-system bounds. The simplified equation does not explicitly include robot-speed-dependent braking distance.

For a closing speed of 2 m/s, S = 1.1 m. At a gap of 1.25 m the envelope requests `(1.25 − 1.1) / 0.3 = 0.5` of nominal speed. This is an illustrative calculation, not an observed trial result. A separate fixed red boundary at 0.94 m overrides the envelope with a zero request. Explain both rules; considering the dynamic equation alone misses that override.

### What prevents an incorrect phase estimate from increasing speed?

In SSM mode, `u_cmd = min(u_envelope, u_context)`. If the envelope permits 0.5 and the context cap permits 0.35, the request is 0.35. If context permits 1.0, it remains 0.5. Fixed red-zone and applicable tracking checks can still request a stop. This is a software command property at the same inputs and settings; it is not proof that a measured clearance or stopping assumption is correct, and it does not establish physical safety.

### How does the predictor work?

It estimates when closing motion will cross the red boundary using `d − r_red − v_proj × τ − 0.5 × a_proj × τ² = 0`. It seeks a nonnegative time within the configured 0.5 s horizon. Projected acceleration is bounded at ±4 m/s², and the fast-closing gate is 0.6 m/s. Sustained risk is debounced before a stop request. This assumes the measured short-term motion is informative about near-future motion; it can fail when motion or sensing changes abruptly. It predicts a boundary crossing, not arbitrary human behaviour.

### What happens between sensor input and robot response?

Track position and timing → estimate distance and motion features → estimate phase and boundary approach → apply the SSM envelope, context cap and overrides → issue an ordinary robot command → record the decision and robot telemetry. Requested speed and physical robot response are different observations. The nominal loop is 60 Hz, but measured intervals vary and gaps are accounted for in the analysis.

### Why are zero-command time and cue timestamps insufficient?

Zero requests include intentional task holds and proximity responses, so they are not an objective false-stop count. Recording span includes operator actions and is not isolated task completion time. A cue timestamp is not independently measured human movement onset. Response latency requires synchronised movement, command and actual robot-deceleration measurements with validated definitions.

## Code map for preparation

Read the short control path rather than trying to memorise the whole repository:

| Topic | Source |
|---|---|
| Distance and motion inputs | `src/hrc_safety/features.py`, `body_tracking.py` |
| Dynamic speed constraint | `src/hrc_safety/envelope.py` |
| Final command and mode logic | `src/hrc_safety/controllers/controllers.py` |
| Boundary prediction | `src/hrc_safety/horizon.py` |
| State estimation | `src/hrc_safety/lhmm/upper.py`, `pilot_model.py` |
| Questionnaire inclusion and scoring | `scripts/analyse_questionnaires.py` |
| Telemetry denominators and gaps | `scripts/analyse_recovered.py` |
| Independent analysis checks | `scripts/verify_empirical_analysis.py` |

The paper describes the implemented and analysed scope. Some historical code comments and design notes express broader aspirations; do not repeat them as demonstrated findings.

## A practical rehearsal

First, each person explains the one-minute project summary without reading. Next, draw the sensor-to-command path and work through the envelope example. Then take turns asking the twelve core questions, keeping initial answers to about thirty seconds and expanding only when asked. Finally, run the full deck with a timer, including handovers. Its 9:15 timing is a plan, not evidence of a completed rehearsal.

For unfamiliar questions, answer the part supported by the work, identify the specific uncertainty, and explain what measurement or check would resolve it. A clear limitation is more defensible than an unsupported claim.
