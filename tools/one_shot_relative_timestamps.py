from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str, label: str) -> None:
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match in {path}, found {count}")
    file_path.write_text(text.replace(old, new, 1), encoding="utf-8")


# Keep every UI timestamp anchored to the NAS timezone while showing both a useful
# relative age and an explicit exact clock time. Backend/export timestamps remain untouched.
replace_once(
    "app/static/app.js",
    "const fmtTime=value=>value?String(value).replace('T',' '):'';\n",
    '''const NAS_TIME_ZONE='America/Indiana/Indianapolis';\nconst fmtExactTime=value=>{\n  if(!value)return '';\n  const date=new Date(value);\n  if(!Number.isFinite(date.getTime()))return String(value).replace('T',' ');\n  try{return new Intl.DateTimeFormat('en-US',{timeZone:NAS_TIME_ZONE,year:'numeric',month:'short',day:'numeric',hour:'numeric',minute:'2-digit',second:'2-digit',timeZoneName:'short'}).format(date)}\n  catch(e){return String(value).replace('T',' ')}\n};\nconst fmtRelativeTime=value=>{\n  if(!value)return '';\n  const date=new Date(value);\n  if(!Number.isFinite(date.getTime()))return '';\n  const delta=date.getTime()-Date.now(),abs=Math.abs(delta);\n  if(abs<45000)return 'just now';\n  let unit='minute',divisor=60000;\n  if(abs<90*60000){unit='minute';divisor=60000}\n  else if(abs<36*3600000){unit='hour';divisor=3600000}\n  else if(abs<45*86400000){unit='day';divisor=86400000}\n  else if(abs<345*86400000){unit='month';divisor=30*86400000}\n  else{unit='year';divisor=365*86400000}\n  const amount=Math.round(delta/divisor)||Math.sign(delta)||0;\n  try{return new Intl.RelativeTimeFormat('en-US',{numeric:'auto'}).format(amount,unit)}\n  catch(e){return delta<0?`${Math.abs(amount)} ${unit}${Math.abs(amount)===1?'':'s'} ago`:`in ${Math.abs(amount)} ${unit}${Math.abs(amount)===1?'':'s'}`}\n};\nconst fmtTime=value=>value?`${fmtRelativeTime(value)} · ${fmtExactTime(value)}`:'';\n''',
    "timestamp formatter",
)

replace_once(
    "app/static/ui.js",
    "    $('homeLastScan').textContent=scan.finished_at||scan.started_at||'Never';\n",
    "    $('homeLastScan').textContent=fmtTime(scan.finished_at||scan.started_at)||'Never';\n",
    "home last scan timestamp",
)

replace_once(
    "app/static/app.js",
    "<span class=\"maintenanceKey\">Last scan</span><span>${esc(scan.finished_at||scan.started_at||'Never')}</span><span class=\"maintenanceKey\">Last scan status</span>",
    "<span class=\"maintenanceKey\">Last scan</span><span>${esc(fmtTime(scan.finished_at||scan.started_at)||'Never')}</span><span class=\"maintenanceKey\">Last scan status</span>",
    "maintenance last scan timestamp",
)
