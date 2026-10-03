"""Two diagnostics behind the counterfactual results.

A. Closing-speed noise: how much of the anchored-body closing speed v_proj comes
   from the nearest body segment switching (a geometric jump in d), rather than
   from real body motion, and how often the intrusion predictor fires on it.
B. Robot motion inside the protective radius: for every sample where the TCP
   moved while the person was inside S0, the time since the controller first
   requested a stop (is it the measured stopping transient or something else?).

Read-only on raw captures; participant-level output goes to --out.
"""
import argparse, json, math, statistics
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MOVING = 0.02


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--captures', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    selected = [t['session_id'] for t in json.load(open(ROOT / 'data/analysis/stop-episodes/trials.json'))['trials']]
    switch_v, steady_v = [], []
    fires = Counter()
    inside_moving = []
    for sid in selected:
        prev_seg = prev_d = prev_t = None
        stop_since = None
        S0 = None
        for line in open(a.captures / f'{sid}.jsonl'):
            r = json.loads(line)
            t = r.get('recorded_monotonic_s')
            if S0 is None:
                S0 = 0.94
            bt = r.get('body_tracking') or {}
            seg = bt.get('nearest_segment')
            geo = (r.get('features') or {}).get('body_geometry') or (r.get('features') or {})
            d, v = geo.get('d'), geo.get('v_proj')
            dec = r.get('controller_decision') or {}
            sf = dec.get('speed_fraction')
            if sf == 0.0:
                stop_since = t if stop_since is None else stop_since
            else:
                stop_since = None
            if v is not None and seg is not None and prev_seg is not None:
                (switch_v if seg != prev_seg else steady_v).append(v)
                if (dec.get('rule') or '').startswith('Rapid-closing'):
                    fires['switch' if seg != prev_seg else 'steady'] += 1
            rt = r.get('robot_telemetry') or {}
            sp = rt.get('actual_tcp_speed')
            spd = math.sqrt(sum(x * x for x in sp[:3])) if sp else None
            if d is not None and spd is not None and spd > MOVING and d <= S0:
                inside_moving.append({'session': sid, 'd': d, 'tcp_speed': spd, 'speed_fraction': sf,
                                      'since_stop_s': None if stop_since is None else t - stop_since,
                                      'rule': (dec.get('rule') or dec.get('status') or '')[:70],
                                      'speed_scaling': rt.get('speed_scaling'), 'target': rt.get('target_speed_fraction'),
                                      'robot_mode': rt.get('robot_mode'), 'safety_mode': rt.get('safety_mode')})
            prev_seg, prev_d, prev_t = seg, d, t
    q = lambda v, p: sorted(v)[int(p * (len(v) - 1))]
    rep = {
        'A_closing_speed': {
            'samples_with_segment_switch': len(switch_v), 'samples_steady': len(steady_v),
            'p95_abs_v_switch': q([abs(x) for x in switch_v], .95), 'p95_abs_v_steady': q([abs(x) for x in steady_v], .95),
            'share_v_over_0.6_switch': sum(x >= .6 for x in switch_v) / len(switch_v),
            'share_v_over_0.6_steady': sum(x >= .6 for x in steady_v) / len(steady_v),
            'predictor_stop_samples': dict(fires),
        },
        'B_inside_S0_while_moving': {
            'samples': len(inside_moving),
            'stop_requested': sum(x['speed_fraction'] == 0.0 for x in inside_moving),
            'since_stop_quantiles_s': ([q([x['since_stop_s'] for x in inside_moving if x['since_stop_s'] is not None], p) for p in (.5, .9, .99, 1.0)]
                                       if any(x['since_stop_s'] is not None for x in inside_moving) else None),
            'min_d': min((x['d'] for x in inside_moving), default=None),
            'rules': Counter(x['rule'] for x in inside_moving).most_common(8),
            'long_after_stop': [x for x in inside_moving if x['since_stop_s'] is not None and x['since_stop_s'] > 0.3][:15],
            'not_stopped': [x for x in inside_moving if x['speed_fraction'] != 0.0][:15],
        },
    }
    (a.out / 'geometry-motion-diagnostics.json').write_text(json.dumps(rep, indent=1, default=str))
    print(json.dumps(rep, indent=1, default=str)[:7000])


if __name__ == '__main__':
    main()
