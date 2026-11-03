"""Portable inputs/output paths for the original AURANGA reconstruction stages."""
import hashlib
import json
import os
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parent
if not os.environ.get('CMPDI_SOURCE_PDF'):
    raise RuntimeError('Set CMPDI_SOURCE_PDF to the original AURANGA_10.pdf first; see ../README.md.')
SOURCE = Path(os.environ['CMPDI_SOURCE_PDF']).expanduser().resolve()
ROOT = Path(os.environ.get('CMPDI_FONT_WORK', HERE/'work')).expanduser().resolve()
manifest = json.loads((HERE.parent/'manifest.json').read_text())
if hashlib.sha256(SOURCE.read_bytes()).hexdigest() != manifest['source_sha256']:
    raise ValueError('These fitted reconstruction stages require the recorded AURANGA_10.pdf; source SHA256 differs.')
ROOT.mkdir(parents=True, exist_ok=True)
for path in (HERE/'inputs').glob('*.json'):
    target = ROOT/path.name
    if not target.exists():
        shutil.copy2(path, target)
(ROOT/'font_trials').mkdir(exist_ok=True)
reviews = ROOT/'font_trials/review_decisions.json'
if not reviews.exists():
    reviews.write_text('{"reviews": []}\n')
