"""Paired counterfactual replay, necessity of stops, and measured robot response.

For every selected participant-study trial this script:

1. Replays the three study controllers (and predictive variants) over the SAME
   logged control inputs (anchored-body d, v_proj, a_proj, speed and body
   features), sample by sample, with the shared fail-closed holds the live loop
   applied to every controller. This is open loop: it shows what each policy
   would have requested for identical human motion, not how the person or robot
   would then have moved.
2. Checks replay fidelity against the logged applied decision and, where
   recorded, the logged shadow decisions of the other two controllers.
3. Classifies every requested stop with hindsight: a stop sample is NECESSARY
   if the person is inside the fixed protective radius S0 or enters it within H
   seconds; otherwise it is UNNECESSARY. H is reported as a grid.
4. For every protective-radius entry, reports whether each controller was
   already requesting a stop and how far ahead it started (lead time).
5. Closed loop, applied controller only: robot response latency from the stop
   request to measured TCP standstill, and separation while the TCP moved.

Read-only on raw captures. Participant-level outputs are written to --out,
which must be outside the public repository.
"""
from __future__ import annotations

import argparse, copy, json, math, sys
from concurrent.futures import ProcessPoolExecutor
from dataclasses import fields, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from hrc_safety.analysis import build_controller  # noqa: E402
from hrc_safety.envelope import build_envelope  # noqa: E402
from hrc_safety.features import FeatureFrame  # noqa: E402
from hrc_safety.pilot_model import load_upper_hmm  # noqa: E402
from hrc_safety.horizon import fused_risk, time_to_breach  # noqa: E402
from hrc_safety.lhmm.upper import STATES  # noqa: E402

CONTROLLERS = {'fixed zone': 'fixed_zone', 'reactive SSM': 'dynamic_ssm', 'predictive SSM': 'adaptive'}
# Predictive variants: onset dwell (ticks of sustained risk before stopping) and
# release hold (seconds a predictor stop is held after risk clears).
VARIANTS = {
    'predictive dwell4': {'hazard_dwell_ticks': 4},
    'predictive dwell6': {'hazard_dwell_ticks': 6},
    'predictive dwell8': {'hazard_dwell_ticks': 8},
    'predictive hold0.3': {'release_hold_s': 0.3},
    'predictive dwell4+hold0.3': {'hazard_dwell_ticks': 4, 'release_hold_s': 0.3},
}
HORIZONS = [0.5, 1.0, 2.0]
MAX_DT = 0.25
MOVING = 0.02      # m/s, TCP linear speed treated as moving
STILL = 0.005      # m/s, TCP linear speed treated as stopped
FRAME_FIELDS = {f.name for f in fields(FeatureFrame)}
FALLBACK_CONFIG = None
MODEL_PATH = None


def frame_from(features):
    return FeatureFrame(**{k: v for k, v in features.items() if k in FRAME_FIELDS})


def norm3(v):
    return math.sqrt(sum(x * x for x in v[:3])) if v else None


class HeldPredictive:
    """Predictive controller with a release hold on predictor-issued stops."""

    def __init__(self, inner, hold_s):
        self.inner, self.hold_s, self.until = inner, hold_s, -1.0

    def decide(self, frame, robot_mode='ssm'):
        d = self.inner.decide(frame, robot_mode=robot_mode)
        if d.speed_fraction == 0.0 and d.rule.startswith('Rapid-closing'):
            self.until = frame.t + self.hold_s
        elif frame.t < self.until:
            d = replace(d, speed_fraction=0.0, rule='release hold')
        return d


class TrunkIntentPredictive:
    """Predictive variant: the pre-emptive intrusion predictor reads closing
    speed and acceleration of the trunk (head-column features), while the
    distance limit, envelope and red boundary still use the whole anchored body.
    Limb reaches (hands to the overhead panel, foot placement) no longer count
    as intrusion intent; the whole-body distance limit still covers them."""

    def __init__(self, inner):
        self.inner = inner

    def decide(self, frame, robot_mode='ssm'):
        c = self.inner
        body = frame.for_control()
        zone = c.zones.update(body.d)
        env = c.envelope.evaluate(body.d, body.v_proj)
        if c.use_state_layer and c.hmm is not None:
            post = c.hmm.step(frame.as_vector(c.hmm.feature_order))
            inferred = STATES[int(max(range(len(post)), key=lambda i: post[i]))]
        else:
            inferred = 'n/a'
        # Trunk kinematics drive the predictor; time to breach uses the body distance.
        ttb = time_to_breach(body.d, frame.v_proj, frame.a_proj, c.zones.red_radius, c.horizon_s, c.max_human_accel)
        risk = fused_risk(0.0, ttb, c.horizon_s, c.imminence_steepness, v_proj=frame.v_proj, min_closing=c.min_closing_speed)
        c._hazard_streak = c._hazard_streak + 1 if risk >= c.risk_threshold else 0
        closing_fast = frame.v_proj >= c.min_closing_speed
        command, speed, rule = c._decide_command(zone, env.max_speed, inferred, risk, robot_mode, closing_fast)
        return SimpleDecision(speed, rule)


class SimpleDecision:
    def __init__(self, speed_fraction, rule):
        self.speed_fraction, self.rule = speed_fraction, rule


def build_legacy_predictive(config, hmm):
    """Predictive controller as it ran on 9 Sep (commit c852471 yellow-zone cap)."""
    from hrc_safety.analysis import _fresh_hmm, build_zone_model
    from hrc_safety.controllers.legacy_c852471 import EnvelopeAdaptiveController as Legacy
    lh, hz = config['lhmm'], config['horizon']
    return Legacy(build_zone_model(config), _fresh_hmm(hmm), envelope=build_envelope(config),
                  speed_reduced=config['controller']['speed_reduced'],
                  hazard_prob_threshold=lh['hazard_prob_threshold'], hazard_dwell_ticks=lh['hazard_dwell_ticks'],
                  working_stability_ticks=config['controller']['working_stability_ticks'],
                  horizon_s=hz['horizon_s'], imminence_steepness=hz['imminence_steepness'],
                  risk_threshold=hz['risk_threshold'], max_human_accel=hz['max_human_accel'],
                  min_closing_speed=hz['min_closing_speed'], condition='adaptive')


def build_all(config, hmm, legacy=False):
    out = {name: build_controller(key, config, hmm) for name, key in CONTROLLERS.items()}
    if legacy:
        out['predictive SSM'] = build_legacy_predictive(config, hmm)
    for name, spec in VARIANTS.items():
        cfg = copy.deepcopy(config)
        if 'hazard_dwell_ticks' in spec:
            cfg['lhmm']['hazard_dwell_ticks'] = spec['hazard_dwell_ticks']
        c = build_controller('adaptive', cfg, hmm)
        out[name] = HeldPredictive(c, spec['release_hold_s']) if 'release_hold_s' in spec else c
    for dwell in (2, 4):
        cfg = copy.deepcopy(config); cfg['lhmm']['hazard_dwell_ticks'] = dwell
        out[f'predictive trunk-intent dwell{dwell}'] = TrunkIntentPredictive(build_controller('adaptive', cfg, hmm))
    return out


def cause(rule):
    r = (rule or '').lower()
    for key, label in (('body evidence', 'body evidence hold'), ('fail closed', 'tracking hold'),
                       ('supervisor', 'tracking hold'), ('red zone', 'red boundary'),
                       ('rapid-closing', 'intrusion predictor'), ('release hold', 'intrusion predictor'),
                       ('envelope=0', 'envelope'), ('final speed', 'envelope')):
        if key in r:
            return label
    return 'other'


def analyse(path_str):
    path = Path(path_str)
    manifest = json.loads(path.with_suffix('.manifest.json').read_text())
    config = (manifest.get('study_release') or {}).get('config') or FALLBACK_CONFIG
    hmm = load_upper_hmm(MODEL_PATH)
    # Replay-verified: only sessions before 12:00 on 9 Sep (P13) ran the c852471 cap.
    legacy = path.stem.split('-')[2] + path.stem.split('-')[3] < '20260909120000'
    ctrls = build_all(config, hmm, legacy)
    zones = config['zones']
    S0 = zones['K'] * zones['T'] + zones['C'] + zones['Sa']
    env = build_envelope(config)
    applied_name = manifest['controller_condition']
    names = list(ctrls)

    t, d, vproj, shared, cmd = [], [], [], [], {n: [] for n in names}
    causes = {n: [] for n in names}
    logged, shadow_logged = [], {n: [] for n in CONTROLLERS}
    tcp_speed, applied_logged_cause, scaling = [], [], []
    with open(path) as fh:
        for line in fh:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            ts = r.get('recorded_monotonic_s')
            if ts is None:
                continue
            dec = r.get('controller_decision') or {}
            feat = r.get('features')
            frame = None
            if feat:
                try:
                    frame = frame_from(feat)
                except (TypeError, ValueError):
                    frame = None
            hold = 'status' in dec or frame is None
            for n in names:
                if frame is not None:
                    try:
                        out = ctrls[n].decide(frame, robot_mode='ssm')
                        s, why = out.speed_fraction, cause(out.rule)
                    except ValueError:
                        s, why = 0.0, 'tracking hold'
                else:
                    s, why = 0.0, 'tracking hold'
                if hold:
                    s, why = 0.0, cause(dec.get('rule')) if dec else 'tracking hold'
                cmd[n].append(s); causes[n].append(why)
            geo = (feat or {}).get('body_geometry') or feat or {}
            t.append(ts); d.append(geo.get('d')); vproj.append(geo.get('v_proj')); shared.append(hold)
            logged.append(dec.get('speed_fraction'))
            applied_logged_cause.append(cause(dec.get('rule')))
            comp = r.get('controller_comparison') or {}
            for n in CONTROLLERS:
                shadow_logged[n].append((comp.get(n) or {}).get('speed_fraction'))
            rt = r.get('robot_telemetry') or {}
            tcp_speed.append(norm3(rt.get('actual_tcp_speed')) if rt.get('available') else None)
            scaling.append(rt.get('speed_scaling'))

    n = len(t)
    dt = [t[i + 1] - t[i] if i + 1 < n and 0 < t[i + 1] - t[i] <= MAX_DT else 0.0 for i in range(n)]
    observed = sum(dt)

    def agree(a, b):
        pairs = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
        return (sum(abs(x - y) < 1e-6 for x, y in pairs) / len(pairs), len(pairs)) if pairs else (None, 0)

    fidelity = {'applied': agree(cmd[applied_name], logged)}
    for c in CONTROLLERS:
        fidelity['shadow ' + c] = agree(cmd[c], shadow_logged[c])

    # Hindsight necessity: time until the person is next inside S0.
    inside = [x is not None and x <= S0 for x in d]
    next_inside = [math.inf] * n
    nxt = math.inf
    for i in range(n - 1, -1, -1):
        if inside[i]:
            nxt = t[i]
        next_inside[i] = nxt - t[i] if nxt != math.inf else math.inf
    entries = [i for i in range(1, n) if inside[i] and not inside[i - 1] and dt[i - 1] > 0]

    per = {}
    for name in names:
        s = cmd[name]
        stop = [x == 0.0 for x in s]
        res = {'stop_s': sum(dt[i] for i in range(n) if stop[i]),
               'stop_s_excl_shared_hold': sum(dt[i] for i in range(n) if stop[i] and not shared[i]),
               'onsets': sum(1 for i in range(1, n) if stop[i] and not stop[i - 1] and dt[i - 1] > 0)}
        # Brief stop segments (< 0.5 s) excluding shared holds.
        seg, brief = 0.0, 0
        for i in range(n):
            if stop[i] and not shared[i]:
                seg += dt[i]
            elif seg:
                brief += seg < 0.5; seg = 0.0
        res['brief_segments'] = brief
        for H in HORIZONS:
            res[f'unnecessary_s_H{H}'] = sum(dt[i] for i in range(n) if stop[i] and not shared[i] and next_inside[i] > H)
            res[f'necessary_s_H{H}'] = sum(dt[i] for i in range(n) if stop[i] and not shared[i] and next_inside[i] <= H)
        # Running inside S0 and below the dynamic protective distance.
        res['run_inside_S0_s'] = sum(dt[i] for i in range(n) if inside[i] and not stop[i])
        res['run_below_dynamic_Sp_s'] = sum(dt[i] for i in range(n) if d[i] is not None and vproj[i] is not None
                                            and d[i] <= env.stop_distance(vproj[i]) and s[i] > 0)
        # Lead time at each S0 entry: how long the request had been a continuous stop.
        leads = []
        for e in entries:
            j, lead = e, 0.0
            while j > 0 and stop[j - 1] and dt[j - 1] > 0:
                j -= 1; lead += dt[j]
            leads.append(lead if stop[e] else -1.0)
        res['entry_leads_s'] = leads
        by_cause = {}
        for i in range(n):
            if stop[i] and not shared[i]:
                by_cause[causes[name][i]] = by_cause.get(causes[name][i], 0.0) + dt[i]
        res['stop_s_by_cause'] = by_cause
        per[name] = res

    # Closed loop, applied controller.
    lat, moving_d = [], []
    for i in range(1, n):
        if logged[i] == 0.0 and logged[i - 1] not in (0.0, None) and tcp_speed[i] is not None and tcp_speed[i] > MOVING:
            j = i
            while j < n and t[j] - t[i] < 3.0 and (tcp_speed[j] is None or tcp_speed[j] > STILL) and logged[j] == 0.0:
                j += 1
            if j < n and logged[j] == 0.0 and tcp_speed[j] is not None and tcp_speed[j] <= STILL:
                lat.append({'latency_s': t[j] - t[i], 'speed_at_request': tcp_speed[i], 'd_at_request': d[i],
                            'cause': applied_logged_cause[i]})
    # Program motion: TCP speed above MOVING with nonzero speed scaling, or braking
    # (the TCP was moving when the stop was requested, until it first reaches
    # standstill). TCP speed with zero scaling otherwise is the held arm being
    # pushed (checked: a few mm out and back, starting from rest), counted apart.
    braking, pushed = False, []
    for i in range(n):
        if logged[i] == 0.0 and (i == 0 or logged[i - 1] != 0.0):
            braking = tcp_speed[i] is not None and tcp_speed[i] > MOVING
        if braking and (logged[i] != 0.0 or (tcp_speed[i] is not None and tcp_speed[i] <= STILL)):
            braking = False
        prog = (scaling[i] or 0) > 0 or braking
        if tcp_speed[i] is not None and tcp_speed[i] > MOVING and d[i] is not None:
            (moving_d if prog else pushed).append((d[i], dt[i]))
    closed = {'response': lat,
              'moving_s': sum(w for _, w in moving_d),
              'min_d_while_moving': min((x for x, _ in moving_d), default=None),
              'inside_S0_while_moving_s': sum(w for x, w in moving_d if x <= S0),
              'held_arm_pushed_s': sum(w for _, w in pushed),
              'held_arm_pushed_inside_S0_s': sum(w for x, w in pushed if x <= S0),
              'tcp_speed_available_fraction': sum(x is not None for x in tcp_speed) / n if n else 0}

    return {'legacy_predictive_version': legacy, 'session_id': path.stem, 'code': path.stem.split('-')[0], 'trial': path.stem.split('-')[1],
            'applied': applied_name, 'block': manifest.get('block_label'),
            'capture_mode': manifest.get('capture_mode'), 'samples': n, 'observed_s': observed,
            'S0': S0, 'entries': len(entries), 'fidelity': fidelity, 'controllers': per, 'closed_loop': closed}


def init(cfg, model):
    global FALLBACK_CONFIG, MODEL_PATH
    FALLBACK_CONFIG, MODEL_PATH = cfg, model


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--captures', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--model', type=Path, required=True)
    ap.add_argument('--extra', nargs='*', default=[], help='additional study codes to include')
    ap.add_argument('--workers', type=int, default=6)
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    selected = [x['session_id'] for x in json.load(open(ROOT / 'data/analysis/stop-episodes/trials.json'))['trials']]
    paths = [a.captures / f'{s}.jsonl' for s in selected]
    for code in a.extra:
        for p in sorted(a.captures.glob(f'{code}-T*.jsonl')):
            if not p.name.endswith('.events.jsonl') and p.stat().st_size > 100_000:
                paths.append(p)
    # Legacy captures lack a study_release config; use the first recorded one.
    cfg = None
    for m in sorted(a.captures.glob('*.manifest.json')):
        c = (json.loads(m.read_text()).get('study_release') or {}).get('config')
        if c:
            cfg = c; break
    results = []
    with ProcessPoolExecutor(a.workers, initializer=init, initargs=(cfg, str(a.model))) as ex:
        for res in ex.map(analyse, [str(p) for p in paths]):
            f = res['fidelity']
            print(res['session_id'], res['applied'], 'fidelity', {k: (round(v[0], 4) if v[0] is not None else None) for k, v in f.items()}, flush=True)
            results.append(res)
    (a.out / 'counterfactual-per-trial.json').write_text(json.dumps(results, indent=1))


if __name__ == '__main__':
    main()
