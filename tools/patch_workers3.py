from pathlib import Path

replacements = {
    'app/static/index.html': [
        ('<select id="activeWorkerSelect"><option value="1">1</option><option value="2">2</option></select>', '<select id="activeWorkerSelect"><option value="1">1</option><option value="2">2</option><option value="3">3</option></select>'),
        ('<select id="workerSelect"><option value="1">1 — Low load</option><option value="2">2 — Faster</option></select>', '<select id="workerSelect"><option value="1">1 — Low load</option><option value="2">2 — Faster</option><option value="3">3 — Maximum</option></select>'),
        ('Two workers increase CPU and disk I/O. Use when the NAS is relatively idle.', 'Multiple workers increase CPU and disk I/O. Three workers is the maximum and should be used when the NAS is relatively idle.'),
    ],
    'app/static/retry-failed.js': [
        ('<select id="retryFailedWorkers"><option value="1">1 — Low load</option><option value="2">2 — Faster</option></select>', '<select id="retryFailedWorkers"><option value="1">1 — Low load</option><option value="2">2 — Faster</option><option value="3">3 — Maximum</option></select>'),
    ],
    'app/static/retry-headroom.js': [
        ('<select id="retryHeadroomWorkers"><option value="1">1 — Low load</option><option value="2">2 — Faster</option></select>', '<select id="retryHeadroomWorkers"><option value="1">1 — Low load</option><option value="2">2 — Faster</option><option value="3">3 — Maximum</option></select>'),
    ],
    'app/main.py': [
        ('if workers not in (1, 2):\n        raise HTTPException(status_code=400, detail="Workers must be 1 or 2")', 'if workers not in (1, 2, 3):\n        raise HTTPException(status_code=400, detail="Workers must be 1, 2, or 3")'),
    ],
    'app/review.py': [
        ('if workers not in (1, 2):\n        raise ValueError("Workers must be 1 or 2")', 'if workers not in (1, 2, 3):\n        raise ValueError("Workers must be 1, 2, or 3")'),
    ],
    'app/jobs.py': [
        ('if workers not in (1, 2):\n            raise JobError("Workers must be 1 or 2")', 'if workers not in (1, 2, 3):\n            raise JobError("Workers must be 1, 2, or 3")'),
        ('files[cursor: cursor + max(1, min(2, current_workers))]', 'files[cursor: cursor + max(1, min(3, current_workers))]'),
    ],
}

for raw_path, pairs in replacements.items():
    path = Path(raw_path)
    text = path.read_text()
    for old, new in pairs:
        count = text.count(old)
        if count < 1:
            raise SystemExit(f'{raw_path}: expected replacement text not found: {old[:80]!r}')
        text = text.replace(old, new)
    path.write_text(text)
    print(f'patched {raw_path}')

# Basic assertions so the one-shot job fails instead of silently producing a partial implementation.
assert '3 — Maximum' in Path('app/static/index.html').read_text()
assert Path('app/main.py').read_text().count('workers not in (1, 2, 3)') >= 2
assert 'min(3, current_workers)' in Path('app/jobs.py').read_text()
assert Path('app/jobs.py').read_text().count('workers not in (1, 2, 3)') >= 2
assert 'workers not in (1, 2, 3)' in Path('app/review.py').read_text()
print('three-worker support patched successfully')
