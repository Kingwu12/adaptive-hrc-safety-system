"""Independent standard-library cross-checks of published empirical summaries."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import statistics

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--source-root', type=Path, default=ROOT.parent)
source_root = parser.parse_args().source_root.resolve()
results = json.loads((ROOT/'data/analysis/recovered/results.json').read_text())
hashes = json.loads((ROOT/'data/analysis/recovered/source-sha256.json').read_text())
inventory = json.loads((ROOT/'data/recovered-trial-inventory.json').read_text())
by_id = {r['session_id']: r for r in results['trials']}
checks = []
for relative, expected in hashes.items():
    assert hashlib.sha256((source_root/relative).read_bytes()).hexdigest() == expected
checks.append('All 42 complete-set source hashes match the analysis manifest.')
for trial in inventory['trials']:
    if not trial['raw_present']:
        continue
    raw = source_root / trial['manifest_path'].replace('.manifest.json', '.jsonl')
    rows = [json.loads(line) for line in raw.read_text().splitlines() if line.strip()]
    result = by_id[trial['session_id']]
    intervals = [(b['recorded_monotonic_s']-a['recorded_monotonic_s'], a)
                 for a,b in zip(rows,rows[1:])]
    usable = [(dt,r) for dt,r in intervals if 0 < dt <= 0.25]
    seconds = math.fsum(dt for dt,_ in usable)
    zero = math.fsum(dt for dt,r in usable if
                    (r.get('controller_decision') or {}).get('speed_fraction') == 0)
    gap = math.fsum(dt for dt,_ in intervals if dt > 0.25)
    assert len(rows) == result['samples'] == trial['sample_rows']
    assert math.isclose(seconds, result['observed_interval_s'], abs_tol=1e-8)
    assert math.isclose(gap, result['gap_interval_s'], abs_tol=1e-8)
    assert math.isclose(100*zero/seconds, result['stop_command_pct_of_observed_time'], abs_tol=1e-8)
    assert math.isclose(seconds+gap, result['sample_span_s'], abs_tol=1e-8)
    event_speeds=[]
    for row in rows:
        if row.get('ground_truth_event') not in ('hazard','distractor'):
            continue
        telemetry=row.get('robot_telemetry') or {}
        velocities=telemetry.get('actual_qd');age=telemetry.get('source_age_s')
        finite=lambda v:isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)
        if (telemetry.get('available') is True and isinstance(velocities,list)
                and len(velocities)==6 and all(finite(v) for v in velocities)
                and finite(age) and 0<=age<=0.25):
            event_speeds.append(max(abs(v) for v in velocities))
    assert len(event_speeds)==result['event_fresh_telemetry']
    for threshold in (0.001,0.005,0.01):
        assert sum(v>threshold for v in event_speeds)==result['event_motion_samples_threshold_'+str(threshold)]
checks.append('Independent adjacent-row integration matches all 14 trial denominators, gaps and zero-request fractions.')
checks.append('Fresh cue-window telemetry denominators and motion counts at all three thresholds match original rows.')
assert len(by_id) == 14 and sum(r['samples'] for r in by_id.values()) == 65697
source = json.loads((ROOT/'data/questionnaires/responses-2026-09-19.json').read_text())
q = json.loads((ROOT/'data/analysis/questionnaires/results.json').read_text())
assert hashlib.sha256((ROOT/'data/questionnaires/responses-2026-09-19.json').read_bytes()).hexdigest() == q['snapshot_sha256']
included = {name:[r['values'] for r in s['rows'] if re.fullmatch(r'P\d+',str(r['values'][1]))]
            for name,s in source['sheets'].items()}
assert {k:len(v) for k,v in included.items()} == q['included_counts']
a = {r[1]:r for r in included['Intake responses']}
z = {r[1]:r for r in included['End responses']}
assert len(a.keys() & z.keys()) == 11
for key,i,j in [('safety',7,8),('trust',8,9)]:
    changes = [int(z[p][j])-int(a[p][i]) for p in sorted(a.keys() & z.keys())]
    assert math.isclose(statistics.mean(changes),q['pre_post'][key]['mean_change'],abs_tol=1e-12)
    assert sum(v>0 for v in changes) == q['pre_post'][key]['increased']
for index,key in enumerate(q['items']):
    for block in 'ABC':
        values = sorted(int(r[3+index]) for r in included['Block responses'] if r[2]==block)
        s=q['block_summaries'][key][block]
        assert len(values)==s['n'] and statistics.median(values)==s['median']
        for rating in range(1,6):
            assert values.count(rating)==s['counts'][str(rating)]
assert set(q['complete_block_codes']) == {'P13','P14','P16','P17','P31','P32','P34','P35','P38'}
complete_rows={p:{r[2]:r for r in included['Block responses'] if r[1]==p}
               for p in q['complete_block_codes']}
changed=[]
for index,key in enumerate(q['items']):
    diffs=[int(v['C'][index+3])-int(v['A'][index+3]) for v in complete_rows.values()]
    d=q['complete_case_A_to_C_changes'][key]
    assert d=={'n':9,'increased':sum(v>0 for v in diffs),'unchanged':sum(v==0 for v in diffs),
               'decreased':sum(v<0 for v in diffs),'median_change':statistics.median(diffs)}
    for block in 'ABC':
        values=[int(v[block][index+3]) for v in complete_rows.values()]
        median=statistics.median(values)
        assert q['complete_case_block_summaries'][key][block]['median']==median
        for rating in range(1,6):
            assert values.count(rating)==q['complete_case_block_summaries'][key][block]['counts'][str(rating)]
        original=q['block_summaries'][key][block]['median']
        if original!=median:
            changed.append({'item':key,'block':block,'all_available':original,'complete_case':median})
assert q['complete_case_median_sensitivity']=={'comparisons':30,'changed':changed}
checks.append('All complete-case medians, distributions and 90 paired A-to-C item changes independently agree with the original Forms rows.')
checks.append('Raw Forms counts, every block-item median/distribution and matched global changes independently agree.')
out = ROOT/'data/analysis/verification.json'
out.write_text(json.dumps({'passed':True,'checks':checks},indent=2))
print(out.read_text())
