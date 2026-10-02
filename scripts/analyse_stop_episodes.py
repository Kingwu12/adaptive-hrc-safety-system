"""Stop-episode analysis for the 97 selected participant-study trials.

Separates sustained stop requests from brief stop/run switching ("chatter").
Read-only on raw captures. Every rule is applied identically to all three
controllers, and results are reported across a grid of thresholds so that no
single cut-off drives the conclusion.

Definitions (command = controller_decision.speed_fraction, left-held over
positive sample intervals <= 0.25 s, as in analyse_recovered.py):
  stop segment   maximal run of consecutive samples with command == 0
  raw onset      nonzero -> zero transition across an interval <= 0.25 s
                 (identical to command_stop_onsets in the 27 Sep analysis)
  stop episode   stop segments joined when the run between them is shorter
                 than the merge gap G; an interval > 0.25 s always splits
  sustained      episode whose stopped time is >= D seconds
Shadow commands (controller_comparison) give every controller's request on the
same recorded inputs. They are open-loop: they show each policy's switching on
identical inputs, not what the robot or person would have done under it.
"""
import argparse, csv, json, math, statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTROLLERS = ['fixed zone', 'reactive SSM', 'predictive SSM']
MAX_DT = .25
SHORT_S = .5
GAPS = [.25, .5, 1.0]
DWELLS = [0.0, .5, 1.0]
HOLDS = [.5, 1.0]


def num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def runs(t, s):
    """Consecutive samples with the same state. Each run keeps its left-held
    duration and whether the interval after its last sample is a gap."""
    out, cur = [], None
    for i, x in enumerate(s):
        ok = i + 1 < len(s) and 0 < t[i + 1] - t[i] <= MAX_DT
        dt = t[i + 1] - t[i] if ok else 0.0
        state = None if x is None else x == 0
        if cur and cur['stop'] == state and not cur['broken']:
            cur['dur'] += dt; cur['broken'] = not ok
        else:
            if cur: out.append(cur)
            cur = {'stop': state, 'dur': dt, 'broken': not ok}
    if cur: out.append(cur)
    return out


def episodes(rs, gap):
    """Stopped time of each episode after joining stops split by runs < gap."""
    eps, cur, joinable = [], None, False
    for r in rs:
        if r['stop']:
            if cur is not None and joinable:
                cur += r['dur']
            else:
                if cur is not None: eps.append(cur)
                cur = r['dur']
            joinable = not r['broken']
        elif cur is not None:
            if r['stop'] is None or r['broken'] or r['dur'] >= gap:
                eps.append(cur); cur = None; joinable = False
    if cur is not None: eps.append(cur)
    return eps


def stats(t, s):
    s = [x if num(x) else None for x in s]
    rs = runs(t, s)
    onsets = sum(1 for i in range(1, len(s)) if s[i] == 0 and s[i - 1] not in (0, None) and 0 < t[i] - t[i - 1] <= MAX_DT)
    observed = sum(t[i + 1] - t[i] for i in range(len(t) - 1) if 0 < t[i + 1] - t[i] <= MAX_DT)
    stops = [r for r in rs if r['stop']]
    out = {
        'raw_onsets': onsets,
        'stop_segments': len(stops),
        'short_stop_segments': sum(1 for r in stops if r['dur'] < SHORT_S),
        'stop_s': sum(r['dur'] for r in stops),
        'observed_s': observed,
    }
    for g in GAPS:
        eps = episodes(rs, g)
        for d in DWELLS:
            out[f'episodes_gap{g}_min{d}'] = sum(1 for e in eps if e >= d)
    return out


def hold(t, s, h):
    """Offline replay of a minimum stop dwell: once zero, stay zero for h s."""
    out, until = [], -1.0
    for ti, x in zip(t, s):
        if not num(x):
            out.append(x); continue
        if x == 0:
            until = max(until, ti + h)
        out.append(0.0 if ti < until else x)
    return out


CAUSES = [('sensing dropout hold', 'Body evidence missing'), ('intrusion predictor', 'Rapid-closing'),
          ('red boundary', 'RED zone breach'), ('envelope minimum', 'final speed=min'), ('tracking unavailable', 'FAIL CLOSED')]


def onset_causes(t, decisions):
    """Classify each applied stop onset by the rule that issued it and by
    whether the stop lasted < SHORT_S (brief) or longer (sustained)."""
    s = [d.get('speed_fraction') for d in decisions]
    out = {f'{c}|{k}': 0 for c, _ in CAUSES + [('other', '')] for k in ('brief', 'sustained')}
    i = 1
    while i < len(s):
        if s[i] == 0 and s[i - 1] not in (0, None) and 0 < t[i] - t[i - 1] <= MAX_DT:
            j, dur = i, 0.0
            while j + 1 < len(s) and s[j + 1] == 0 and 0 < t[j + 1] - t[j] <= MAX_DT:
                dur += t[j + 1] - t[j]; j += 1
            if j + 1 < len(s) and 0 < t[j + 1] - t[j] <= MAX_DT:
                dur += t[j + 1] - t[j]
            rule = decisions[i].get('rule') or ''
            cause = next((c for c, marker in CAUSES if marker in rule), 'other')
            out[f"{cause}|{'brief' if dur < SHORT_S else 'sustained'}"] += 1
            i = j + 1
        else:
            i += 1
    return out


def find(source, sid):
    hits = list(source.rglob(f'*{sid}*.manifest.json'))
    if len(hits) != 1:
        raise SystemExit(f'{sid}: expected one manifest, found {len(hits)}')
    m = hits[0]
    return m, Path(str(m).replace('.manifest.json', '.jsonl'))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--source-root', type=Path, required=True)
    ap.add_argument('--selected', type=Path, required=True)
    ap.add_argument('--out', type=Path, default=ROOT / 'data/analysis/stop-episodes')
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    selected = list(csv.DictReader(a.selected.open()))
    trials = []
    for item in selected:
        sid = item['session_id']
        manifest, raw = find(a.source_root, sid)
        rows = [json.loads(l) for l in raw.open() if l.strip()]
        assert len(rows) == int(item['samples']) == json.loads(manifest.read_text())['samples'], sid
        t = [r['recorded_monotonic_s'] for r in rows]
        applied = [(r.get('controller_decision') or {}).get('speed_fraction') for r in rows]
        rec = {k: item[k] for k in ['session_id', 'participant_id', 'trial_id', 'controller_condition', 'planned_event', 'capture_mode']}
        rec['applied'] = stats(t, applied)
        rec['applied_causes'] = onset_causes(t, [r.get('controller_decision') or {} for r in rows])
        assert sum(rec['applied_causes'].values()) == rec['applied']['raw_onsets'], sid
        assert rec['applied']['raw_onsets'] == int(item['command_stop_onsets']), (sid, rec['applied']['raw_onsets'], item['command_stop_onsets'])
        rec['applied_hold'] = {str(h): stats(t, hold(t, applied, h)) for h in HOLDS}
        shadow = {c: [((r.get('controller_comparison') or {}).get(c) or {}).get('speed_fraction') for r in rows] for c in CONTROLLERS}
        rec['shadow_coverage'] = sum(1 for r in rows if r.get('controller_comparison')) / len(rows)
        if rec['shadow_coverage'] > .95:
            rec['shadow'] = {c: stats(t, v) for c, v in shadow.items()}
            rec['shadow_hold'] = {str(h): stats(t, hold(t, shadow['predictive SSM'], h)) for h in HOLDS}
        trials.append(rec)
        print(sid, item['controller_condition'], rec['applied']['raw_onsets'], rec['applied']['short_stop_segments'], f"{rec['shadow_coverage']:.2f}")
    json.dump({'definitions': __doc__, 'settings': {'max_interval_s': MAX_DT, 'short_stop_s': SHORT_S, 'merge_gaps_s': GAPS,
               'min_stop_s': DWELLS, 'offline_holds_s': HOLDS}, 'trials': trials}, (a.out / 'trials.json').open('w'), indent=1)
    summarise(trials, a.out)


def summarise(trials, out):
    keys = ['raw_onsets', 'short_stop_segments', 'stop_s', 'observed_s'] + [f'episodes_gap{g}_min{d}' for g in GAPS for d in DWELLS]
    lines = []
    def block(title, groups):
        lines.append(f'\n## {title}\n')
        lines.append('| group | trials | ' + ' | '.join(keys) + ' |')
        lines.append('|' + '---|' * (len(keys) + 2))
        for name, recs in groups:
            if not recs: continue
            tot = {k: sum(r[k] for r in recs) for k in keys}
            lines.append(f'| {name} | {len(recs)} | ' + ' | '.join(f'{tot[k]:.1f}' if isinstance(tot[k], float) else str(tot[k]) for k in keys) + ' |')
    by = defaultdict(list)
    for r in trials:
        by[r['controller_condition']].append(r)
    block('Applied command, by recorded controller (closed loop, totals)', [(c, [r['applied'] for r in by[c]]) for c in CONTROLLERS])
    for mode in ['legacy_operator_confirmed', 'automatic_streams']:
        block(f'Applied command, {mode}', [(c, [r['applied'] for r in by[c] if r['capture_mode'] == mode]) for c in CONTROLLERS])
    causes = list(trials[0]['applied_causes'])
    lines.append('\n## Applied stop onsets by issuing rule and duration (brief < %.1f s)\n' % SHORT_S)
    lines.append('| cause | ' + ' | '.join(CONTROLLERS) + ' |')
    lines.append('|---|' + '---|' * len(CONTROLLERS))
    for k in causes:
        row = [sum(r['applied_causes'][k] for r in by[c]) for c in CONTROLLERS]
        if any(row): lines.append(f'| {k} | ' + ' | '.join(map(str, row)) + ' |')
    sh = [r for r in trials if 'shadow' in r]
    block(f'Shadow commands on identical inputs ({len(sh)} trials, open loop)', [(c, [r['shadow'][c] for r in sh]) for c in CONTROLLERS])
    for h in HOLDS:
        block(f'Offline {h}-s minimum stop dwell on applied predictive commands', [('predictive SSM', [r['applied_hold'][str(h)] for r in by['predictive SSM']])])
        if sh:
            block(f'Offline {h}-s minimum stop dwell on shadow predictive commands', [('predictive SSM', [r['shadow_hold'][str(h)] for r in sh])])
    if sh:
        ratios = [r['shadow']['predictive SSM']['raw_onsets'] / r['shadow']['reactive SSM']['raw_onsets'] for r in sh if r['shadow']['reactive SSM']['raw_onsets']]
        lines.append(f'\nPer-trial shadow onset ratio predictive/reactive: median {statistics.median(ratios):.2f} (n={len(ratios)}), '
                     f'IQR {statistics.quantiles(ratios, n=4)[0]:.2f}-{statistics.quantiles(ratios, n=4)[2]:.2f}\n')
    (out / 'summary.md').write_text('# Stop-episode analysis\n' + '\n'.join(lines) + '\n')
    print('\n'.join(lines))


if __name__ == '__main__':
    main()
