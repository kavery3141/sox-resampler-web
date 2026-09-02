from pathlib import Path

p = Path('app/static/index.html')
s = p.read_text()
old = '<link rel="icon" type="image/png" href="/static/icon.png?v=20260902">\n  <link rel="apple-touch-icon" href="/static/icon.png?v=20260902">'
new = '<link rel="icon" type="image/x-icon" href="/static/favicon.ico?v=20260902b">\n  <link rel="apple-touch-icon" href="/static/icon.png?v=20260902b">'
if s.count(old) != 1:
    raise SystemExit(f'expected exactly one favicon block, found {s.count(old)}')
s = s.replace(old, new, 1)
old_brand = '<div class="brand"><img src="/static/icon.png?v=20260902" alt="SoX Resampler Web">'
new_brand = '<div class="brand"><img src="/static/icon.png?v=20260902b" alt="SoX Resampler Web">'
if s.count(old_brand) != 1:
    raise SystemExit(f'expected exactly one brand icon, found {s.count(old_brand)}')
s = s.replace(old_brand, new_brand, 1)
p.write_text(s)
