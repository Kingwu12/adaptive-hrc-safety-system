"""Reaction-chain latency and per-person phase recognition, from the raw captures.

Latency: per sample, the age of the newest Xsens and OptiTrack data when the
control tick ran, the Xsens/OptiTrack skew, and the tick interval. Combined with
the measured stop-request-to-standstill time (analyse_counterfactual.py) this
gives the measurable part of the reaction chain, to compare with T = 0.4 s.
Device-internal latency upstream of the stream (MVN and Motive processing) is not
observable in these logs and is reported as such.

Phase recognition: the deployed HMM's state (applied decision in predictive
trials; shadow predictive decision in every v2 trial) against the planned-cue
phase labels, per person. Labels mark planned cue windows, not observed onsets,
so agreement is a lower bound on recognition quality.
Only aggregate values are written.
"""
import argparse, json, statistics
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATES = ['approaching', 'working', 'retreating']
MERGE = {'P39': 'P39/P42', 'P42': 'P39/P42'}
V2 = {'P31', 'P32', 'P34', 'P35', 'P38', 'P39/P42'}


def q(v, p):
    v = sorted(v)
    return v[min(len(v) - 1, int(p * (len(v) - 1)))] if v else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--captures', type=Path, required=True)
    ap.add_argument('--out', type=Path, default=ROOT / 'data/analysis/publication/latency-and-phase.json')
    a = ap.parse_args()
    sel = [t['session_id'] for t in json.load(open(ROOT / 'data/analysis/stop-episodes/trials.json'))['trials']]
    for code in MERGE:
        sel += [p.stem for p in sorted(a.captures.glob(f'{code}-T*.jsonl'))
                if not p.name.endswith('.events.jsonl') and p.stat().st_size > 100_000]
    lat = defaultdict(list)
    conf = defaultdict(Counter)
    for sid in sel:
        code = MERGE.get(sid.split('-')[0], sid.split('-')[0])
        prev = None
        for line in open(a.captures / f'{sid}.jsonl'):
            r = json.loads(line)
            t = r.get('recorded_monotonic_s')
            if prev is not None and t is not None and 0 < t - prev <= 0.25:
                lat[('tick', code in V2)].append(t - prev)
            prev = t
            if r.get('xsens_age_s') is not None:
                lat['xsens_age'].append(r['xsens_age_s'])
            rb = (r.get('optitrack_rigid_bodies') or {}).get('1') or {}
            if rb.get('age_s') is not None:
                lat['optitrack_age'].append(rb['age_s'])
            skew = (r.get('body_tracking') or {}).get('source_skew_s')
            if skew is not None:
                lat['xsens_optitrack_skew'].append(skew)
            gt = r.get('ground_truth_phase')
            if gt not in STATES:
                continue
            dec = r.get('controller_decision') or {}
            inferred = dec.get('inferred_state') if r.get('controller_condition') == 'predictive SSM' else None
            if inferred not in STATES:
                inferred = ((r.get('controller_comparison') or {}).get('predictive SSM') or {}).get('inferred_state')
            if inferred in STATES:
                conf[code][(gt, inferred)] += 1

    rep = {'latency_s': {}}
    for k, v in lat.items():
        name = k if isinstance(k, str) else f"tick_interval_{'v2' if k[1] else 'v1'}"
        rep['latency_s'][name] = {'n': len(v), 'median': statistics.median(v), 'p95': q(v, .95), 'p99': q(v, .99), 'max': max(v)}
    per = {}
    for code, c in sorted(conf.items()):
        n = sum(c.values())
        acc = sum(c[(s, s)] for s in STATES) / n
        recalls = [c[(s, s)] / sum(c[(s, x)] for x in STATES) for s in STATES if sum(c[(s, x)] for x in STATES)]
        per[code] = {'labelled_samples': n, 'accuracy': acc, 'balanced_accuracy': statistics.mean(recalls),
                     'version': 'v2' if code in V2 else 'v1'}
    rep['phase_per_person'] = per
    for ver in ('v1', 'v2', None):
        rows = [v for v in per.values() if ver is None or v['version'] == ver]
        rep[f"phase_summary_{ver or 'all'}"] = {'people': len(rows),
                                                'accuracy_median': statistics.median(r['accuracy'] for r in rows),
                                                'accuracy_range': [min(r['accuracy'] for r in rows), max(r['accuracy'] for r in rows)],
                                                'balanced_median': statistics.median(r['balanced_accuracy'] for r in rows),
                                                'balanced_range': [min(r['balanced_accuracy'] for r in rows), max(r['balanced_accuracy'] for r in rows)]}
    total = Counter()
    for c in conf.values():
        total.update(c)
    rep['phase_confusion_all'] = {f'{g}->{p}': total[(g, p)] for g in STATES for p in STATES}
    a.out.write_text(json.dumps(rep, indent=1))
    print(json.dumps({k: v for k, v in rep.items() if k != 'phase_per_person'}, indent=1))
    for k, v in per.items():
        print(k, v['version'], v['labelled_samples'], round(v['accuracy'], 3), round(v['balanced_accuracy'], 3))


if __name__ == '__main__':
    main()
