"""Stature proxy from the OptiTrack helmet rigid body (independent of the Xsens profile).

Upper quantiles of helmet height over a trial approximate standing head height,
which differs between people and does not depend on the MVN body profile.
Writes participant-level output outside the public repo (--out).
"""
import argparse, csv, json, statistics
from pathlib import Path

STRIDE = 10


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--captures', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    rows = []
    for f in sorted(a.captures.glob('*.jsonl')):
        if f.name.endswith('.events.jsonl') or f.stat().st_size < 100_000:
            continue
        z, mvn_head = [], []
        with open(f) as fh:
            for i, line in enumerate(fh):
                if i % STRIDE:
                    continue
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                rb = (r.get('optitrack_rigid_bodies') or {}).get('1')
                if rb and rb.get('age_s', 1) < 0.05:
                    z.append(rb['position'][2])
                seg = ((r.get('xsens_frame') or {}).get('segments')) or {}
                if '7' in seg and '18' in seg and '22' in seg:
                    foot = min(seg['18']['position_m'][2], seg['22']['position_m'][2])
                    mvn_head.append(seg['7']['position_m'][2] - foot)
        if len(z) < 50:
            continue
        q = statistics.quantiles(z, n=100)
        row = {'session_id': f.stem, 'code': f.stem.split('-')[0], 'n': len(z),
               'helmet_z_p50': q[49], 'helmet_z_p90': q[89], 'helmet_z_p98': q[97]}
        if len(mvn_head) > 50:
            row['mvn_head_above_foot_p98'] = statistics.quantiles(mvn_head, n=100)[97]
        rows.append(row)
        print(row['session_id'], round(row['helmet_z_p98'], 3), flush=True)
    keys = sorted({k for r in rows for k in r}, key=lambda k: list(rows[0]).index(k) if k in rows[0] else 99)
    with open(a.out / 'helmet-height-per-capture.csv', 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=keys); w.writeheader(); w.writerows(rows)


if __name__ == '__main__':
    main()
