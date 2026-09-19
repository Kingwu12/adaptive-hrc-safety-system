"""Descriptive audit of recovered FYP captures. Never edits raw files.
Run from the task root with the bundled Python runtime.
"""
import sys, json, math, hashlib, csv, argparse
from pathlib import Path
from collections import Counter
from datetime import datetime
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser();parser.add_argument('--source-root',type=Path,default=ROOT.parent)
SOURCE_ROOT=parser.parse_args().source_root.resolve()
OUT=ROOT/'data/analysis/recovered'
OUT.mkdir(parents=True,exist_ok=True)
inv=json.loads((ROOT/'data/recovered-trial-inventory.json').read_text())
def num(x): return isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x)
def pct(a,b): return 100*a/b if b else None
def utc(s): return datetime.fromisoformat(s).timestamp()
def col_distance(p,tcp): return math.dist(p,[tcp[0],tcp[1],min(max(p[2],0),tcp[2])])
def quant(x,q): return float(np.quantile(x,q)) if x else None
metrics=[]; traces={}; sourcehashes={}; confusion={}; detail={}
for item in inv['trials']:
 if not item['raw_present']: continue
 manifest=SOURCE_ROOT/item['manifest_path']
 raw=Path(str(manifest).replace('.manifest.json','.jsonl'))
 events=Path(str(manifest).replace('.manifest.json','.events.jsonl'))
 m=json.loads(manifest.read_text());rows=[json.loads(l) for l in raw.open() if l.strip()]; ev=[json.loads(l) for l in events.open() if l.strip()]
 for p in (manifest,raw,events):sourcehashes[str(p.relative_to(SOURCE_ROOT))]=hashlib.sha256(p.read_bytes()).hexdigest()
 n=len(rows);assert n==m['samples']==item['sample_rows']
 counts=Counter();dur=Counter();err=[];referr=[];features_age=[];cmds=Counter();event_types=Counter(x['event'] for x in ev)
 t=np.array([r['recorded_monotonic_s'] for r in rows]); dt=np.diff(t,append=t[-1]); valid=(dt>0)&(dt<=.25)
 monotonic_span=t[-1]-t[0]; utc_span=utc(rows[-1]['recorded_utc_time'])-utc(rows[0]['recorded_utc_time'])
 trace=[]; cm=np.zeros((3,3),dtype=int); phases=['approaching','working','retreating']; motion_thresholds={str(v):0 for v in [.001,.005,.01]}
 head=[];control=[];closing=[];eventhead=[];eventcontrol=[];eventclosing=[]; maxqd=[]; sample_lag=[];sources=Counter();shadows=[]
 for i,r in enumerate(rows):
  f=r.get('features') or {};d=r.get('controller_decision') or {}; rt=r.get('robot_telemetry') or {}; age=rt.get('source_age_s');qd=rt.get('actual_qd')
  fresh=(rt.get('available') is True and isinstance(qd,list) and len(qd)==6 and all(num(x) for x in qd) and num(age) and 0<=age<=.25)
  q=max(map(abs,qd)) if fresh else None; event=r.get('ground_truth_event') in ['hazard','distractor']
  for th in motion_thresholds:motion_thresholds[th]+=int(event and fresh and q>float(th))
  body=f.get('body_geometry') or {};hd=f.get('d');cd=d.get('d');cv=body.get('v_proj',f.get('v_proj'));s=d.get('speed_fraction')
  flags={'tracking_stale':r.get('stale') is True,'fresh_telemetry':fresh,'measured_motion':fresh and q>.005,'event_window':event,
   'event_motion':event and fresh and q>.005,'event_fresh_telemetry':event and fresh,'controller_present':bool(d),
   'stop_command':num(s) and s==0,'reduced_command':num(s) and 0<s<1,'full_command':num(s) and s==1,
   'event_stop_command':event and num(s) and s==0,'output_applied':bool(d) and r.get('controller_output_applied') is True,
   'event_closing_gate':event and num(cv) and cv>=.6,'event_inside_red':event and num(cd) and cd<=.94,
   'event_closing_and_inside_red':event and num(cd) and cd<=.94 and num(cv) and cv>=.6,
   'body_available':(r.get('body_tracking') or {}).get('available') is True,
   'live_reference':(r.get('geometry_reference') or {}).get('source')=='live_rtde_tcp'}
  for k,v in flags.items():counts[k]+=int(v);dur[k+'_s']+=float(dt[i])*int(v)*int(valid[i])
  if num(s) and valid[i]:dur['command_speed_deficit_s']+=(1-s)*dt[i]
  expected={'static':'fixed zone','fixed_zone':'fixed zone','dynamic_ssm':'reactive SSM','adaptive':'predictive SSM'}
  if d:
   counts['identity_mismatch']+=int(d.get('condition') is not None and expected.get(d.get('condition'))!=item['controller_condition'])
   counts['identity_unspecified']+=int(d.get('condition') is None)
   counts['fail_closed']+=int(d.get('status')=='tracking_unavailable')
   cmds[d.get('command','missing')]+=1
  if num(hd):head.append(hd)
  if num(cd):control.append(cd)
  if num(cv):closing.append(cv)
  if event:
   if num(hd):eventhead.append(hd)
   if num(cd):eventcontrol.append(cd)
   if num(cv):eventclosing.append(cv)
  if fresh:maxqd.append(q)
  p=r.get('position'); pose=rt.get('actual_tcp_pose'); gr=r.get('geometry_reference') or {}; row_error=None
  if num(hd) and isinstance(p,list) and len(p)==3 and isinstance(pose,list) and len(pose)==6 and fresh:
   row_error=abs(hd-col_distance(p,pose[:3]));err.append(row_error)
  if num(hd) and isinstance(p,list) and isinstance(gr.get('tcp_position_m'),list):
   referr.append(abs(hd-col_distance(p,gr['tcp_position_m'])))
  if num(rt.get('sampled_monotonic_s')):sample_lag.append(rt['sampled_monotonic_s']-r['recorded_monotonic_s'])
  if num(f.get('t')) and num(r.get('t')):features_age.append(f['t']-r['t'])
  src=d.get('geometry_source') or ('legacy_unspecified' if d else 'no_decision');sources[src]+=1
  true=r.get('ground_truth_phase'); pred=r.get('hmm_state')
  if true in phases and pred in phases and not r.get('stale'): cm[phases.index(true),phases.index(pred)]+=1
  shadow=r.get('controller_comparison') or {}
  if shadow and valid[i]: shadows.append({'dt':float(dt[i]),'speeds':{k:v.get('speed_fraction') for k,v in shadow.items()}})
  trace.append({'t_s':round(float(t[i]-t[0]),4),'head_proxy_m':hd,'control_proxy_m':cd,'closing_m_s':cv,'command_fraction':s,'max_joint_speed_rad_s':q,'event':event,'stale':r.get('stale') is True,'gap_after':not bool(valid[i]),'head_to_current_tcp_error_m':row_error})
 # Summaries use all rows; time integrals cover only positive intervals <=250 ms.
 result={k:item[k] for k in ['session_id','participant_id','trial_id','controller_condition','planned_event']}
 result.update({'samples':n,'sample_span_s':monotonic_span,'utc_span_s':utc_span,'catalog_duration_s':m['catalog_summary']['duration_s'],
  'observed_interval_s':float(dt[valid].sum()),'gap_interval_s':float(dt[dt>.25].sum()),'gap_count':int((dt>.25).sum()),'nonpositive_interval_count':int((dt[:-1]<=0).sum()),'median_interval_ms':quant(dt[dt>0].tolist(),.5)*1000,
  'sample_rate_hz':(n-1)/monotonic_span,'stale_sample_pct':pct(counts['tracking_stale'],n),'fresh_telemetry_pct':pct(counts['fresh_telemetry'],n),
  'controller_present_pct':pct(counts['controller_present'],n),'output_applied_of_decisions_pct':pct(counts['output_applied'],counts['controller_present']),
  'stop_command_pct_of_observed_time':pct(dur['stop_command_s'],float(dt[valid].sum())),
  'min_head_proxy_m':min(head) if head else None,'min_control_proxy_m':min(control) if control else None,'event_min_head_proxy_m':min(eventhead) if eventhead else None,
  'event_min_control_proxy_m':min(eventcontrol) if eventcontrol else None,'event_max_closing_m_s':max(eventclosing) if eventclosing else None,
  'max_joint_speed_rad_s':max(maxqd) if maxqd else None,'head_geometry_error_median_m':quant(err,.5),'head_geometry_error_p95_m':quant(err,.95),
  'head_recorded_reference_error_median_m':quant(referr,.5),'head_recorded_reference_error_p95_m':quant(referr,.95),
  'telemetry_sample_time_offset_median_s':quant(sample_lag,.5),'telemetry_sample_time_offset_p95_s':quant(sample_lag,.95),
  'feature_clock_offset_median_s':quant(features_age,.5),'release_hash':(m.get('study_release') or {}).get('sha256'),'model_sha256':m.get('model_sha256'),
  'capture_mode':m.get('capture_mode','legacy_operator_confirmed'),'manifest_final_data_approved':(m.get('study_release') or {}).get('final_data_approved'),
  'labelled_phase_samples':int(cm.sum()),'phase_label_agreement_pct':pct(int(np.trace(cm)),int(cm.sum())),
  **dict(counts),**{k:float(v) for k,v in dur.items()}})
 for threshold,count in motion_thresholds.items(): result['event_motion_samples_threshold_'+threshold]=count
 # Diagnostic nonzero-to-zero request transitions, not protective stops or reaction time.
 result['command_stop_onsets']=sum(1 for i,x in enumerate(trace) if i>0 and x['command_fraction']==0 and trace[i-1]['command_fraction'] not in (0,None) and 0<t[i]-t[i-1]<=.25)
 metrics.append(result);traces[item['session_id']]=trace;confusion[item['session_id']]=cm.tolist()
 detail[item['session_id']]={'event_types':dict(event_types),'geometry_sources':dict(sources),'command_counts':dict(cmds),'event_markers':[x for x in ev if x['event'] in ['trial_started','trial_completed','planned_event_window_started','planned_event_window_ended']], 'shadow_time_s':sum(x['dt'] for x in shadows),'shadow_mean_command':{c:sum(x['dt']*x['speeds'][c] for x in shadows if num(x['speeds'].get(c)))/sum(x['dt'] for x in shadows if num(x['speeds'].get(c))) for c in ['fixed zone','reactive SSM','predictive SSM']} if shadows else {}}
 print(item['participant_id'],item['trial_id'],item['controller_condition'],item['planned_event'],'motion',counts['measured_motion'],'event_motion',counts['event_motion'],'min',result['event_min_control_proxy_m'],'maxv',result['event_max_closing_m_s'],'geometry_p95',result['head_geometry_error_p95_m'])
assert len(metrics)==14 and sum(x['samples'] for x in metrics)==65697
json.dump({'analysis_date':'2026-09-19','purpose':'Descriptive recovered-record analysis, not confirmatory controller comparison','settings':{'maximum_integrated_interval_s':.25,'fresh_telemetry_age_max_s':.25,'diagnostic_joint_motion_rad_s':.005,'configured_red_boundary_m':.94,'closing_gate_m_s':.6},'trials':metrics,'details':detail,'phase_confusions':confusion},(OUT/'results.json').open('w'),indent=2,allow_nan=False)
fields=list(dict.fromkeys(k for r in metrics for k in r))
with (OUT/'trial-metrics.csv').open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(metrics)
json.dump(sourcehashes,(OUT/'source-sha256.json').open('w'),indent=2)
json.dump(traces,(OUT/'traces.json').open('w'),separators=(',',':'),allow_nan=False)
json.dump({'complete_sets':len(metrics),'sample_rows':sum(x['samples'] for x in metrics),'participant_codes':dict(Counter(x['participant_id'] for x in metrics)), 'event_motion_samples':sum(x['event_motion'] for x in metrics),'motion_samples':sum(x['measured_motion'] for x in metrics),'tracked_hours':sum(x['sample_span_s'] for x in metrics)/3600,'assertions':'14 manifests match 14 raw sample counts; total 65697; all JSON serializes without NaN'},(OUT/'checks.json').open('w'),indent=2)
