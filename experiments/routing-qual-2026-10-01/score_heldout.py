"""Held-out scoring entry point with a corrected sealed-gold hash check.

Post-freeze scorer defect (found 2026-10-02 at first held-out scoring):
score.verify_gold_access compares the gold file with the *first* hash in
cases/heldout-gold.sha256, which is the hash of heldout.jsonl, so it rejects
the correct sealed gold. score.py is a frozen file, so it is left unchanged
and this wrapper replaces only that function. The replacement reads the line
naming heldout-gold.jsonl in both the committed file and FROZEN.json. Every
other check (freeze present, freeze before each run, run bound to the current
freeze) and all metric code are unchanged.
"""
import json
from pathlib import Path

import score


def _gold_hash(text):
    for line in text.strip().splitlines():
        fields = line.split()
        if len(fields) == 2 and fields[1].endswith('heldout-gold.jsonl'):
            return fields[0]
    raise ValueError('no heldout-gold.jsonl line in the commitment')


def verify_gold_access(gold_path, manifests, root=score.ROOT, sealed_path=score.SEALED):
    gold_path, root = Path(gold_path), Path(root)
    heldout = [m for m in manifests if m.get('split') == 'heldout']
    if gold_path.resolve() != Path(sealed_path).resolve() and not heldout:
        return
    frozen_path = root / 'FROZEN.json'
    if not frozen_path.exists():
        raise ValueError('sealed/held-out scoring requires FROZEN.json')
    frozen = json.loads(frozen_path.read_text())
    freeze_time = score.timestamp(frozen['frozen_at'])
    for manifest in heldout:
        if freeze_time >= score.timestamp(manifest['started_at']):
            raise ValueError('freeze must precede every held-out run')
    expected = _gold_hash((root / 'cases/heldout-gold.sha256').read_text())
    if score.sha256(gold_path) != expected:
        raise ValueError('held-out gold hash mismatch')
    if _gold_hash(frozen.get('heldout_gold_sha256', '')) != expected:
        raise ValueError('gold hash differs from the frozen commitment')
    for manifest in heldout:
        if manifest.get('frozen_sha256') != score.sha256(frozen_path):
            raise ValueError('run does not identify the current freeze commitment')


score.verify_gold_access = verify_gold_access

if __name__ == '__main__':
    score.main()
