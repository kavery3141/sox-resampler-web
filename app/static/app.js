const state={albums:[],selected:new Map(),profiles:[],review:null,reviewBody:null,jobId:null,jobPoll:null,readOnly:false};
const $=id=>document.getElementById(id);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmtBytes=n=>{if(!n)return '0 B';const u=['B','KB','MB','GB','TB'];let i=0,x=Number(n);while(x>=1024&&i<u.length-1){x/=1024;i++}return `${x.toFixed(i>1?1:0)} ${u[i]}`};
const basename=p=>String(p||'').split('/').pop()||String(p||'');
const NAS_TIME_ZONE='America/Indiana/Indianapolis';
const fmtExactTime=value=>{
  if(!value)return '';
  const date=new Date(value);
  if(!Number.isFinite(date.getTime()))return String(value).replace('T',' ');
  try{return new Intl.DateTimeFormat('en-US',{timeZone:NAS_TIME_ZONE,year:'numeric',month:'short',day:'numeric',hour:'numeric',minute:'2-digit',second:'2-digit',timeZoneName:'short'}).format(date)}
  catch(e){return String(value).replace('T',' ')}
};
const fmtRelativeTime=value=>{
  if(!value)return '';
  const date=new Date(value);
  if(!Number.isFinite(date.getTime()))return '';
  const delta=date.getTime()-Date.now(),abs=Math.abs(delta);
  if(abs<45000)return 'just now';
  let unit='minute',divisor=60000;
  if(abs<90*60000){unit='minute';divisor=60000}
  else if(abs<36*3600000){unit='hour';divisor=3600000}
  else if(abs<45*86400000){unit='day';divisor=86400000}
  else if(abs<345*86400000){unit='month';divisor=30*86400000}
  else{unit='year';divisor=365*86400000}
  const amount=Math.round(delta/divisor)||Math.sign(delta)||0;
  try{return new Intl.RelativeTimeFormat('en-US',{numeric:'auto'}).format(amount,unit)}
  catch(e){return delta<0?`${Math.abs(amount)} ${unit}${Math.abs(amount)===1?'':'s'} ago`:`in ${Math.abs(amount)} ${unit}${Math.abs(amount)===1?'':'s'}`}
};
const fmtTime=value=>value?`${fmtRelativeTime(value)} · ${fmtExactTime(value)}`:'';
function selectedKey(a){return `${a.albumartist}\u0000${a.album}\u0000${a.folder}`}
function activeRates(){const r=[];if($('r96').checked)r.push(96000);if($('r192').checked)r.push(192000);return r}
function lines(id){return $(id).value.split(/\r?\n/).map(x=>x.trim()).filter(Boolean)}
function resetAck(){state.review=null;state.reviewBody=null;$('replaceAck').checked=false;$('startBtn').disabled=true;$('ackArea').classList.add('hidden');$('startActions').classList.add('hidden');$('exportReviewTxt').disabled=true;$('exportReviewCsv').disabled=true}
function notice(id,text,kind='info'){const n=$(id);n.className=`notice ${kind}`;n.textContent=text;n.classList.remove('hidden')}

async function loadStatus(){
  try{
    const s=await fetch('/api/status').then(r=>r.json());
    $('trackCount').textContent=s.library.tracks.toLocaleString();
    $('albumCount').textContent=s.library.albums.toLocaleString();
    $('highCount').textContent=s.library.high_rate_tracks.toLocaleString();
    $('cpuCount').textContent=`${Math.round(s.cpu_percent)}%`;
    $('zfsCount').textContent=s.zfs?.ok?'Healthy':'Blocked';
    state.readOnly=Boolean(s.read_only_mode);
    $('readOnlyBanner').classList.toggle('show',state.readOnly);
    if($('readOnlyState')){$('readOnlyState').textContent=state.readOnly?'Enabled':'Disabled';$('readOnlyState').className=`statusPill ${state.readOnly?'paused':'completed'}`}
    if(s.scan.running)showScan(`Scanning: ${s.scan.files_seen.toLocaleString()} FLACs seen, ${s.scan.files_read.toLocaleString()} updated`,false);
    if(s.conversion.active_job_id&&state.jobId!==s.conversion.active_job_id)watchJob(s.conversion.active_job_id,true);
  }catch(e){}
}
function showScan(text,bad=false){const n=$('scanNotice');n.textContent=text;n.classList.remove('hidden','bad');if(bad)n.classList.add('bad')}
async function loadProfiles(){const data=await fetch('/api/profiles').then(r=>r.json());state.profiles=data.profiles;$('profileSelect').innerHTML=data.profiles.map(p=>`<option value="${esc(p.id)}" ${p.id===data.default?'selected':''}>${esc(p.name)}</option>`).join('')}
async function loadCandidates(){const p=new URLSearchParams();for(const r of activeRates())p.append('rates',r);if($('above48').checked)p.set('above','48000');try{const data=await fetch('/api/library/candidates?'+p).then(r=>r.json());state.albums=data.albums;render()}catch(e){$('results').innerHTML='<div class="row"><div></div><div class="muted">Unable to load library index.</div></div>'}}
function filtered(){const q=$('textSearch').value.trim().toLowerCase();if(!q)return state.albums;return state.albums.filter(a=>(a.albumartist||'').toLowerCase().includes(q)||(a.album||'').toLowerCase().includes(q))}
function render(){
  const rows=filtered();
  $('matchCount').textContent=`${rows.length.toLocaleString()} albums matched`;
  $('results').innerHTML=rows.length?rows.map(a=>{
    const key=selectedKey(a),checked=state.selected.has(key)?'checked':'',disabled=a.selectable?'':'disabled';
    const badges=[...(a.releasetypes||'').split(',').filter(Boolean).map(x=>`<span class="badge">${esc(x)}</span>`),...(a.warnings||[]).map(x=>`<span class="badge warn">${esc(x)}</span>`),...(a.blockers||[]).map(x=>`<span class="badge bad">${esc(x)}</span>`)].join('');
    return `<div class="row" data-key="${encodeURIComponent(key)}"><div><input class="check albumCheck" type="checkbox" ${checked} ${disabled} aria-label="Select ${esc(a.album)}"></div><div><div class="album-artist">${esc(a.albumartist||'Missing Album Artist')}</div><div class="album-title">${esc(a.album||'Missing Album')}</div><div class="badges">${badges}</div></div><div>${(a.source_rates||[]).map(r=>(r/1000)+' kHz').join(', ')}</div><div>${a.matching_tracks}/${a.total_tracks}</div><div>${(a.bit_depths||[]).map(b=>b+'-bit').join(', ')}</div><div>${fmtBytes(a.matching_bytes)}</div></div>`;
  }).join(''):'<div class="row"><div></div><div class="muted">No matching albums.</div></div>';
  document.querySelectorAll('.albumCheck').forEach(c=>c.addEventListener('change',e=>{const key=decodeURIComponent(e.target.closest('.row').dataset.key);const album=state.albums.find(a=>selectedKey(a)===key);if(e.target.checked&&album)state.selected.set(key,album);else state.selected.delete(key);updateTray();resetAck()}));
  updateTray();
}
function updateTray(){const albums=[...state.selected.values()];$('tray').classList.toggle('hidden',albums.length===0);$('selectedCount').textContent=`${albums.length} album${albums.length===1?'':'s'} selected`;$('selectedTracks').textContent=`${albums.reduce((n,a)=>n+a.matching_tracks,0)} matching tracks`;$('selectedSize').textContent=`${fmtBytes(albums.reduce((n,a)=>n+a.matching_bytes,0))} source`}

function showView(which){
  for(const name of ['library','convert','history','settings','maintenance'])$(`${name}View`).classList.toggle('hidden',which!==name);
  for(const name of ['Library','Convert','History','Settings','Maintenance'])$(`nav${name}`).classList.toggle('active',which===name.toLowerCase());
  if(which==='convert'&&!state.jobId)refreshReview();
  if(which==='history')loadHistory();
  if(which==='settings')loadSettings();
  if(which==='maintenance')loadMaintenance();
}
function buildReviewBody(){const albums=[...state.selected.values()];return {albums:albums.map(a=>({albumartist:a.albumartist,album:a.album,folder:a.folder})),rates:activeRates(),above:$('above48').checked?48000:null,profile_id:$('profileSelect').value,workers:Number($('workerSelect').value)}}
async function refreshReview(){
  resetAck();const albums=[...state.selected.values()];
  if(!albums.length){$('reviewStatus').className='notice warn';$('reviewStatus').textContent='No albums selected.';$('reviewSummary').classList.add('hidden');$('reviewAlbums').classList.add('hidden');return}
  const body=buildReviewBody();$('reviewStatus').className='notice';$('reviewStatus').textContent='Running preflight checks…';
  try{
    const r=await fetch('/api/convert/review',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const d=await r.json();if(!r.ok)throw new Error(typeof d.detail==='string'?d.detail:'Review failed');
    state.review=d;state.reviewBody=body;$('reviewStatus').className='notice '+(d.can_start?'good':'bad');$('reviewStatus').textContent=d.can_start?'Preflight passed. Review the details and acknowledge replacement to enable Start Conversion.':(d.blockers?.[0]||'Batch cannot start yet.');
    $('reviewSummary').classList.remove('hidden');$('reviewSummary').innerHTML=`<div class="reviewMetric"><span>Selected</span><strong>${d.album_count} albums, ${d.matching_tracks} tracks</strong></div><div class="reviewMetric"><span>Preset</span><strong>${esc(d.profile.name)}</strong></div><div class="reviewMetric"><span>Source size</span><strong>${fmtBytes(d.source_bytes)}</strong></div><div class="reviewMetric"><span>Estimated savings</span><strong>${fmtBytes(d.estimated_savings_bytes)}</strong></div><div class="reviewMetric"><span>Free space</span><strong>${fmtBytes(d.free_bytes)}</strong></div><div class="reviewMetric"><span>ZFS</span><strong>${d.zfs?.ok?'Healthy':'Blocked'}</strong></div><div class="reviewMetric"><span>CPU cap</span><strong>${d.cpu_limit_percent!==null&&d.cpu_limit_percent!==undefined?`${d.cpu_limit_percent}% / worker`:'Disabled'}</strong></div>`;
    $('reviewAlbums').classList.remove('hidden');$('reviewAlbums').innerHTML=d.albums.map(a=>`<div class="reviewAlbum"><div class="album-artist">${esc(a.albumartist)}</div><div class="album-title">${esc(a.album)}</div><div class="kv"><span class="muted">Matching tracks</span><span>${a.matching_tracks}</span><span class="muted">Source size</span><span>${fmtBytes(a.source_bytes)}</span><span class="muted">After estimate</span><span>${fmtBytes(a.estimated_output_bytes)}</span><span class="muted">Estimated savings</span><span>${fmtBytes(a.estimated_savings_bytes)}</span></div>${(a.warnings||[]).map(x=>`<span class="badge warn">${esc(x)}</span>`).join('')}${(a.blockers||[]).map(x=>`<div class="notice bad" style="margin-top:10px">${esc(x)}</div>`).join('')}${a.tracks?.[0]?.command?.length?`<details style="margin-top:10px"><summary>Command preview</summary><div class="command">${esc(a.tracks[0].command.join(' '))}</div></details>`:''}</div>`).join('');
    $('ackArea').classList.toggle('hidden',!d.can_start);$('startActions').classList.toggle('hidden',!d.can_start);$('startBtn').disabled=true;$('exportReviewTxt').disabled=false;$('exportReviewCsv').disabled=false;
  }catch(e){$('reviewStatus').className='notice bad';$('reviewStatus').textContent=e.message}
}
async function downloadReview(ext){if(!state.reviewBody)return;try{const r=await fetch(`/api/convert/review/report.${ext}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(state.reviewBody)});if(!r.ok){const d=await r.json();throw new Error(typeof d.detail==='string'?d.detail:'Report export failed')}const blob=await r.blob();const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=`sox-resampler-pre-conversion.${ext}`;document.body.appendChild(a);a.click();a.remove();URL.revokeObjectURL(url)}catch(e){$('reviewStatus').className='notice bad';$('reviewStatus').textContent=e.message}}
async function startConversion(){if(!state.review?.can_start||!state.reviewBody||!$('replaceAck').checked)return;const b=$('startBtn');b.disabled=true;const old=b.innerHTML;b.textContent='Starting…';try{const body={...state.reviewBody,acknowledged_replace_in_place:true};const r=await fetch('/api/convert/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const d=await r.json();if(!r.ok){const detail=typeof d.detail==='string'?d.detail:(d.detail?.blockers||[]).join('; ');throw new Error(detail||'Unable to start conversion')}state.jobId=d.job_id;if(typeof resetOperationalBatchOptions==='function')resetOperationalBatchOptions();$('replaceAck').checked=false;$('ackArea').classList.add('hidden');$('startActions').classList.add('hidden');watchJob(d.job_id,true)}catch(e){$('reviewStatus').className='notice bad';$('reviewStatus').textContent=e.message}finally{b.innerHTML=old}}

function statusClass(status){return ['running','completed','failed','interrupted','paused','stopped','cancelled'].includes(status)?status:''}
function renderJob(j){
  $('activeJob').classList.remove('hidden');$('jobTitle').textContent=`Conversion Job ${j.id}`;$('jobDetail').textContent=`Preset: ${j.profile_id} · Started: ${fmtTime(j.started_at)||'not started'}`;$('jobStatus').className=`statusPill ${statusClass(j.status)}`;$('jobStatus').textContent=j.status;
  $('jobProgress').style.width=`${Math.max(0,Math.min(100,Number(j.progress_percent||0)))}%`;$('jobProgressText').textContent=`${j.processed_files||0} of ${j.total_files||0} files processed (${Number(j.progress_percent||0).toFixed(1)}%)`;
  $('jobCompleted').textContent=j.counts?.completed||0;$('jobFailed').textContent=j.counts?.failed||0;$('jobPending').textContent=j.counts?.pending||0;$('jobActive').textContent=j.counts?.running||0;$('jobWorkers').textContent=j.workers;$('activeWorkerSelect').value=String(j.workers||1);
  const current=j.current_files||[];$('jobCurrent').classList.toggle('hidden',current.length===0);$('jobCurrentList').innerHTML=current.map(f=>`<div class="currentFile"><strong>${esc(basename(f.path))}</strong><div class="muted">${esc(f.albumartist)} — ${esc(f.album)}</div></div>`).join('');
  const failures=j.recent_failures||[];$('jobFailureArea').classList.toggle('hidden',failures.length===0);$('jobFailures').innerHTML=failures.map(f=>`<div class="failure"><strong>${esc(basename(f.path))}</strong><div>${esc(f.error_text||'Conversion failed')}</div></div>`).join('');
  $('jobError').classList.toggle('hidden',!j.error_text);$('jobError').textContent=j.error_text||'';const active=['running','pausing','stopping','cancelling'].includes(j.status);$('pauseJob').classList.toggle('hidden',!active);$('stopJob').classList.toggle('hidden',!active);$('cancelJob').classList.toggle('hidden',!active);$('resumeJob').classList.toggle('hidden',!['paused','interrupted'].includes(j.status));$('activeWorkerSelect').disabled=!active;$('jobReportTxt').href=`/api/convert/jobs/${j.id}/report.txt`;$('jobReportCsv').href=`/api/convert/jobs/${j.id}/report.csv`;
}
async function pollJob(follow=true){if(!state.jobId)return;try{const r=await fetch(`/api/convert/jobs/${state.jobId}`);if(!r.ok)throw new Error('Unable to load conversion job');const j=await r.json();renderJob(j);if(['completed','cancelled','stopped'].includes(j.status)){if(state.jobPoll){clearInterval(state.jobPoll);state.jobPoll=null}await loadCandidates();await loadStatus();if(j.status==='completed'){state.selected.clear();updateTray()}}else if(follow&&!state.jobPoll){state.jobPoll=setInterval(()=>pollJob(true),1500)}}catch(e){$('jobError').classList.remove('hidden');$('jobError').textContent=e.message}}
function watchJob(id,follow=true){state.jobId=Number(id);$('activeJob').classList.remove('hidden');showView('convert');if(state.jobPoll){clearInterval(state.jobPoll);state.jobPoll=null}pollJob(follow);if(follow)state.jobPoll=setInterval(()=>pollJob(true),1500)}
async function jobAction(action){if(!state.jobId)return;try{const r=await fetch(`/api/convert/jobs/${state.jobId}/${action}`,{method:'POST'});const d=await r.json();if(!r.ok)throw new Error(typeof d.detail==='string'?d.detail:'Job action failed');await pollJob(true)}catch(e){$('jobError').classList.remove('hidden');$('jobError').textContent=e.message}}
async function loadHistory(){const box=$('historyRows');box.innerHTML='<div class="historyRow"><div></div><div class="muted">Loading history…</div></div>';try{const d=await fetch('/api/convert/jobs?limit=100').then(r=>r.json());const jobs=d.jobs||[];$('historyCount').textContent=`${jobs.length} recent jobs`;box.innerHTML=jobs.length?jobs.map(j=>`<div class="historyRow"><div>#${j.id}</div><div><span class="statusPill ${statusClass(j.status)}">${esc(j.status)}</span></div><div><strong>${esc(j.profile_id)}</strong><div class="muted">${esc(fmtTime(j.created_at))}</div></div><div>${j.workers}</div><div>${j.error_text?'<span class="badge warn">Message</span>':'—'}</div><div class="historyActions"><button data-view-job="${j.id}">View</button><a href="/api/convert/jobs/${j.id}/report.txt">TXT</a><a href="/api/convert/jobs/${j.id}/report.csv">CSV</a></div></div>`).join(''):'<div class="historyRow"><div></div><div class="muted">No conversion history yet.</div></div>';document.querySelectorAll('[data-view-job]').forEach(b=>b.onclick=()=>watchJob(Number(b.dataset.viewJob),false))}catch(e){box.innerHTML=`<div class="historyRow"><div></div><div class="muted">${esc(e.message)}</div></div>`}}

async function loadSettings(){
  try{
    const d=await fetch('/api/settings').then(r=>r.json());
    state.readOnly=Boolean(d.read_only_mode);$('readOnlyBanner').classList.toggle('show',state.readOnly);$('readOnlyState').textContent=state.readOnly?'Enabled':'Disabled';$('readOnlyState').className=`statusPill ${state.readOnly?'paused':'completed'}`;$('enableReadOnly').disabled=state.readOnly;$('disableReadOnly').disabled=!state.readOnly;$('reserveGb').value=String(d.free_space_reserve_gb??10);$('excludePaths').value=(d.exclude_paths||[]).join('\n');$('excludeGlobs').value=(d.exclude_globs||[]).join('\n');
  }catch(e){notice('settingsNotice',e.message,'bad')}
}
async function setReadOnly(enabled){
  if(!enabled&&!confirm('Disable Read-only Scan Mode and restore conversion capability?'))return;
  try{const r=await fetch('/api/settings/read-only',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({enabled,confirmed_disable:!enabled})});const d=await r.json();if(!r.ok)throw new Error(d.detail||'Unable to change Read-only Scan Mode');notice('settingsNotice',enabled?'Read-only Scan Mode enabled. Conversion is disabled.':'Read-only Scan Mode disabled. Conversion still requires explicit batch review and confirmation.','good');await loadSettings();await loadStatus();resetAck()}catch(e){notice('settingsNotice',e.message,'bad')}
}
function storageSettingsBody(){return {free_space_reserve_gb:Number($('reserveGb').value),exclude_paths:lines('excludePaths'),exclude_globs:lines('excludeGlobs')}}
async function previewExclusions(){try{const r=await fetch('/api/settings/exclusions/preview',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({exclude_paths:lines('excludePaths'),exclude_globs:lines('excludeGlobs')})});const d=await r.json();if(!r.ok)throw new Error(d.detail||'Unable to preview exclusions');notice('exclusionPreview',`${d.folders.toLocaleString()} folders and ${d.flac_files.toLocaleString()} FLAC files would be excluded.`,'info')}catch(e){notice('exclusionPreview',e.message,'bad')}}
async function saveStorageSettings(){try{const body=storageSettingsBody();const r=await fetch('/api/settings/storage',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const d=await r.json();if(!r.ok)throw new Error(d.detail||'Unable to save storage settings');notice('settingsNotice','Storage safety settings saved. Run a rescan to apply exclusion changes to the index.','good');await loadSettings();await loadStatus();resetAck()}catch(e){notice('settingsNotice',e.message,'bad')}}

async function loadMaintenance(){
  try{
    const d=await fetch('/api/maintenance/status').then(r=>r.json());
    $('maintenanceSummary').innerHTML=`<div class="card metric"><span>Indexed FLACs</span><strong>${d.library.tracks.toLocaleString()}</strong></div><div class="card metric"><span>Indexed Albums</span><strong>${d.library.albums.toLocaleString()}</strong></div><div class="card metric"><span>Database</span><strong>${fmtBytes(d.database.size_bytes+d.database.wal_bytes)}</strong></div><div class="card metric"><span>Free space</span><strong>${fmtBytes(d.free_bytes)}</strong></div><div class="card metric"><span>ZFS</span><strong>${d.zfs?.ok?'Healthy':'Blocked'}</strong></div>`;
    const scan=d.latest_scan||{};$('maintenanceDetails').innerHTML=`<span class="maintenanceKey">App version</span><span>${esc(d.app_version)}</span><span class="maintenanceKey">Database schema</span><span>${esc(d.db_schema)}</span><span class="maintenanceKey">SoX</span><span>${esc(d.tools.sox||'Unavailable')}</span><span class="maintenanceKey">FLAC</span><span>${esc(d.tools.flac||'Unavailable')}</span><span class="maintenanceKey">Python</span><span>${esc(d.tools.python||'Unavailable')}</span><span class="maintenanceKey">Last scan</span><span>${esc(fmtTime(scan.finished_at||scan.started_at)||'Never')}</span><span class="maintenanceKey">Last scan status</span><span>${esc(scan.status||'—')}</span><span class="maintenanceKey">Timezone</span><span>${esc(d.timezone)}</span><span class="maintenanceKey">Music root</span><span>${esc(d.music_root)}</span><span class="maintenanceKey">Data root</span><span>${esc(d.data_root)}</span>`;
  }catch(e){notice('maintenanceNotice',e.message,'bad')}
}
async function maintenanceAction(path,label,confirmText=null){if(confirmText&&!confirm(confirmText))return;notice('maintenanceNotice',`${label} requested…`,'info');try{const r=await fetch(path,{method:'POST'});const d=await r.json();if(!r.ok)throw new Error(d.detail||`${label} failed`);notice('maintenanceNotice',`${label} accepted.`, 'good');await loadMaintenance();await loadStatus()}catch(e){notice('maintenanceNotice',e.message,'bad')}}

let debounce;$('textSearch').addEventListener('input',()=>{clearTimeout(debounce);debounce=setTimeout(render,250)});['r96','r192','above48'].forEach(id=>$(id).addEventListener('change',()=>{resetAck();loadCandidates()}));
$('refreshBtn').onclick=loadCandidates;$('checkAll').onclick=()=>{for(const a of filtered())if(a.selectable)state.selected.set(selectedKey(a),a);render();resetAck()};$('uncheckAll').onclick=()=>{for(const a of filtered())state.selected.delete(selectedKey(a));render();resetAck()};$('clearSelected').onclick=()=>{state.selected.clear();render();resetAck()};$('reviewBtn').onclick=()=>showView('convert');
$('navLibrary').onclick=()=>showView('library');$('navConvert').onclick=()=>showView('convert');$('navHistory').onclick=()=>showView('history');$('navSettings').onclick=()=>showView('settings');$('navMaintenance').onclick=()=>showView('maintenance');$('backLibrary').onclick=()=>showView('library');
$('reviewRefresh').onclick=refreshReview;$('profileSelect').onchange=refreshReview;$('workerSelect').onchange=()=>{$('workerNotice').classList.toggle('hidden',$('workerSelect').value!=='2');refreshReview()};$('replaceAck').onchange=()=>{$('startBtn').disabled=!($('replaceAck').checked&&state.review?.can_start&&!state.readOnly)};$('startBtn').onclick=startConversion;$('exportReviewTxt').onclick=()=>downloadReview('txt');$('exportReviewCsv').onclick=()=>downloadReview('csv');
$('pauseJob').onclick=()=>jobAction('pause');$('resumeJob').onclick=()=>jobAction('resume');$('stopJob').onclick=()=>jobAction('stop-after-album');$('cancelJob').onclick=()=>jobAction('cancel');$('activeWorkerSelect').onchange=async()=>{if(!state.jobId)return;try{const r=await fetch(`/api/convert/jobs/${state.jobId}/workers`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({workers:Number($('activeWorkerSelect').value)})});if(!r.ok){const d=await r.json();throw new Error(d.detail||'Unable to change workers')}await pollJob(true)}catch(e){$('jobError').classList.remove('hidden');$('jobError').textContent=e.message}};
$('refreshHistory').onclick=loadHistory;$('enableReadOnly').onclick=()=>setReadOnly(true);$('disableReadOnly').onclick=()=>setReadOnly(false);$('previewExclusions').onclick=previewExclusions;$('saveStorageSettings').onclick=saveStorageSettings;$('refreshMaintenance').onclick=loadMaintenance;$('maintenanceIncremental').onclick=()=>maintenanceAction('/api/scan/incremental','Incremental rescan');$('maintenanceFull').onclick=()=>maintenanceAction('/api/maintenance/full-rescan','Full rescan');$('maintenanceRebuild').onclick=()=>maintenanceAction('/api/maintenance/rebuild-index','Index rebuild','Rebuild the local index? This deletes only the app index and immediately starts a full discovery scan. Music files are not modified.');$('maintenanceVacuum').onclick=()=>maintenanceAction('/api/maintenance/vacuum','Database vacuum');
$('scanBtn').onclick=async()=>{const b=$('scanBtn');b.disabled=true;showScan('Incremental library scan queued…');try{const r=await fetch('/api/scan/incremental',{method:'POST'});if(!r.ok){const d=await r.json();throw new Error(d.detail||'Unable to start scan')}const poll=setInterval(async()=>{const s=await fetch('/api/scan/status').then(r=>r.json());if(s.active.running){showScan(`Scanning: ${s.active.files_seen.toLocaleString()} FLACs seen, ${s.active.files_read.toLocaleString()} updated`)}else{clearInterval(poll);showScan(`Scan complete: ${s.latest?.files_seen??0} FLACs seen, ${s.latest?.files_read??0} updated, ${s.latest?.errors??0} errors`,(s.latest?.errors??0)>0);b.disabled=false;await loadStatus();await loadCandidates()}},1200)}catch(e){showScan(e.message,true);b.disabled=false}};

Promise.all([loadStatus(),loadProfiles(),loadCandidates()]);setInterval(loadStatus,5000);
