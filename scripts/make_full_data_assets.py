"""Figures and the controller table for the 97-trial full-data paper.

Inputs: FYP-selected-trial-metrics.csv (27 Sep full-data selection), the
stop-episode results from analyse_stop_episodes.py, and the raw capture for the
representative trace. Read-only on raw data.
"""
import argparse, csv, json, statistics
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

ROOT = Path(__file__).resolve().parents[1]
PAPER = ROOT / 'paper'
CONTROLLERS = ['fixed zone', 'reactive SSM', 'predictive SSM']
LABEL = {'fixed zone': 'Fixed', 'reactive SSM': 'Reactive', 'predictive SSM': 'Predictive'}
C = {'fixed zone': '#28699d', 'reactive SSM': '#bb7332', 'predictive SSM': '#228776'}
MODE = {'legacy_operator_confirmed': 'Early version\n(P13–P22)', 'automatic_streams': 'Later version\n(P31–P38)'}
plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 8, 'axes.spines.top': False, 'axes.spines.right': False,
                     'axes.labelsize': 8, 'xtick.labelsize': 7, 'ytick.labelsize': 7, 'legend.fontsize': 7,
                     'figure.facecolor': 'white', 'savefig.facecolor': 'white', 'pdf.fonttype': 42})


def save(fig, name):
    for ext in ['pdf', 'png']:
        fig.savefig(PAPER / 'figures' / f'{name}.{ext}', dpi=240, bbox_inches='tight', pad_inches=.04)
    plt.close(fig)


def fnum(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def geometry_figure(rows):
    fig, axs = plt.subplots(1, 2, figsize=(7.1, 2.55), gridspec_kw={'width_ratios': [.8, 1.2]})
    ax = axs[0]
    rng = np.random.default_rng(0)
    for i, mode in enumerate(MODE):
        y = [fnum(r['head_geometry_error_p95_m']) for r in rows if r['capture_mode'] == mode]
        y = [v for v in y if v is not None]
        ax.scatter(i + rng.uniform(-.13, .13, len(y)), y, s=9, color='#7593a5' if i == 0 else '#228776', alpha=.75)
        ax.hlines(statistics.median(y), i - .25, i + .25, color='#333', lw=1.2)
        ax.text(i, max(y) + .03, f'n={len(y)}\nmedian {statistics.median(y):.3f} m', ha='center', fontsize=6)
    ax.set_xticks([0, 1], list(MODE.values()))
    ax.set_xlim(-.6, 1.6); ax.set_ylim(-.02, .8)
    ax.set_ylabel('95th-percentile difference (m)')
    ax.set_title('(a) Recorded vs recomputed head distance', loc='left', fontsize=8)
    ax = axs[1]
    cap, clipped = 6.0, 0
    for r in rows:
        x, y = fnum(r['event_min_control_proxy_m']), fnum(r['event_max_closing_m_s'])
        if r['planned_event'] == 'clean' or x is None or y is None:
            continue
        marker = 'o' if r['planned_event'] == 'rapid intrusion' else '^'
        if y > cap:
            clipped += 1
            ax.scatter(x, cap, s=16, facecolors='none', edgecolors=C[r['controller_condition']], marker=marker, lw=1, clip_on=False)
        else:
            ax.scatter(x, y, s=16, color=C[r['controller_condition']], alpha=.8, marker=marker)
    ax.set_ylim(-.2, cap)
    ax.text(.97, cap * .9, f'{clipped} values above {cap:.0f} m/s drawn hollow at the top edge', fontsize=6, color='#555')
    print('clipped', clipped)
    ax.axvline(.94, color='#8a9398', ls='--', lw=.8); ax.axhline(.6, color='#8a9398', ls='--', lw=.8)
    ax.set_xlabel('Smallest distance in cue window (m)'); ax.set_ylabel('Largest closing speed (m/s)')
    ax.set_title('(b) Cue-window extremes', loc='left', fontsize=8)
    handles = [Line2D([0], [0], marker='o', color='#555', ls='', label='Rapid cue'),
               Line2D([0], [0], marker='^', color='#555', ls='', label='Distractor')] + \
              [Line2D([0], [0], marker='s', color=C[c], ls='', label=LABEL[c]) for c in CONTROLLERS]
    ax.legend(handles=handles, loc='center right', fontsize=6, ncol=1, frameon=False)
    fig.tight_layout(w_pad=1.5)
    save(fig, 'geometry-and-events-full')


def trace_figure(raw):
    rows = [json.loads(l) for l in raw.open() if l.strip()]
    t = np.array([r['recorded_monotonic_s'] for r in rows]); t0 = t[0]
    gap = np.r_[np.diff(t) > .25, False]

    def series(get):
        y = np.array([np.nan if get(r) is None else float(get(r)) for r in rows])
        y[np.where(gap)[0] + 1 if gap.any() else []] = np.nan
        return y

    def qd(r):
        rt = r.get('robot_telemetry') or {}; q = rt.get('actual_qd'); age = rt.get('source_age_s')
        ok = rt.get('available') is True and isinstance(q, list) and len(q) == 6 and age is not None and 0 <= age <= .25
        return max(abs(v) for v in q) if ok else None
    dec = lambda r: r.get('controller_decision') or {}
    feat = lambda r: r.get('features') or {}
    closing = lambda r: (feat(r).get('body_geometry') or {}).get('v_proj', feat(r).get('v_proj'))
    event = np.array([r.get('ground_truth_event') in ['hazard', 'distractor'] for r in rows])
    panels = [(series(lambda r: dec(r).get('d')), 'Distance to\nrobot (m)', '#228776', .94),
              (series(closing), 'Closing\nspeed (m/s)', '#28699d', .6),
              (series(lambda r: dec(r).get('speed_fraction')), 'Speed\ncommand', '#8b5e9c', None),
              (series(qd), 'Joint speed\n(rad/s)', '#465964', None)]
    fig, axs = plt.subplots(4, 1, figsize=(7.1, 3.6), sharex=True)
    for ax, (y, label, color, line) in zip(axs, panels):
        ax.plot(t - t0, y, color=color, lw=.8); ax.set_ylabel(label, fontsize=7); ax.grid(axis='y', alpha=.18)
        if event.any():
            ax.axvspan(t[event][0] - t0, t[event][-1] - t0, color='#e8c999', alpha=.32)
        if line is not None:
            ax.axhline(line, color='#888', ls='--', lw=.7)
    axs[2].set_ylim(-.05, 1.05); axs[-1].set_xlabel('Time from first recorded sample (s)')
    fig.tight_layout(h_pad=.3)
    save(fig, 'representative-trace-full')


def controller_table(rows, stops):
    by = {c: [r for r in rows if r['controller_condition'] == c] for c in CONTROLLERS}
    sb = {c: [t for t in stops if t['controller_condition'] == c] for c in CONTROLLERS}
    def s(c, k): return sum(t['applied_causes'][k] for t in sb[c])
    def obs(c): return sum(t['applied']['observed_s'] for t in sb[c]) / 60
    def ev(c, e): return sum(1 for r in by[c] if r['planned_event'] == e)
    lines = [
        ('Trials', lambda c: str(len(by[c]))),
        ('Samples', lambda c: f"{sum(int(r['samples']) for r in by[c]):,}"),
        ('Capture span (min)', lambda c: f"{sum(float(r['sample_span_s']) for r in by[c]) / 60:.1f}"),
        ('Clean / distractor / rapid', lambda c: f"{ev(c, 'clean')}/{ev(c, 'distractor')}/{ev(c, 'rapid intrusion')}"),
        ('Median stop time (\\%)', lambda c: f"{statistics.median(float(r['stop_command_pct_of_observed_time']) for r in by[c]):.1f}"),
        ('All stop requests', lambda c: str(sum(t['applied']['raw_onsets'] for t in sb[c]))),
        ('\\quad Brief: sensing dropout hold', lambda c: str(s(c, 'sensing dropout hold|brief'))),
        ('\\quad Brief: intrusion predictor', lambda c: str(s(c, 'intrusion predictor|brief'))),
        ('\\quad Brief: other rules', lambda c: str(sum(s(c, k + '|brief') for k in ['red boundary', 'envelope minimum', 'tracking unavailable', 'other']))),
        ('\\quad Sustained: red boundary', lambda c: str(s(c, 'red boundary|sustained'))),
        ('\\quad Sustained: intrusion predictor', lambda c: str(s(c, 'intrusion predictor|sustained'))),
        ('\\quad Sustained: other rules', lambda c: str(sum(s(c, k + '|sustained') for k in ['sensing dropout hold', 'envelope minimum', 'tracking unavailable', 'other']))),
        ('Sustained stops per minute', lambda c: f"{sum(sum(v for k, v in t['applied_causes'].items() if k.endswith('|sustained')) for t in sb[c]) / obs(c):.1f}"),
    ]
    body = '\n'.join(f"{name} & " + ' & '.join(fn(c) for c in CONTROLLERS) + ' \\\\' for name, fn in lines)
    tex = ('% Generated by scripts/make_full_data_assets.py; do not hand-edit.\n'
           '\\begin{table}[!t]\n\\centering\n'
           '\\caption{Recorded behaviour by controller (97 trials). Brief stop requests last less than 0.5~s.}\n'
           '\\label{tab:controllers}\n\\footnotesize\n\\begin{tabular}{@{}lrrr@{}}\n\\toprule\n'
           ' & Fixed & Reactive & Predictive \\\\\n\\midrule\n' + body + '\n\\bottomrule\n\\end{tabular}\n'
           '\\par\\smallskip\\begin{minipage}{\\linewidth}\\footnotesize Totals are descriptive, not controller-effect '
           'estimates: order, participant identity and system version are not jointly controlled. Stop time includes '
           'intentional task holds. P13 A1 and P22 A3 have no completed capture.\\end{minipage}\n\\end{table}\n')
    (PAPER / 'tables' / 'controller_summary.tex').write_text(tex)
    print(tex)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--selected', type=Path, required=True)
    ap.add_argument('--trace-raw', type=Path, required=True)
    ap.add_argument('--stops', type=Path, default=ROOT / 'data/analysis/stop-episodes/trials.json')
    a = ap.parse_args()
    rows = list(csv.DictReader(a.selected.open()))
    assert len(rows) == 97
    stops = json.loads(a.stops.read_text())['trials']
    assert {t['session_id'] for t in stops} == {r['session_id'] for r in rows}
    geometry_figure(rows)
    trace_figure(a.trace_raw)
    controller_table(rows, stops)


if __name__ == '__main__':
    main()
