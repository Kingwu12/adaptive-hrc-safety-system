"""Questionnaire ratings linked to controller and to measured robot behaviour.

Inputs (private, outside the public repository): the three Google Forms exports
re-keyed as pipe-separated files, and the counterfactual per-trial JSON. Each
after-block rating is linked to the controller that ran in that block (from the
trial manifests) and to what that controller actually did in that block's trials
(stop time, brief stops, unnecessary stop time per minute).

Analyses, person as the unit:
  1. Ratings by controller: Friedman over people with all three blocks, and
     paired Wilcoxon for each pair over people with both blocks.
  2. End-of-session choices (felt safest, least safe, pick for a shift) against
     chance (1/3 per controller), exact binomial.
  3. Perception vs measurement: within-person (repeated-measures) correlation
     between "slowed or stopped more than it needed to" and measured stopping
     in the same block, plus the same for "had to watch it constantly".
  4. Block position (first, second, third) effects, to separate controller from
     order (habituation).
Only aggregate values are written, so the output may live in the repository.
"""
import argparse, csv, json, math, statistics
from collections import defaultdict
from pathlib import Path

from scipy.stats import binomtest, friedmanchisquare, pearsonr, wilcoxon

ROOT = Path(__file__).resolve().parents[1]
CTRL = ['fixed zone', 'reactive SSM', 'predictive SSM']
ITEMS = ['anxious_relaxed', 'agitated_calm', 'quiescent_surprised', 'confident_stop', 'watch_constantly',
         'slowed_more_than_needed', 'speed_changes_made_sense', 'mental', 'physical', 'frustration']


def read_psv(p):
    return list(csv.DictReader(open(p), delimiter='|'))


def rm_corr(pairs_by_person):
    """Repeated-measures correlation: centre x and y within each person, then correlate."""
    xs, ys, n_people = [], [], 0
    for pts in pairs_by_person.values():
        if len(pts) < 2:
            continue
        n_people += 1
        mx = statistics.mean(p[0] for p in pts); my = statistics.mean(p[1] for p in pts)
        xs += [p[0] - mx for p in pts]; ys += [p[1] - my for p in pts]
    if len(xs) < 3 or not any(xs) or not any(ys):
        return None
    r, _ = pearsonr(xs, ys)
    dof = len(xs) - n_people - 1
    t = r * math.sqrt(dof / max(1e-12, 1 - r * r))
    from scipy.stats import t as tdist
    return {'r_rm': r, 'dof': dof, 'p': 2 * tdist.sf(abs(t), dof), 'people': n_people, 'blocks': len(xs)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--qdir', type=Path, required=True)
    ap.add_argument('--trials', type=Path, required=True)
    ap.add_argument('--out', type=Path, default=ROOT / 'data/analysis/publication/questionnaire-links.json')
    a = ap.parse_args()
    after = read_psv(a.qdir / 'after-block.psv')
    end = read_psv(a.qdir / 'end-of-session.psv')
    trials = json.loads(a.trials.read_text())

    block_ctrl, measured = {}, defaultdict(lambda: defaultdict(float))
    for t in trials:
        key = (t['code'], t['block'])
        block_ctrl[key] = t['applied']
        m = t['controllers'][t['applied']]
        acc = measured[key]
        acc['observed_s'] += t['observed_s']
        acc['stop_s'] += m['stop_s_excl_shared_hold']
        acc['brief'] += m['brief_segments']
        acc['unnec'] += m['unnecessary_s_H1.0']
    rate = lambda k, f: 60 * measured[k][f] / measured[k]['observed_s']

    rows = []
    for r in after:
        key = (r['id'], r['block'])
        if key not in block_ctrl:
            continue
        rows.append({**r, 'controller': block_ctrl[key], 'position': 'ABC'.index(r['block']),
                     **{i: float(r[i]) for i in ITEMS},
                     'm_stop': rate(key, 'stop_s'), 'm_brief': rate(key, 'brief'), 'm_unnec': rate(key, 'unnec')})
    people = sorted({r['id'] for r in rows})
    by = {(r['id'], r['controller']): r for r in rows}
    rep = {'people_with_block_ratings': len(people), 'block_ratings': len(rows),
           'people_with_all_three_blocks': sum(all((p, c) in by for c in CTRL) for p in people), 'items': {}}

    for item in ITEMS:
        res = {'median_by_controller': {c: statistics.median([by[(p, c)][item] for p in people if (p, c) in by]) for c in CTRL},
               'mean_by_controller': {c: statistics.mean([by[(p, c)][item] for p in people if (p, c) in by]) for c in CTRL}}
        full = [p for p in people if all((p, c) in by for c in CTRL)]
        vals = [[by[(p, c)][item] for p in full] for c in CTRL]
        try:
            res['friedman_p'] = friedmanchisquare(*vals).pvalue
        except ValueError:
            res['friedman_p'] = None
        res['friedman_n'] = len(full)
        pair = {}
        for x, y in [('predictive SSM', 'fixed zone'), ('predictive SSM', 'reactive SSM'), ('reactive SSM', 'fixed zone')]:
            both = [p for p in people if (p, x) in by and (p, y) in by]
            d = [by[(p, x)][item] - by[(p, y)][item] for p in both]
            pair[f'{x} - {y}'] = {'n': len(both), 'mean_diff': statistics.mean(d),
                                  'higher': sum(v > 0 for v in d), 'lower': sum(v < 0 for v in d),
                                  'wilcoxon_p': wilcoxon(d).pvalue if any(d) else 1.0}
        res['paired'] = pair
        rep['items'][item] = res

    # Perception vs measurement, within person.
    links = {}
    for item in ['slowed_more_than_needed', 'watch_constantly', 'frustration', 'confident_stop']:
        for meas in ['m_unnec', 'm_brief', 'm_stop']:
            g = defaultdict(list)
            for r in rows:
                g[r['id']].append((r[meas], r[item]))
            links[f'{item} ~ {meas}'] = rm_corr(g)
    rep['perception_vs_measurement'] = links

    # Order effects.
    full_pos = [p for p in people if all(any(r['id'] == p and r['position'] == k for r in rows) for k in range(3))]
    pos = {}
    for item in ITEMS:
        vals = [[next(r[item] for r in rows if r['id'] == p and r['position'] == k) for p in full_pos] for k in range(3)]
        try:
            pos[item] = {'means_first_second_third': [statistics.mean(v) for v in vals], 'friedman_p': friedmanchisquare(*vals).pvalue}
        except ValueError:
            pos[item] = None
    rep['block_position'] = pos

    # End-of-session choices mapped to controllers.
    choices = {}
    for field in ['felt_safest', 'felt_least_safe', 'pick_for_shift']:
        counts = defaultdict(int)
        for e in end:
            c = block_ctrl.get((e['id'], e[field]))
            if c:
                counts[c] += 1
        n = sum(counts.values())
        choices[field] = {c: {'count': counts[c], 'binom_p_vs_third': binomtest(counts[c], n, 1 / 3).pvalue} for c in CTRL}
        choices[field]['n'] = n
    rep['end_of_session_choices'] = choices
    rep['end_overall'] = {k: statistics.median(float(e[k]) for e in end) for k in ['felt_safe_overall', 'trust_overall', 'suit_restricted']}
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(rep, indent=1, default=str))
    print(json.dumps(rep, indent=1, default=str)[:9000])


if __name__ == '__main__':
    main()
