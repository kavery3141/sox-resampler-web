from pathlib import Path

# Make the advanced DSP controls unmistakably discoverable with a persistent
# Basic / Advanced mode selector on the Convert page.
p = Path('app/static/advanced-presets.js')
s = p.read_text()

old = "const ADVANCED_LAST_PRESET_KEY='sox-resampler-last-preset';\n"
new = "const ADVANCED_LAST_PRESET_KEY='sox-resampler-last-preset';\nconst ADVANCED_MODE_KEY='sox-resampler-convert-mode';\n"
if s.count(old) != 1:
    raise SystemExit(f'mode key replacement count={s.count(old)}')
s = s.replace(old, new, 1)

needle = "function advancedInstallPanel(){\n"
insert = """function advancedSetMode(mode,{persist=true}={}){\n  const selected=mode==='advanced'?'advanced':'basic';\n  if(persist)localStorage.setItem(ADVANCED_MODE_KEY,selected);\n  const panel=$('advancedDspPanel');\n  const basic=$('advancedModeBasic');\n  const advanced=$('advancedModeAdvanced');\n  if(panel){\n    panel.classList.toggle('hidden',selected!=='advanced');\n    if(selected==='advanced')panel.open=true;\n  }\n  if(basic){basic.classList.toggle('primary',selected==='basic');basic.setAttribute('aria-pressed',String(selected==='basic'))}\n  if(advanced){advanced.classList.toggle('primary',selected==='advanced');advanced.setAttribute('aria-pressed',String(selected==='advanced'))}\n  const hint=$('advancedModeHint');\n  if(hint)hint.textContent=selected==='advanced'?'Advanced mode: SoX DSP parameters and preset management are visible below.':'Basic mode: choose a preset and review the batch. Switch to Advanced to edit individual SoX parameters.';\n}\n\nfunction advancedInstallPanel(){\n"""
if s.count(needle) != 1:
    raise SystemExit(f'install function replacement count={s.count(needle)}')
s = s.replace(needle, insert, 1)

old = """function advancedInstallPanel(){\n  if($('advancedDspPanel'))return;\n  const panel=document.createElement('details');\n"""
new = """function advancedInstallPanel(){\n  if($('advancedDspPanel'))return;\n  const mode=document.createElement('div');\n  mode.id='advancedModeControl';\n  mode.className='advancedModeControl';\n  mode.innerHTML=`<div><strong>Conversion controls</strong><div id=\"advancedModeHint\" class=\"muted\"></div></div><div class=\"advancedModeButtons\" role=\"group\" aria-label=\"Conversion control mode\"><button id=\"advancedModeBasic\" type=\"button\" aria-pressed=\"false\">Basic</button><button id=\"advancedModeAdvanced\" type=\"button\" aria-pressed=\"false\">Advanced</button></div>`;\n  const panel=document.createElement('details');\n"""
if s.count(old) != 1:
    raise SystemExit(f'mode control insertion count={s.count(old)}')
s = s.replace(old, new, 1)

old = """  $('workerNotice').insertAdjacentElement('afterend',panel);\n  for(const id of ['advTargetRate','advBitDepth','advQuality','advPassband','advPhase','advCompression','advDither','advHeadroom','advAliasing']){\n"""
new = """  $('workerNotice').insertAdjacentElement('afterend',mode);\n  mode.insertAdjacentElement('afterend',panel);\n  $('advancedModeBasic').onclick=()=>advancedSetMode('basic');\n  $('advancedModeAdvanced').onclick=()=>advancedSetMode('advanced');\n  advancedSetMode(localStorage.getItem(ADVANCED_MODE_KEY)||'basic',{persist:false});\n  for(const id of ['advTargetRate','advBitDepth','advQuality','advPassband','advPhase','advCompression','advDither','advHeadroom','advAliasing']){\n"""
if s.count(old) != 1:
    raise SystemExit(f'panel placement replacement count={s.count(old)}')
s = s.replace(old, new, 1)
p.write_text(s)

p = Path('app/static/advanced-presets.css')
s = p.read_text()
append = '.advancedModeControl{display:flex;align-items:center;gap:16px;margin:12px 0;padding:12px 14px;border:1px solid var(--border);border-radius:10px;background:var(--panel2)}.advancedModeControl>div:first-child{min-width:0}.advancedModeControl .muted{margin-top:4px}.advancedModeButtons{display:flex;gap:6px;margin-left:auto;flex:0 0 auto}.advancedModeButtons button{min-width:92px}.advancedModeButtons button[aria-pressed="true"]{font-weight:700}body[data-theme="light"] .advancedModeControl{background:#f8fafc}@media(max-width:620px){.advancedModeControl{align-items:stretch;flex-direction:column}.advancedModeButtons{margin-left:0}.advancedModeButtons button{flex:1}}'
if append in s:
    raise SystemExit('advanced mode CSS already present')
s = s.rstrip() + append + '\n'
p.write_text(s)

# Bump the dynamic add-on cache key so an updated container always serves this JS.
p = Path('app/static/ui.js')
s = p.read_text()
old = "v=20260902c"
new = "v=20260902d"
count = s.count(old)
if count != 1:
    raise SystemExit(f'ui cache version replacement count={count}')
s = s.replace(old, new, 1)
p.write_text(s)
