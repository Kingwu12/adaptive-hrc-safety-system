"""Descriptive safety and efficiency indicators per controller (97 selected trials).

Read-only on raw captures. Time totals use left-held values over positive
intervals <= 0.25 s, as in analyse_recovered.py. The red boundary is the
configured 0.94-m inner radius on the controller distance input.
"""
import argparse, csv, json, statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTROLLERS = ['fixed zone', 'reactive SSM', 'predictive SSM']
RED_M = .94
MAX_DT = .25


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--source-root', type=Path, required=True)
    ap.add_argument('--selected', type=Path, required=True)
    ap.add_argument('--out', type=Path, default=ROOT / 'data/analysis/stop-episodes/safety.json')
    a = ap.parse_args()
    agg = {c: {'red_s': 0.0, 'red_stop_s': 0.0, 'observed_s': 0.0, 'closest_m': [], 'span_s': []} for c in CONTROLLERS}
    for item in csv.DictReader(a.selected.open()):
        hits = list(a.source_root.rglob(f"*{item['session_id']}*.manifest.json"))
        assert len(hits) == 1, item['session_id']
        raw = Path(str(hits[0]).replace('.manifest.json', '.jsonl'))
        rows = [json.loads(l) for l in raw.open() if l.strip()]
        t = [r['recorded_monotonic_s'] for r in rows]
        g = agg[item['controller_condition']]
        closest = None
        for i, r in enumerate(rows):
            d = r.get('controller_decision') or {}
            dist, s = d.get('d'), d.get('speed_fraction')
            if isinstance(dist, (int, float)):
                closest = dist if closest is None else min(closest, dist)
            if i + 1 == len(rows) or not (0 < t[i + 1] - t[i] <= MAX_DT):
                continue
            dt = t[i + 1] - t[i]
            g['observed_s'] += dt
            if isinstance(dist, (int, float)) and dist <= RED_M:
                g['red_s'] += dt
                g['red_stop_s'] += dt * (s == 0)
        g['closest_m'].append(closest)
        g['span_s'].append(float(item['sample_span_s']))
    out = {}
    for c, g in agg.items():
        out[c] = {'trials': len(g['span_s']),
                  'median_trial_duration_s': statistics.median(g['span_s']),
                  'median_closest_distance_m': statistics.median(v for v in g['closest_m'] if v is not None),
                  'red_time_pct': 100 * g['red_s'] / g['observed_s'],
                  'stop_requested_in_red_pct': 100 * g['red_stop_s'] / g['red_s']}
    a.out.write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


if __name__ == '__main__':
    main()
