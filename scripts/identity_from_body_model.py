"""Participant identity check from the Xsens MVN body model.

MVN scales a rigid 23-segment model to each person's measured body dimensions at
calibration, so the distance between adjacent segment origins (thigh, shank,
upper arm, forearm, hip and shoulder width, spine) is a per-person constant.
This script measures those distances in every raw capture and reports, per study
code, whether the code is one body and whether two codes share a body.

Read-only on raw captures. Writes participant-level output OUTSIDE the repo
(--out), because the repository is public.
"""
import argparse, csv, json, math, statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# MVN segment ids: 1 pelvis, 6 neck, 7 head, 9/13 R/L upper arm, 10/14 forearm,
# 11/15 hand, 16/20 upper leg, 17/21 lower leg, 18/22 foot, 19/23 toe.
LINKS = {
    'thigh_r': (16, 17), 'thigh_l': (20, 21), 'shank_r': (17, 18), 'shank_l': (21, 22),
    'upper_arm_r': (9, 10), 'upper_arm_l': (13, 14), 'forearm_r': (10, 11), 'forearm_l': (14, 15),
    'hip_width': (16, 20), 'shoulder_width': (9, 13), 'spine': (1, 6), 'neck_head': (6, 7),
    'foot_r': (18, 19), 'foot_l': (22, 23),
}
STRIDE = 25


def dist(a, b):
    return math.dist(a, b)


def measure(path):
    vals = {k: [] for k in LINKS}
    first = None
    with open(path) as fh:
        for i, line in enumerate(fh):
            if i % STRIDE:
                continue
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get('stale'):
                continue
            seg = ((r.get('xsens_frame') or {}).get('segments')) or {}
            if len(seg) < 23:
                continue
            first = first or r.get('recorded_utc_time')
            p = {int(k): v['position_m'] for k, v in seg.items()}
            for k, (a, b) in LINKS.items():
                vals[k].append(dist(p[a], p[b]))
    out = {}
    for k, v in vals.items():
        if v:
            q = statistics.quantiles(v, n=4) if len(v) > 3 else [v[0]] * 3
            out[k] = statistics.median(v)
            out[k + '_iqr'] = q[2] - q[0]
    out['n'] = len(vals['thigh_r'])
    out['first_utc'] = first
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--captures', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    selected = {t['session_id'] for t in json.load(open(ROOT / 'data/analysis/stop-episodes/trials.json'))['trials']}
    rows = []
    for f in sorted(a.captures.glob('*.jsonl')):
        if f.name.endswith('.events.jsonl') or f.stat().st_size < 100_000:
            continue
        sid = f.stem
        m = measure(f)
        if not m['n']:
            continue
        man = f.with_suffix('.manifest.json')
        meta = json.load(open(man)) if man.exists() else {}
        rows.append({'session_id': sid, 'code': sid.split('-')[0], 'trial': sid.split('-')[1],
                     'collection_mode': meta.get('collection_mode'), 'controller': meta.get('controller_condition'),
                     'selected': sid in selected, **m})
        print(sid, m['n'], round(m.get('thigh_r', 0), 4), round(m.get('upper_arm_r', 0), 4), flush=True)
    keys = list(rows[0].keys())
    for r in rows:
        keys += [k for k in r if k not in keys]
    with open(a.out / 'body-model-per-capture.csv', 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=keys); w.writeheader(); w.writerows(rows)


if __name__ == '__main__':
    main()
