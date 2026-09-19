"""Generate manuscript tables, numeric macros and publication-sized figures.

Consumes audited empirical summaries only. Synthetic metrics.json is never read.
"""
import csv,json,math
from pathlib import Path
from collections import Counter
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap
from matplotlib.lines import Line2D
from make_paper_tables import _model_validation_table

ROOT=Path(__file__).resolve().parents[1]
PAPER=ROOT/'paper';TABLES=PAPER/'tables';FIG=PAPER/'figures'
TABLES.mkdir(exist_ok=True);FIG.mkdir(exist_ok=True)
R=json.loads((ROOT/'data/analysis/recovered/results.json').read_text())['trials']
T=json.loads((ROOT/'data/analysis/recovered/traces.json').read_text())
Q=json.loads((ROOT/'data/analysis/questionnaires/results.json').read_text())
B=list(csv.DictReader((ROOT/'data/analysis/questionnaires/block-items.csv').open(encoding='utf8')))
G=list(csv.DictReader((ROOT/'data/analysis/questionnaires/paired-global-items.csv').open(encoding='utf8')))
MODEL=json.loads((ROOT/'data/models/pilot_hmm.json').read_text())
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':8,'axes.spines.top':False,'axes.spines.right':False,
 'axes.labelsize':8,'xtick.labelsize':7,'ytick.labelsize':7,'legend.fontsize':7,'figure.facecolor':'white','savefig.facecolor':'white','pdf.fonttype':42})
C={'fixed zone':'#28699d','reactive SSM':'#bb7332','predictive SSM':'#228776'}
def save(fig,name):
 for ext in ['pdf','png']:fig.savefig(FIG/(name+'.'+ext),dpi=240,bbox_inches='tight',pad_inches=.04)
 plt.close(fig)
def table(name,caption,label,columns,headers,rows,wide=False,foot=None):
 env='table*' if wide else 'table';text=[f'\\begin{{{env}}}[t]','\\centering',f'\\caption{{{caption}}}',f'\\label{{{label}}}','\\footnotesize',f'\\begin{{tabular}}{{{columns}}}','\\toprule',' & '.join(headers)+r' \\','\\midrule']
 text+=[' & '.join(map(str,row))+r' \\' for row in rows]
 text+=['\\bottomrule','\\end{tabular}']
 if foot:text+=['\\par\\smallskip\\begin{minipage}{\\linewidth}\\footnotesize '+foot+'\\end{minipage}']
 text+=[f'\\end{{{env}}}']
 (TABLES/name).write_text('% Generated from empirical evidence; do not hand-edit.\n'+'\n'.join(text)+'\n')
def f(x,n=2):return '--' if x is None else f'{x:.{n}f}'
span=sum(r['sample_span_s'] for r in R);gap=sum(r['gap_interval_s'] for r in R)
macros={'TrialCount':str(len(R)),'SensorRows':f"{sum(r['samples'] for r in R):,}",'CaptureMinutes':f(span/60),
 'ObservedSeconds':f(sum(r['observed_interval_s'] for r in R)),'GapSeconds':f(gap),'GapCount':str(sum(r['gap_count'] for r in R)),
 'GapPercent':f(100*gap/span),'StaleRows':str(sum(r['tracking_stale'] for r in R)),
 'FailClosedRows':str(sum(r['fail_closed'] for r in R)),'DecisionRows':f"{sum(r['controller_present'] for r in R):,}",
 'EventMotionSeconds':f(sum(r['event_motion_s'] for r in R)),'BlockResponses':str(len(B)),
 'FollowupCodes':str(len(G)),'IntakeCodes':str(Q['included_counts']['Intake responses']),
 'CompleteSurveyCodes':str(len(Q['complete_block_codes'])),
 'LegacyErrorLow':f(min(r['head_geometry_error_p95_m'] for r in R[:-1]),3),
 'LegacyErrorHigh':f(max(r['head_geometry_error_p95_m'] for r in R[:-1]),3)}
macros.update({'StableBlockMedians':str(Q['complete_case_median_sensitivity']['comparisons']-len(Q['complete_case_median_sensitivity']['changed'])),
 'EventFreshRows':f"{sum(r['event_fresh_telemetry'] for r in R):,}",
 'EventMotionRowsLow':f"{sum(r['event_motion_samples_threshold_0.001'] for r in R):,}",
 'EventMotionRowsMain':f"{sum(r['event_motion_samples_threshold_0.005'] for r in R):,}",
 'EventMotionRowsHigh':f"{sum(r['event_motion_samples_threshold_0.01'] for r in R):,}"})
for key in ['safety','trust']:
 for phase in ['pre','post']:macros[key.title()+phase.title()+'Mean']=f(Q['pre_post'][key][phase]['mean'])
 macros[key.title()+'MeanChange']=f(Q['pre_post'][key]['mean_change'])
(TABLES/'empirical_numbers.tex').write_text('% Auto-generated numeric values.\n'+'\n'.join('\\newcommand{\\'+k+'}{'+v+'}' for k,v in macros.items())+'\n')
(TABLES/'model_validation.tex').write_text(_model_validation_table(MODEL),encoding='utf8')

condshort={'fixed zone':'Fixed','reactive SSM':'Reactive','predictive SSM':'Predictive'}
rows=[]
for r in R:
 rows.append([r['participant_id']+' '+r['trial_id'],condshort[r['controller_condition']],r['planned_event'].replace('rapid intrusion','Rapid cue').title(),f"{r['samples']:,}",f(r['sample_span_s'],1),f(r['gap_interval_s'],2),f(r['stop_command_pct_of_observed_time'],1)])
table('recovered_trials.tex','Analysed telemetry trials. Span is capture duration, not isolated task time. Zero-request time includes intentional holds; it is not a false-stop rate.','tab:trials','lllrrrr',
 ['Code/trial','Controller','Planned event','Rows','Span (s)','Gaps (s)','Zero request (\\%)'],rows,True,
 'Intervals over 250 ms are excluded from time integrals. Zero-request percentage uses the remaining positive intervals as its denominator. P17 and P22 use the earlier head geometry; P24 uses anchored segment origins for control.')
qrows=[]
for key,label in Q['items'].items():
 vals=Q['block_summaries'][key]
 qrows.append([label,*[f"{f(vals[b]['median'],0)} [{f(vals[b]['q1'],1)}, {f(vals[b]['q3'],1)}]" for b in 'ABC']])
table('questionnaire_items.tex','Block questionnaire items: median [first, third quartile]. A, B and C are reported block labels, not pooled controller conditions. All ratings use 1--5.','tab:survey','lrrr',
 ['Item','A ($n=11$)','B ($n=11$)','C ($n=9$)'],qrows,True,
 'Higher means the right-hand semantic anchor for the first three items, stronger agreement for the next four, and greater demand/frustration for the final three. Responses are clustered within 11 study IDs; individual-level linkage is incomplete. No trust, safety or workload composite is used.')
prows=[]
for key,label in [('safety','Felt safe'),('trust','Trust in distance')]:
 d=Q['pre_post'][key]
 prows.append([label,f(d['pre']['mean']),f(d['post']['mean']),f(d['mean_change']),f"{d['increased']}/{d['unchanged']}/{d['decreased']}"])
table('global_ratings.tex','Paired global ratings for 11 codes with intake and end responses. Five-point items; descriptive code-level changes only.','tab:global','lrrrr',
 ['Item','Before','After','$\\Delta$','Up/same/down'],prows,
 foot='Before/after wording changes from expected to experienced safety/trust. Means summarize coded responses; neither causation nor an interval-scale measurement model is assumed.')

sequence_rows=[]
for key,label in Q['items'].items():
 medians='/'.join(f(Q['complete_case_block_summaries'][key][b]['median'],0) for b in 'ABC')
 d=Q['complete_case_A_to_C_changes'][key]
 sequence_rows.append([label,medians,f"{d['increased']}/{d['unchanged']}/{d['decreased']}"])
table('questionnaire_sensitivity.tex','Complete response sets: block medians and within-code changes ($n=9$ codes).','tab:survey-sensitivity','@{}lcc@{}',
 ['Item','A/B/C','A to C: up/same/down'],sequence_rows,
 foot='Counts refer to the raw rating direction, not uniformly to improvement. A--C changes describe block sequence, not a controller effect. The same nine codes supply every row.')

# Evidence availability: every cell refers to an actual response or complete raw file set.
codes=[r['participant_code'] for r in Q['coverage']]
matrix=np.zeros((len(codes),6));rawcount=Counter(r['participant_id'] for r in R)
for i,r in enumerate(Q['coverage']):
 matrix[i]=[int(r['intake']),*[int(b in r['blocks']) for b in 'ABC'],int(r['end']),int(rawcount[r['participant_code']]>0)]
fig,ax=plt.subplots(figsize=(7.1,3.75));ax.imshow(matrix,cmap=ListedColormap(['#edf0f2','#367e9e']),vmin=0,vmax=1,aspect='auto')
ax.set_yticks(range(len(codes)),codes);ax.set_xticks(range(6),['Intake','Block A','Block B','Block C','End','Telemetry'])
for i,p in enumerate(codes):
 for j in range(6):ax.text(j,i,str(rawcount[p]) if j==5 and rawcount[p] else ('1' if matrix[i,j] else '-'),ha='center',va='center',color='white' if matrix[i,j] else '#78858e',fontsize=7)
ax.tick_params(length=0);ax.set_title('Data availability by study ID',loc='left',fontsize=9)
ax.set_xlabel('Cells: form submissions; final column: complete telemetry trial sets')
fig.tight_layout();save(fig,'evidence-coverage')

fig,axs=plt.subplots(1,2,figsize=(7.1,2.65),gridspec_kw={'width_ratios':[1.13,1]})
ax=axs[0];ax.bar(range(len(R)),[r['head_geometry_error_p95_m'] for r in R],color=['#7593a5']*13+['#228776'])
ax.set_xticks(range(len(R)),[r['participant_id']+' '+r['trial_id'] for r in R],rotation=65,ha='right',fontsize=6)
ax.set_ylabel('95th-percentile discrepancy (m)');ax.set_ylim(0,.6);ax.set_title('(a) Head proxy vs live-TCP recomputation',loc='left',fontsize=8)
ax.text(13,.025,'~0',ha='center',fontsize=7)
ax=axs[1]
for r in R:
 if r['event_min_control_proxy_m'] is None:continue
 ax.scatter(r['event_min_control_proxy_m'],r['event_max_closing_m_s'],c=C[r['controller_condition']],s=27,marker='o' if r['planned_event']=='rapid intrusion' else '^')
 if (r['participant_id'],r['trial_id']) in [('P17','T09'),('P17','T08'),('P24','T01')]:
  ax.annotate(r['participant_id']+' '+r['trial_id'],(r['event_min_control_proxy_m'],r['event_max_closing_m_s']),xytext=(-2,5),textcoords='offset points',fontsize=6,ha='center')
ax.axvline(.94,color='#8a9398',ls='--',lw=.8);ax.axhline(.6,color='#8a9398',ls='--',lw=.8)
ax.set_xlabel('Minimum control proxy (m)');ax.set_ylabel('Maximum closing input (m/s)');ax.set_ylim(-.1,5.9);ax.set_xlim(0,2.35)
ax.set_title('(b) Dashboard cue-window extrema',loc='left',fontsize=8)
ax.legend(handles=[Line2D([0],[0],marker='o',color='#555',ls='',label='Rapid cue'),Line2D([0],[0],marker='^',color='#555',ls='',label='Distractor')],loc='upper right',fontsize=6)
fig.tight_layout(w_pad=1.5);save(fig,'geometry-and-events')

r=next(r for r in R if r['participant_id']=='P24');a=T[r['session_id']];times=np.array([x['t_s'] for x in a]);event=np.array([x['event'] for x in a]);fig,axs=plt.subplots(4,1,figsize=(7.1,3.9),sharex=True)
for ax,key,label,color in zip(axs,['control_proxy_m','closing_m_s','command_fraction','max_joint_speed_rad_s'],['Control proxy\n(m)','Closing input\n(m/s)','Command\nfraction','Joint speed\n(rad/s)'],['#228776','#28699d','#8b5e9c','#465964']):
 y=np.array([x[key] if x[key] is not None else np.nan for x in a]);y[[i+1 for i,x in enumerate(a[:-1]) if x['gap_after']]]=np.nan
 ax.plot(times,y,color=color,lw=.85);ax.set_ylabel(label,fontsize=7);ax.grid(axis='y',alpha=.18);ax.axvspan(times[event][0],times[event][-1],color='#e8c999',alpha=.32)
axs[0].axhline(.94,color='#888',ls='--',lw=.7);axs[1].axhline(.6,color='#888',ls='--',lw=.7)
axs[2].set_ylim(-.05,1.05);axs[-1].set_xlabel('Time from first recorded sample (s)')
fig.tight_layout(h_pad=.3);save(fig,'p24-recorded-trace')

# Original ordinal response distributions, deliberately not averaged into a scale.
fig,ax=plt.subplots(figsize=(7.1,3.35));palette=['#315775','#6e92aa','#d6dee2','#d6b36f','#aa7530'];left=np.zeros(10)
for rating,color in zip(range(1,6),palette):
 n=np.array([sum(int(r[key])==rating for r in B) for key in Q['items']]);ax.barh(range(10),n,left=left,color=color,label=str(rating),height=.7)
 for i,v in enumerate(n):
  if v>=2:ax.text(left[i]+v/2,i,str(v),ha='center',va='center',fontsize=7,color='white' if rating in [1,2,5] else '#273b47')
 left+=n
ax.set_yticks(range(10),list(Q['items'].values()));ax.invert_yaxis();ax.set_xlim(0,len(B));ax.set_xlabel('Block-response count (31 submissions from 11 codes)')
ax.legend(title='Raw rating',ncol=5,loc='upper center',bbox_to_anchor=(.5,1.13),frameon=False,title_fontsize=7)
fig.tight_layout();save(fig,'questionnaire-distributions')

fig,axs=plt.subplots(1,2,figsize=(7.1,2.55),sharey=True)
for ax,key,title in zip(axs,['safety','trust'],['Expected / experienced safety','Expected / experienced trust']):
 for i,r in enumerate(G):
  offset=(i-(len(G)-1)/2)*.013
  ax.plot([offset,1+offset],[int(r[key+'_pre']),int(r[key+'_post'])],color='#3e7d9b',alpha=.40,marker='o',ms=3,lw=.8)
 ax.set_xticks([0,1],['Before','After']);ax.set_yticks(range(1,6));ax.set_ylim(.8,5.3);ax.set_xlim(-.17,1.17);ax.set_title(title,loc='left',fontsize=8);ax.grid(axis='y',alpha=.15)
axs[0].set_ylabel('Raw rating (1-5)');fig.tight_layout();save(fig,'global-ratings')
print('Generated empirical tables, macros and five scientific figures.')
