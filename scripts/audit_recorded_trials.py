#!/usr/bin/env python3
"""Audit recorded evidence without changing, selecting or relabelling any trial.

Motion thresholds below are diagnostic settings, not validated safety limits.
Event labels identify cued windows; they do not establish observed event onset.
"""
import argparse
import collections
import json
import math
import statistics
from pathlib import Path


def audit_trial(path: Path, red_boundary_m: float = .94, closing_gate_m_s: float = .6) -> dict:
    counts = collections.Counter()
    reasons = collections.Counter()
    conditions = collections.Counter()
    minimum_d = math.inf
    previous = None
    durations = collections.Counter()
    first = None
    last = None
    event_min_d = math.inf
    event_max_closing = -math.inf
    event_max_joint_speed = 0.0
    geometry_errors = []
    identity_names = {'static':'fixed zone', 'fixed_zone':'fixed zone',
                      'dynamic_ssm':'reactive SSM', 'adaptive':'predictive SSM'}
    for line in path.open(encoding='utf-8-sig'):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            counts['invalid_json'] += 1
            previous = None
            continue
        if first is None:
            first = row
        last = row
        counts['samples'] += 1
        decision = row.get('controller_decision') or {}
        if decision.get('condition'):
            counts['controller_identity_samples'] += 1
            if decision['condition'] not in identity_names or identity_names[decision['condition']] != row.get('controller_condition'):
                counts['controller_identity_mismatch'] += 1
        telemetry = row.get('robot_telemetry') or {}
        qd = telemetry.get('actual_qd')
        valid_qd = (isinstance(qd, list) and len(qd) == 6
                    and all(isinstance(v, (int,float)) and math.isfinite(v) for v in qd))
        age = telemetry.get('source_age_s')
        fresh = (telemetry.get('available') is True and valid_qd
                 and isinstance(age, (int,float)) and 0 <= age <= .25)
        moving = fresh and max(map(abs, qd)) > .005
        event = row.get('ground_truth_event') in ('hazard','distractor')
        flags = {'tracking_stale': row.get('stale') is True,
                 'telemetry_unusable': not fresh, 'measured_motion': moving,
                 'event_window': event, 'event_during_motion': event and moving,
                 'stop_requested': decision.get('speed_fraction') == 0,
                 'output_not_applied': bool(decision) and decision.get('output_applied') is not True}
        for name, flag in flags.items():
            counts[name] += int(flag)
        if decision:
            conditions[str(decision.get('condition'))] += 1
            reasons[str(decision.get('rule'))] += 1
        f = row.get('features') or {}
        d = f.get('d')
        v = f.get('v_proj')
        if isinstance(d,(int,float)) and math.isfinite(d):
            minimum_d = min(minimum_d,d)
            if event: event_min_d = min(event_min_d,d)
            position, pose = row.get('position'), telemetry.get('actual_tcp_pose')
            if (isinstance(position,list) and len(position) == 3
                    and isinstance(pose,list) and len(pose) == 6
                    and all(isinstance(x,(int,float)) and math.isfinite(x) for x in position+pose)
                    and telemetry.get('available') is True
                    and isinstance(age,(int,float)) and 0 <= age <= .25):
                # Recompute the existing column proxy from same-row inputs.
                # This is not independently measured physical clearance.
                nearest = (pose[0],pose[1],min(max(position[2],0),pose[2]))
                recomputed = math.dist(position,nearest)
                geometry_errors.append(abs(d-recomputed))
        if (row.get('geometry_reference') or {}).get('source') != 'live_rtde_tcp':
            counts['live_geometry_contract_missing'] += 1
        if event and isinstance(v,(int,float)) and math.isfinite(v):
            event_max_closing = max(event_max_closing,v)
        if event and fresh: event_max_joint_speed = max(event_max_joint_speed,max(map(abs,qd)))
        t = row.get('recorded_monotonic_s')
        if isinstance(t,(int,float)) and math.isfinite(t):
            if previous is not None:
                dt = t-previous[0]
                if 0 < dt <= .25:
                    durations['observed_s'] += dt
                    for name, flag in previous[1].items():
                        if flag: durations[name+'_s'] += dt
                else: counts['clock_or_sample_gap'] += 1
            previous = (t,flags)
        else:
            previous = None
    manifest_path = path.with_suffix('.manifest.json')
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    blockers = []
    if manifest.get('outcome') != 'completed': blockers.append('completion not evidenced')
    if not manifest.get('study_release'): blockers.append('per-trial code/config fingerprint not recorded')
    if ((first or {}).get('capture_mode') != 'automatic_streams'
            and (last or {}).get('sync_marker_count',0) < 1):
        blockers.append('recording clock alignment requires review; no shared marker or automatic-stream capture contract')
    if counts['measured_motion'] == 0: blockers.append('no fresh measured robot-motion samples')
    if (first or {}).get('planned_event') in ('rapid intrusion','distractor') and counts['event_during_motion'] == 0:
        blockers.append('no overlap between the cued event window and fresh measured robot motion')
    if counts['invalid_json']: blockers.append('invalid JSON rows')
    if counts['controller_identity_mismatch']:
        blockers.append('recorded decision controller differs from assigned controller')
    if counts['controller_identity_samples'] == 0:
        blockers.append('no identified controller decisions recorded')
    if geometry_errors and max(geometry_errors) > .01:
        blockers.append('stored distance differs by more than 1 cm from same-row live TCP column recomputation; geometry review required')
    if counts['live_geometry_contract_missing']:
        blockers.append('live geometry reference was not explicitly recorded on every sample')
    if (first or {}).get('planned_event') == 'rapid intrusion' and event_max_closing < closing_gate_m_s:
        blockers.append(f'labelled rapid-intrusion window never reached the audit closing gate ({closing_gate_m_s:g} m/s); independently review exposure')
    if (first or {}).get('planned_event') == 'distractor' and event_min_d <= red_boundary_m:
        blockers.append(f'labelled distractor window entered the audit red boundary ({red_boundary_m:g} m); independently review exposure')
    # References and confirmations are not file-existence or synchronisation proof.
    blockers.append('cue labels alone do not independently verify event onset; assess timing and exposure evidence for the planned outcome measures')
    return {'session_id': (first or {}).get('session_id',path.stem),
            'participant_id': (first or {}).get('participant_id'),
            'block': (first or {}).get('block_label'),
            'controller': (first or {}).get('controller_condition'),
            'planned_event': (first or {}).get('planned_event'),
            'execution_mode': (first or {}).get('execution_mode'),
            'capture_mode': (first or {}).get('capture_mode'),
            'capture_grade': manifest.get('catalog_summary',{}).get('quality',{}).get('grade'),
            'counts': dict(counts), 'durations': {k:round(v,3) for k,v in durations.items()},
            'decision_conditions': dict(conditions), 'top_rules': reasons.most_common(5),
            'minimum_proxy_distance_m': minimum_d if math.isfinite(minimum_d) else None,
            'event_minimum_proxy_distance_m': event_min_d if math.isfinite(event_min_d) else None,
            'event_maximum_closing_m_s': event_max_closing if math.isfinite(event_max_closing) else None,
            'event_maximum_joint_speed_rad_s': event_max_joint_speed,
            'geometry_recomputation': {
                'basis':'Same-row recorded head position and fresh robot TCP; discrepancy diagnostic, not independent physical clearance',
                'samples':len(geometry_errors),
                'median_absolute_distance_error_m':statistics.median(geometry_errors) if geometry_errors else None,
                'maximum_absolute_distance_error_m':max(geometry_errors) if geometry_errors else None,
            },
            'final_data_status': 'review_required', 'unresolved_evidence': blockers}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--red-boundary-m',type=float,default=.94,help='Diagnostic threshold; default matches the Sep 9 configuration')
    parser.add_argument('--closing-gate-m-s',type=float,default=.6,help='Diagnostic threshold; default matches the Sep 9 configuration')
    args=parser.parse_args()
    if not all(math.isfinite(v) and v > 0 for v in (args.red_boundary_m,args.closing_gate_m_s)):
        parser.error('Diagnostic thresholds must be finite and positive')
    files=sorted(p for p in args.directory.glob('*.jsonl') if not p.name.endswith('.events.jsonl'))
    if not files: parser.error('No sample JSONL files found')
    result={'scope':'Only sample files present in the supplied directory; no inference about missing trials.',
            'motion_diagnostic':{'joint_speed_threshold_rad_s':.005,'max_telemetry_age_s':.25},
            'event_diagnostic':{'red_boundary_m':args.red_boundary_m,'closing_gate_m_s':args.closing_gate_m_s},
            'trials':[audit_trial(p,args.red_boundary_m,args.closing_gate_m_s) for p in files]}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(f'Audited {len(files)} trials: {args.output}')


if __name__=='__main__': main()
