"""Rebuild the canonical empirical paper; fail rather than silently skip a PDF.

Usage: python scripts/build_paper.py --source-root .. --engine /path/to/tectonic
Use --compile-only when reviewing prose/layout against already generated assets.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def source_hashes(source_root):
    inventory = json.loads((ROOT / 'data/recovered-trial-inventory.json').read_text())
    files = [ROOT / 'data/questionnaires/responses-2026-09-19.json',
             ROOT / 'data/models/pilot_hmm.json']
    for trial in inventory['trials']:
        manifest = source_root / trial['manifest_path']
        files.extend(p for p in [manifest,
                     Path(str(manifest).replace('.manifest.json', '.jsonl')),
                     Path(str(manifest).replace('.manifest.json', '.events.jsonl'))]
                     if p.exists())
    return {str(p.resolve()): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source-root', type=Path, default=ROOT.parent)
    parser.add_argument('--engine', help='Path/name of tectonic or latexmk')
    parser.add_argument('--compile-only', action='store_true')
    args = parser.parse_args()
    source_root = args.source_root.resolve()
    engine = args.engine or shutil.which('tectonic') or shutil.which('latexmk')
    if not engine:
        raise SystemExit('A TeX engine is required: install tectonic or latexmk, or pass --engine.')
    found = shutil.which(engine)
    engine = str(Path(found or engine).resolve())
    if not Path(engine).is_file():
        raise SystemExit('TeX engine does not exist: ' + engine)
    # A manuscript-only build uses the committed tables and figures. Raw study
    # records are deliberately not distributed in the public repository.
    before = source_hashes(source_root) if not args.compile_only else None
    if not args.compile_only:
        commands = [
            ['scripts/analyse_recovered.py', '--source-root', str(source_root)],
            ['scripts/analyse_questionnaires.py'],
            ['scripts/make_empirical_paper_assets.py'],
            ['scripts/verify_empirical_analysis.py', '--source-root', str(source_root)],
        ]
        for command in commands:
            subprocess.run([sys.executable, *command], cwd=ROOT, check=True)
    if 'tectonic' in Path(engine).name.lower():
        command = [engine, '--keep-logs', '--keep-intermediates', 'main.tex']
    elif 'latexmk' in Path(engine).name.lower():
        command = [engine, '-pdf', '-interaction=nonstopmode', '-halt-on-error', 'main.tex']
    else:
        raise SystemExit('Supported engines: tectonic and latexmk')
    subprocess.run(command, cwd=ROOT / 'paper', check=True)
    if before is not None:
        assert before == source_hashes(source_root), 'Raw sources changed during build'
    from pypdf import PdfReader
    pdf = ROOT / 'paper/main.pdf'
    reader = PdfReader(pdf)
    assert 1 <= len(reader.pages) <= 10, f'Paper exceeds the 10-page limit: {len(reader.pages)}'
    text = '\n'.join(page.extract_text() for page in reader.pages)
    assert '[PENDING:' not in text and '??' not in text, 'Unresolved manuscript markers'
    log = (ROOT / 'paper/main.log').read_text(errors='replace')
    assert 'Overfull \\hbox' not in log, 'Overfull line/table; inspect main.log'
    assert 'undefined references' not in log, 'Undefined LaTeX references'
    verification = {'pdf_pages': len(reader.pages),
                    'build_mode': 'compile-only' if args.compile_only else 'full-analysis',
                    'raw_sources_unchanged': True if before is not None else None,
                    'source_file_count': len(before) if before is not None else 0,
                    'pdf_sha256': hashlib.sha256(pdf.read_bytes()).hexdigest(),
                    'engine': engine, 'visual_review': 'See paper/README.md; separate rendered review required'}
    (ROOT / 'paper/build-verification.json').write_text(json.dumps(verification, indent=2))
    print(json.dumps(verification, indent=2))


if __name__ == '__main__':
    main()
