"""Aggregate the counterfactual replay into person-level, paper-ready summaries.

Unit of inference is the study code (one sitting per person). Trial-level
quantities are summed within a code and normalised by that code's observed
time, so a person with more trials does not weigh more. Paired contrasts use
the Wilcoxon signed-rank test across codes and a percentile bootstrap over codes.
Only aggregate values are written, so the output may live in the repository.
"""
import argparse, json, random, statistics
from collections import defaultdict
from pathlib import Path

from scipy.stats import wilcoxon

ROOT = Path(__file__).resolve().parents[1]
MAIN = ['fixed zone', 'reactive SSM', 'predictive SSM']
H = '1.0'


def per_code(trials, codes):
    agg = defaultdict(lambda: defaultdict(float))
    for tr in trials:
        if tr['code'] not in codes:
            continue
        a = agg[tr['code']]
        a['observed_s'] += tr['observed_s']; a['entries'] += tr['entries']
        for name, m in tr['controllers'].items():
            a[(name, 'stop')] += m['stop_s_excl_shared_hold']
            a[(name, 'onsets')] += m['onsets']
            a[(name, 'brief')] += m['brief_segments']
            for h in ('0.5', '1.0', '2.0'):
                a[(name, 'unnec', h)] += m[f'unnecessary_s_H{h}']
                a[(name, 'nec', h)] += m[f'necessary_s_H{h}']
            a[(name, 'run_inside')] += m['run_inside_S0_s']
            a[(name, 'run_below_sp')] += m['run_below_dynamic_Sp_s']
            covered = [x for x in m['entry_leads_s'] if x >= 0]
            a[(name, 'covered')] += len(covered)
            a[(name, 'lead_sum')] += sum(covered)
    return agg


def rate(a, key):
    return 60.0 * a[key] / a['observed_s']


def boot(diff, n=10000, seed=7):
    rnd = random.Random(seed)
    means = sorted(statistics.mean(rnd.choices(diff, k=len(diff))) for _ in range(n))
    return means[int(.025 * n)], means[int(.975 * n)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--inp', type=Path, required=True)
    ap.add_argument('--out', type=Path, default=ROOT / 'data/analysis/publication')
    ap.add_argument('--codes', nargs='*', default=None, help='restrict to these study codes')
    ap.add_argument('--name', default='counterfactual-summary')
    ap.add_argument('--merge', nargs='*', default=[], metavar='CODE=PERSON',
                    help='count these study codes as one person, e.g. P39=P39/P42 P42=P39/P42; '
                         'merged codes are included even if absent from the 97-trial selection')
    a = ap.parse_args()
    trials = json.loads(a.inp.read_text())
    a.out.mkdir(parents=True, exist_ok=True)
    selected = {t['session_id'] for t in json.load(open(ROOT / 'data/analysis/stop-episodes/trials.json'))['trials']}
    merge = dict(m.split('=', 1) for m in a.merge)
    main_trials = []
    for t in trials:
        if t['session_id'] not in selected and t['code'] not in merge:
            continue
        t = dict(t, code=merge.get(t['code'], t['code']))
        if not a.codes or t['code'] in a.codes:
            main_trials.append(t)
    codes = sorted({t['code'] for t in main_trials})
    agg = per_code(main_trials, set(codes))
    names = list(main_trials[0]['controllers'])

    fid = [v[0] for t in main_trials for v in t['fidelity'].values() if v[0] is not None]
    report = {'trials': len(main_trials), 'codes': codes, 'merged_codes': merge,
              'applied_trials_by_person': {c: dict(sorted({x['applied']: sum(1 for y in main_trials if y['code'] == c and y['applied'] == x['applied'])
                                                           for x in main_trials if x['code'] == c}.items())) for c in codes}, 'fidelity_min': min(fid),
              'fidelity_mean': statistics.mean(fid),
              'fidelity_exact_trials': sum(all(v[0] in (None, 1.0) for v in t['fidelity'].values()) for t in main_trials),
              'observed_min': sum(t['observed_s'] for t in main_trials) / 60, 'entries': sum(t['entries'] for t in main_trials)}

    table = {}
    for n in names:
        row = {}
        per = [agg[c] for c in codes]
        for key, label in [((n, 'stop'), 'stop_s_per_min'), ((n, 'onsets'), 'onsets_per_min'),
                           ((n, 'brief'), 'brief_per_min'), ((n, 'unnec', H), 'unnecessary_s_per_min'),
                           ((n, 'nec', H), 'necessary_s_per_min')]:
            vals = [rate(x, key) for x in per]
            row[label] = {'median': statistics.median(vals), 'mean': statistics.mean(vals)}
        tot_entries = sum(x['entries'] for x in per)
        covered = sum(x[(n, 'covered')] for x in per)
        row['entries_covered_pct'] = 100 * covered / tot_entries if tot_entries else None
        row['mean_lead_s'] = sum(x[(n, 'lead_sum')] for x in per) / covered if covered else None
        row['run_inside_S0_s'] = sum(x[(n, 'run_inside')] for x in per)
        row['run_below_dynamic_Sp_s'] = sum(x[(n, 'run_below_sp')] for x in per)
        row['unnecessary_share_pct'] = 100 * sum(x[(n, 'unnec', H)] for x in per) / max(1e-9, sum(x[(n, 'unnec', H)] + x[(n, 'nec', H)] for x in per))
        table[n] = row
    report['open_loop'] = table

    contrasts = {}
    for metric, key in [('unnecessary_s_per_min', 'unnec'), ('stop_s_per_min', 'stop'), ('brief_per_min', 'brief')]:
        for x, y in [('predictive SSM', 'fixed zone'), ('reactive SSM', 'fixed zone'), ('predictive SSM', 'reactive SSM'),
                     ('predictive dwell6', 'predictive SSM'), ('predictive dwell6', 'fixed zone'), ('predictive dwell6', 'reactive SSM'),
                     ('predictive trunk-intent dwell2', 'predictive SSM'), ('predictive trunk-intent dwell2', 'fixed zone'),
                     ('predictive trunk-intent dwell2', 'reactive SSM')]:
            kx = (x, key, H) if key == 'unnec' else (x, key)
            ky = (y, key, H) if key == 'unnec' else (y, key)
            diff = [rate(agg[c], kx) - rate(agg[c], ky) for c in codes]
            p = wilcoxon(diff).pvalue if any(diff) else 1.0
            lo, hi = boot(diff)
            contrasts[f'{metric}: {x} - {y}'] = {'mean_diff': statistics.mean(diff), 'ci95': [lo, hi], 'wilcoxon_p': p,
                                                 'n_codes': len(diff), 'codes_lower': sum(d < 0 for d in diff)}
    for x, y in [('predictive SSM', 'fixed zone'), ('predictive SSM', 'reactive SSM'), ('reactive SSM', 'fixed zone'),
                 ('predictive trunk-intent dwell2', 'fixed zone'), ('predictive trunk-intent dwell2', 'reactive SSM'),
                 ('predictive trunk-intent dwell2', 'predictive SSM')]:
        diff = [agg[c][(x, 'lead_sum')] / max(1, agg[c][(x, 'covered')]) - agg[c][(y, 'lead_sum')] / max(1, agg[c][(y, 'covered')])
                for c in codes if agg[c]['entries']]
        lo, hi = boot(diff)
        contrasts[f'mean_lead_s: {x} - {y}'] = {'mean_diff': statistics.mean(diff), 'ci95': [lo, hi],
                                                'wilcoxon_p': wilcoxon(diff).pvalue if any(diff) else 1.0,
                                                'n_codes': len(diff), 'codes_lower': sum(d < 0 for d in diff)}
    report['paired_contrasts'] = contrasts

    lat = defaultdict(list)
    moving_min, inside_moving = [], 0.0
    for t in main_trials:
        cl = t['closed_loop']
        for r in cl['response']:
            lat[t['applied']].append(r['latency_s']); lat['all'].append(r['latency_s'])
        if cl['min_d_while_moving'] is not None:
            moving_min.append(cl['min_d_while_moving'])
        inside_moving += cl['inside_S0_while_moving_s']
    q = lambda v, p: sorted(v)[min(len(v) - 1, int(p * len(v)))]
    report['closed_loop'] = {
        'response_latency_s': {k: {'n': len(v), 'median': statistics.median(v), 'p95': q(v, .95), 'max': max(v)}
                               for k, v in lat.items() if v},
        'min_separation_while_moving_m': min(moving_min) if moving_min else None,
        'inside_S0_while_moving_s': inside_moving,
        'moving_min': sum(t['closed_loop']['moving_s'] for t in main_trials) / 60,
        'held_arm_pushed_s': sum(t['closed_loop'].get('held_arm_pushed_s', 0) for t in main_trials),
        'held_arm_pushed_inside_S0_s': sum(t['closed_loop'].get('held_arm_pushed_inside_S0_s', 0) for t in main_trials),
        'people_who_pushed_held_arm': sorted({t['code'] for t in main_trials if t['closed_loop'].get('held_arm_pushed_inside_S0_s', 0) > 0}),
    }
    (a.out / f'{a.name}.json').write_text(json.dumps(report, indent=1, default=str))
    print(json.dumps(report, indent=1, default=str)[:6000])


if __name__ == '__main__':
    main()
