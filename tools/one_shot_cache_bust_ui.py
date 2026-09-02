from pathlib import Path

# Force browsers to fetch the current UI shell and dynamically loaded add-ons after deployments.
p = Path('app/static/index.html')
s = p.read_text()
old = '<script src="/static/ui.js"></script>'
new = '<script src="/static/ui.js?v=20260902c"></script>'
if s.count(old) != 1:
    raise SystemExit(f'index ui.js replacement count={s.count(old)}')
s = s.replace(old, new, 1)
p.write_text(s)

p = Path('app/static/ui.js')
s = p.read_text()
old = "function loadUiAddon(src){const script=document.createElement('script');script.src=src;script.async=false;document.body.appendChild(script)}"
new = "function loadUiAddon(src){const script=document.createElement('script');const sep=src.includes('?')?'&':'?';script.src=`${src}${sep}v=20260902c`;script.async=false;document.body.appendChild(script)}"
if s.count(old) != 1:
    raise SystemExit(f'addon loader replacement count={s.count(old)}')
s = s.replace(old, new, 1)
p.write_text(s)
