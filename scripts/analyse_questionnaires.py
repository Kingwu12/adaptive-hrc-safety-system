"""Reproduce item-level questionnaire summaries from the immutable response snapshot.

No Master-tab formulas, scale conversion, imputation, automatic identity merging,
or assumptions that anonymous registration codes are independent people.
"""
from pathlib import Path
import argparse, ast, csv, hashlib, json, re
from collections import Counter, defaultdict
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
ITEMS=['relaxed','calm','surprised','stopping_confidence','constant_monitoring',
       'unnecessary_stopping','speed_legibility','mental_demand','physical_demand','frustration']
LABELS=['Anxious to relaxed','Agitated to calm','Quiescent to surprised',
        'Confident robot would stop','Had to watch constantly','Stopped more than needed',
        'Speed changes made sense','Mental demand','Physical demand','Frustration']

def summary(values, ordinal=True):
 a=np.array(values,dtype=float)
 if not len(a):return {'n':0}
 q=np.quantile(a,[.25,.5,.75])
 return {'n':len(a),'mean':float(a.mean()),'median':float(q[1]),'q1':float(q[0]),'q3':float(q[2]),
         'min':float(a.min()),'max':float(a.max()),**({'counts':{str(i):int((a==i).sum()) for i in range(1,6)}} if ordinal else {})}

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path,default=ROOT/'data/questionnaires/responses-2026-09-19.json')
 args=parser.parse_args();source=json.loads(args.source.read_text(encoding='utf8'))
 out=ROOT/'data/analysis/questionnaires';out.mkdir(parents=True,exist_ok=True)
 accepted={};excluded=[];duplicates=[]
 for name,s in source['sheets'].items():
  accepted[name]=[];seen=set()
  for r in s['rows']:
   v=r['values'];pid=str(v[1]).strip().upper()
   if not re.fullmatch(r'P\d+',pid):
    excluded.append({'sheet':name,'source_row':r['source_row'],'id':pid,'reason':'explicit pilot/test/qualification identifier'});continue
   key=(pid,str(v[2]).strip()) if name=='Block responses' else (pid,)
   if key in seen:duplicates.append({'sheet':name,'key':key,'row':r['source_row']})
   seen.add(key);accepted[name].append({'participant_code':pid,'source_row':r['source_row'],'timestamp':v[0],'values':v})
 if duplicates:raise ValueError('Duplicate response keys need explicit review: '+str(duplicates))
 intake={r['participant_code']:r for r in accepted['Intake responses']}
 end={r['participant_code']:r for r in accepted['End responses']}
 blocks=[];bycode=defaultdict(list)
 # Extract the assignment constants without importing the hardware dashboard.
 tree=ast.parse((ROOT/'scripts/dashboard_server.py').read_text(encoding='utf8'))
 orders=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='CONTROLLER_ORDERS' for t in n.targets))
 for r in accepted['Block responses']:
  v=r['values'];b=str(v[2]).strip().upper();assert b in 'ABC' and len(b)==1
  record={k:r[k] for k in ['participant_code','source_row','timestamp']};record['block']=b
  for key,value in zip(ITEMS,v[3:13]):
   value=float(value);assert value.is_integer() and 1<=value<=5,(r['participant_code'],key,value)
   record[key]=int(value)
  record['comment']=v[13] or ''
  record['planned_controller']=orders[(int(r['participant_code'][1:])-1)%6]['ABC'.index(b)]
  record['controller_mapping_status']='dashboard assignment only; physical execution not established by this response'
  blocks.append(record);bycode[r['participant_code']].append(record)
 codes=sorted(bycode,key=lambda p:int(p[1:]));complete=[p for p in codes if {x['block'] for x in bycode[p]}==set('ABC')]
 global_rows=[];paired={}
 for p in sorted(set(intake)&set(end),key=lambda p:int(p[1:])):
  a=intake[p]['values'];z=end[p]['values']
  rec={'participant_code':p,'age':a[2],'dominant_hand':a[3],'robot_experience':a[4],
       'prior_unfenced_work':a[5],'prior_mocap':a[6],'safety_pre':int(a[7]),'trust_pre':int(a[8]),
       'safety_post':int(z[8]),'trust_post':int(z[9]),'suit_restriction':int(z[7]),
       'safest_block':z[2],'least_safe_block':z[3],'shift_choice_block':z[4],'noticed_change':z[5],
       'change_comment':z[6] or '', 'risk_comment':z[10] or '', 'discomfort_comment':z[11] or ''}
  assert all(1<=rec[k]<=5 for k in ['safety_pre','trust_pre','safety_post','trust_post','suit_restriction'])
  global_rows.append(rec)
 for measure in ['safety','trust']:
  diffs=[r[measure+'_post']-r[measure+'_pre'] for r in global_rows]
  paired[measure]={'pre':summary([r[measure+'_pre'] for r in global_rows]),'post':summary([r[measure+'_post'] for r in global_rows]),
     'mean_change':float(np.mean(diffs)),'median_change':float(np.median(diffs)),
     'increased':sum(x>0 for x in diffs),'unchanged':sum(x==0 for x in diffs),'decreased':sum(x<0 for x in diffs)}
 # No inferential CIs or p values: unique-person linkage is unresolved after reported restarts.
 item_summaries={k:{b:summary([r[k] for r in blocks if r['block']==b]) for b in 'ABC'} for k in ITEMS}
 item_complete={k:{b:summary([r[k] for r in blocks if r['block']==b and r['participant_code'] in complete]) for b in 'ABC'} for k in ITEMS}
 # Match original ratings within complete response codes, retaining each item's
 # direction. This is a block-sequence description, not a controller contrast.
 complete_pairs={p:{r['block']:r for r in bycode[p]} for p in complete}
 sequence_changes={}
 for key in ITEMS:
  changes=[complete_pairs[p]['C'][key]-complete_pairs[p]['A'][key] for p in complete]
  sequence_changes[key]={'n':len(changes),'increased':sum(v>0 for v in changes),
      'unchanged':sum(v==0 for v in changes),'decreased':sum(v<0 for v in changes),
      'median_change':float(np.median(changes))}
 changed_medians=[{'item':key,'block':b,'all_available':item_summaries[key][b]['median'],
                   'complete_case':item_complete[key][b]['median']}
                  for key in ITEMS for b in 'ABC'
                  if item_summaries[key][b]['median']!=item_complete[key][b]['median']]
 planned={k:{c:summary([r[k] for r in blocks if r['planned_controller']==c]) for c in orders[0]} for k in ITEMS}
 coverage=[]
 for p in sorted(set(intake)|set(end)|set(bycode),key=lambda p:int(p[1:])):
  coverage.append({'participant_code':p,'intake':p in intake,'blocks':sorted(r['block'] for r in bycode.get(p,[])),
      'end':p in end,'first_timestamp':min([r['timestamp'] for r in [intake.get(p),end.get(p),*bycode.get(p,[])] if r]),
      'identity_status':'unreconciled registration code'})
 result={'source_url':source['source_url'],'source_workbook_sha256':source['workbook_sha256'],
  'snapshot_sha256':hashlib.sha256(args.source.read_bytes()).hexdigest(),'analysis_kind':'Descriptive, retrospective; no imputation or distinct-person assumption',
  'raw_counts':{k:len(v['rows']) for k,v in source['sheets'].items()},'included_counts':{k:len(v) for k,v in accepted.items()},
  'excluded':excluded,'duplicate_keys':duplicates,'response_codes':codes,'complete_block_codes':complete,'coverage':coverage,
  'items':dict(zip(ITEMS,LABELS)),'scale':{'min':1,'max':5,'workload':'Adapted single items; not NASA-TLX total or 0-100 scores','trust':'Two separate items; no validated trust composite','safety':'Three separate semantic differential items; surprised remains raw, higher means more surprised'},
  'block_summaries':item_summaries,'complete_case_block_summaries':item_complete,
  'complete_case_A_to_C_changes':sequence_changes,
  'complete_case_median_sensitivity':{'comparisons':len(ITEMS)*3,'changed':changed_medians},
  'planned_controller_sensitivity':planned,'planned_controller_caution':'Not an observed treatment-effect comparison. Mapping is from the dashboard assignment function, not recovered execution for every block.',
  'pre_post':paired,'end_choices':{k:dict(Counter(r[k] for r in global_rows)) for k in ['safest_block','least_safe_block','shift_choice_block','noticed_change']},
  'suit_restriction':summary([r['suit_restriction'] for r in global_rows]),'age':summary([r['age'] for r in global_rows],ordinal=False),
  'inference_withheld_reason':'Restarted registrations and absent full execution records prevent establishing independent people and actual controller exposure.'}
 for name,rows in [('block-items',blocks),('paired-global-items',global_rows),('response-coverage',coverage)]:
  with (out/(name+'.csv')).open('w',newline='',encoding='utf8') as f:
   writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
 (out/'results.json').write_text(json.dumps(result,indent=2,allow_nan=False),encoding='utf8')
 print(json.dumps({k:result[k] for k in ['included_counts','complete_block_codes','pre_post','end_choices']},indent=2))

if __name__=='__main__':main()
