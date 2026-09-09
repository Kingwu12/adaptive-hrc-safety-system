#!/usr/bin/env python3
"""Offline command witnesses using the configured controllers and pilot artifact.

Synthetic inputs establish branch behavior, not predictive accuracy or safety.
This script opens no sockets and sends no hardware commands.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from hrc_safety.config import load_config
from hrc_safety.experiment_diagnostics import ControllerComparison, model_health
from hrc_safety.features import FeatureFrame
from hrc_safety.pilot_model import load_upper_hmm


def verify(model_path):
    config = load_config()
    hmm = load_upper_hmm(model_path)
    scenarios = []
    cases = [('near boundary', .8, 0, [0, 0, 0]),
             ('stationary outside red', 1.1, 0, [.35, 1, 1]),
             ('rapid approach outside yellow', 1.6, 1.5, [1, 1, 0])]
    for name, distance, closing, expected in cases:
        comparison = ControllerComparison(config, hmm)
        for tick in range(2):
            frame = FeatureFrame(tick/60, distance, -closing, closing,
                                 closing, 0, 0, 1 if closing else 0)
            decisions = comparison.decide(frame)
        actual = [decisions[key]['speed_fraction'] for key in comparison.controllers]
        if actual != expected:
            raise AssertionError(f'{name}: expected {expected}, got {actual}')
        scenarios.append({'name':name, 'distance_m':distance, 'closing_m_s':closing,
                          'ticks':2, 'decisions':decisions})
    return {'scope':'Synthetic branch witnesses; not hardware validation, model accuracy or an experimental result.',
            'model_sha256':hashlib.sha256(model_path.read_bytes()).hexdigest(),
            'model_health':model_health(hmm), 'scenarios':scenarios}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model',type=Path,default=Path('data/models/pilot_hmm.json'))
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    result = verify(args.model)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(f'All three synthetic controller witnesses passed: {args.output}')
