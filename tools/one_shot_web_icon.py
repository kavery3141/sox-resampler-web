from pathlib import Path
p = Path('app/static/index.html')
s = p.read_text()
s = s.replace('<title>SoX Resampler Web</title>\n  <link rel="stylesheet" href="/static/app.css">', '<title>SoX Resampler Web</title>\n  <link rel="icon" type="image/png" href="/static/icon.png?v=20260902">\n  <link rel="apple-touch-icon" href="/static/icon.png?v=20260902">\n  <link rel="stylesheet" href="/static/app.css">', 1)
s = s.replace('<div class="brand"><img src="/static/icon.png" alt="SoX Resampler Web">', '<div class="brand"><img src="/static/icon.png?v=20260902" alt="SoX Resampler Web">', 1)
p.write_text(s)
