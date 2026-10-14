"""Figures for the deck's trained-model slides, from the stored model and its development data.

Usage: .venv/bin/python scripts/make_deck_model_figures.py
"""
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from hrc_safety.pilot_training import load_trial, fit_trials, _filter_trial  # noqa: E402

OUT = ROOT / 'presentation/media/model'
MODEL = json.loads((ROOT / 'data/models/pilot_hmm.json').read_text())
STATES = MODEL['states']
COL = {'approaching': '#2b6cb0', 'working': '#2f855a', 'retreating': '#c05621'}
NAMES = {'d': 'distance to robot', 'v_proj': 'approach speed',
         'speed': 'body speed', 'heading_alignment': 'facing the robot'}
plt.rcParams.update({'font.family': 'Arial', 'font.size': 13})


def trials():
    runs = MODEL['data_summary']['training_runs']
    return [load_trial(ROOT / 'data/xsens' / r['file_name']) for r in runs]


def confusion():
    cm = np.array(MODEL['validation']['confusion'], float)
    cm = cm / cm.sum(axis=1, keepdims=True)
    fig, ax = plt.subplots(figsize=(5.6, 4.8))
    ax.imshow(cm, cmap='Greens', vmin=0, vmax=1)
    for i in range(3):
        for j in range(3):
            ax.text(j, i, f'{cm[i, j]:.0%}', ha='center', va='center',
                    color='white' if cm[i, j] > .5 else 'black', fontsize=16, fontweight='bold')
    ax.set_xticks(range(3), STATES); ax.set_yticks(range(3), STATES)
    ax.set_xlabel('model said'); ax.set_ylabel('person was actually')
    ax.set_title('Leave-one-operator-out (full-trial decoding)', fontsize=13)
    fig.tight_layout(); fig.savefig(OUT / 'confusion.png', dpi=200); plt.close(fig)


def feature_space(ts):
    X = np.concatenate([t.X for t in ts]); y = np.array([l for t in ts for l in t.labels])
    rng = np.random.default_rng(0); idx = rng.choice(len(X), 6000, replace=False)
    fig, ax = plt.subplots(figsize=(6.4, 4.8))
    for s in STATES:
        k = idx[y[idx] == s]
        ax.scatter(X[k, 0], X[k, 1], s=5, alpha=.35, color=COL[s], label=s)
    ax.set_xlabel('distance to robot (m)'); ax.set_ylabel('approach speed (m/s)')
    ax.set_ylim(-1.2, 1.2); ax.legend(markerscale=4, frameon=False)
    ax.set_title(f'{len(X):,} labelled frames the model learned from', fontsize=13)
    ax.spines[['top', 'right']].set_visible(False)
    fig.tight_layout(); fig.savefig(OUT / 'feature-space.png', dpi=200); plt.close(fig)


def held_out(ts):
    # Show the held-out trial with the median live accuracy, not a best or worst case.
    model = fit_trials([t for t in ts if t.participant_id != 'P05'], emission_components=3)
    scored = []
    for trial in (t for t in ts if t.participant_id == 'P05'):
        p, tr = _filter_trial(model, trial)
        scored.append((np.mean(np.array(p) == np.array(tr)), trial, p, tr))
    scored.sort(key=lambda r: r[0])
    _, test, pred, truth = scored[len(scored) // 2]
    X = np.concatenate(test.feature_sequences)
    t = np.arange(len(truth)) / 60.0
    fig, axs = plt.subplots(3, 1, figsize=(11, 4.2), sharex=True,
                            gridspec_kw={'height_ratios': [2.2, .6, .6]})
    axs[0].plot(t, X[:, 0], color='#333', lw=1.2); axs[0].set_ylabel('distance (m)')
    axs[0].spines[['top', 'right']].set_visible(False)
    for ax, seq, lab in ((axs[1], truth, 'actual'), (axs[2], pred, 'model (live)')):
        ax.imshow([[STATES.index(s) for s in seq]], aspect='auto', extent=(t[0], t[-1], 0, 1),
                  cmap=matplotlib.colors.ListedColormap([COL[s] for s in STATES]), vmin=0, vmax=2)
        ax.set_yticks([.5], [lab]); ax.tick_params(left=False)
    axs[2].set_xlabel('time (s, labelled frames)')
    handles = [plt.Rectangle((0, 0), 1, 1, color=COL[s]) for s in STATES]
    axs[0].legend(handles, STATES, ncol=3, frameon=False, loc='upper right')
    acc = np.mean(np.array(pred) == np.array(truth))
    axs[0].set_title(f'Held-out trial {test.participant_id} {test.trial_id}: model trained only on the other two operators '
                     f'({acc:.0%} of frames correct)', fontsize=12)
    fig.tight_layout(); fig.savefig(OUT / 'held-out-trial.png', dpi=200); plt.close(fig)


def pipeline():
    fig, ax = plt.subplots(figsize=(11, 3.6)); ax.axis('off'); ax.set_xlim(0, 11); ax.set_ylim(0, 3.6)
    def box(x, y, w, h, txt, fc, fs=12, bold=False):
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle='round,pad=0.05', fc=fc, ec='#444'))
        ax.text(x + w / 2, y + h / 2, txt, ha='center', va='center', fontsize=fs,
                fontweight='bold' if bold else 'normal')
    box(.1, 1.1, 1.9, 1.4, 'Xsens suit\n23 body segments\n+ OptiTrack head\n~60 Hz', '#edf2f7')
    for i, f in enumerate(MODEL['feature_order']):
        box(2.5, 2.75 - i * .8, 2.3, .6, NAMES[f], '#e6fffa', 11)
    box(5.4, .5, 2.6, 2.6, '', '#f0fff4')
    ax.text(6.7, 2.85, 'Hidden Markov model', ha='center', fontsize=12, fontweight='bold')
    for i, s in enumerate(STATES):
        ax.add_patch(plt.Circle((5.95 + i * .75, 1.7), .32, color=COL[s]))
        ax.text(5.95 + i * .75, 1.7, s[:4], ha='center', va='center', color='white', fontsize=10, fontweight='bold')
    ax.text(6.7, .85, '3 phases × 3-Gaussian mixture\nlearned from labelled trials', ha='center', fontsize=10)
    box(8.6, 1.1, 2.3, 1.4, 'phase estimate\nevery frame →\nspeed controller\n(can only slow)', '#fffaf0', 11)
    for y in (3.05, 2.25, 1.45, .65):
        ax.annotate('', (2.5, y), (2.0, 1.8), arrowprops=dict(arrowstyle='->', color='#666'))
        ax.annotate('', (5.4, 1.8), (4.8, y), arrowprops=dict(arrowstyle='->', color='#666'))
    ax.annotate('', (8.6, 1.8), (8.0, 1.8), arrowprops=dict(arrowstyle='->', color='#666', lw=2))
    fig.tight_layout(); fig.savefig(OUT / 'pipeline.png', dpi=200); plt.close(fig)


if __name__ == '__main__':
    ts = trials()
    pipeline(); confusion(); feature_space(ts); held_out(ts)
    print('wrote', sorted(p.name for p in OUT.iterdir()))
