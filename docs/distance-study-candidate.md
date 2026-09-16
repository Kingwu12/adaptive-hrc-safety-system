# Separate fixed and adaptive distances: offline development candidate

The intended comparison is a fixed stop boundary versus an adaptive stopping
distance based on observed closing speed and measured stopping time. In an
intermediate band, a stationary wearer could cause a fixed controller to stop
while a validated reactive controller could continue; a fast approach must
increase the adaptive stopping distance and stop it. Predictive phase caution
may reduce speed further but cannot override the reactive stop. These are
*controller hypotheses*, not a clearance approved for this rig.

The live participant dashboard still uses the common 0.94 m hard red boundary.
That value and the current kinematic and sensing margins are pilot placeholders,
not proven safe minima. The recorded P27 T01/T02 pilots contain one clean and
one review-needed capture; their shadow decisions are useful to replay, but
they do not measure stop performance or certify a closer limit. The HEAD rigid
body is currently intermittently untracked, so visible HEAD markers alone do
not provide reliable absolute body anchoring. The live settings were not
changed by this candidate.

The T02 dashboard stream passes the basic Xsens body audit (4,359 rows with
23 complete segments), but the labelled-trial audit fails: there is no
confirmed native MVN recording or references to native Motive and consented
video. Preserve the raw stream and its manifest; do not mark it as a fully
qualified research capture or invent the missing references.

`configs/distance_candidate.yaml` is deliberately unfilled and development
only. `scripts/offline_distance_candidate.py` refuses to compare scenarios
until all seven numeric inputs are supplied; it never drives the robot. The
synthetic tests demonstrate the desired controller distinction and a fast
approach stop, without implying their example distances are usable in person.

Before a real moving-arm participant release, measure the final sensor to
zero-motion response on the final robot/program, bound tracking and calibration
error, validate the protected arm/tool/panel swept geometry and the safety-rated
stop chain, then replay representative participant traces. Document the approved
fixed boundary and adaptive minimum with those measurements. Validate causal
phase transitions before attributing a predictive effect. The collection-stage
research readiness audit also requires objective synchronized logging,
participant data flow, protocol/ethics alignment and a frozen analysis plan.
