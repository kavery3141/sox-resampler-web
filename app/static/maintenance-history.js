(function installMaintenanceHistoryStyles(){
  if(document.querySelector('link[data-maint-history]'))return;
  const link=document.createElement('link');link.rel='stylesheet';link.href='/static/maintenance-history.css';link.dataset.maintHistory='1';document.head.appendChild(link);
})();

let maintenanceScanPoll=null;

function maintenanceScanInstall(){
  if($('maintenanceScanCard'))return;
  const firstCard=document.querySelector('#maintenanceView > .card');
  const card=document.createElement('section');
  card.id='maintenanceScanCard';card.className='card';card.style.marginTop='14px';
  card.innerHTML=`
    <div class="sectionTitle"><div><h3 style="margin:0">Full Scan Progress</h3><div class="muted">Full scans and index rebuilds can be paused cleanly. Resume performs a complete traversal while skipping unchanged indexed FLACs, then applies deletion reconciliation only after that traversal completes safely.</div></div><span class="spacer"></span><button id="maintenancePauseScan" class="hidden">Pause Full Scan</button><button id="maintenanceResumeScan" class="primary hidden">Resume Full Scan</button></div>
    <div id="maintenanceScanMetrics" class="summary maintenanceHistoryMetrics"></div>
    <div id="maintenanceScanPath" class="muted"></div>
    <div id="maintenanceScanNotice" class="notice hidden"></div>`;
  if(firstCard)firstCard.insertAdjacentElement('afterend',card);else $('maintenanceView').appendChild(card);
  $('maintenancePauseScan').onclick=maintenanceScanPause;
  $('maintenanceResumeScan').onclick=maintenanceScanResume;
}

function maintenanceRecoveryInstall(){
  if($('maintenanceRecoveryCard'))return;
  maintenanceScanInstall();
  const card=document.createElement('section');
  card.id='maintenanceRecoveryCard';card.className='card';card.style.marginTop='14px';
  card.innerHTML=`
    <div class="sectionTitle"><div><h3 style="margin:0">Recovery Safety</h3><div class="muted">Recheck interrupted replacement journals and hidden app temp files after manual repair. Recheck never starts conversion and never promotes a temp file into the library.</div></div><span class="spacer"></span><button id="maintenanceRecheckRecovery" class="primary">Recheck Recovery State</button></div>
    <div id="maintenanceRecoveryMetrics" class="summary maintenanceHistoryMetrics"></div>
    <div id="maintenanceRecoveryNotice" class="notice hidden"></div>
    <div id="maintenanceRecoveryItems" class="maintenanceRecoveryItems"></div>`;
  const scanCard=$('maintenanceScanCard');
  if(scanCard)scanCard.insertAdjacentElement('afterend',card);else $('maintenanceView').appendChild(card);
  $('maintenanceRecheckRecovery').onclick=maintenanceRecoveryRecheck;
}

function maintenanceHistoryInstall(){
  if($('maintenanceHistoryCard'))return;
  const cards=[...document.querySelectorAll('#maintenanceView > .card')];
  const anchor=cards[cards.length-1]||null;
  const card=document.createElement('section');
  card.id='maintenanceHistoryCard';card.className='card';
  card.innerHTML=`
    <div class="sectionTitle"><div><h3 style="margin:0">History & Operational Logs</h3><div class="muted">Clean terminal job history is retained for 180 days. Jobs containing failures or errors are protected from automatic pruning until you deliberately clear terminal history.</div></div><span class="spacer"></span><button id="maintenanceClearHistory" class="danger">Clear Terminal History</button></div>
    <div id="maintenanceHistoryMetrics" class="summary maintenanceHistoryMetrics"></div>
    <div id="maintenanceHistoryNotice" class="notice hidden"></div>
    <div class="maintenanceHistorySplit"><div><strong>Bounded application log</strong><div id="maintenanceLogDetail" class="muted maintenanceLogDetail">Loading…</div></div><div><strong>Recent maintenance events</strong><div id="maintenanceEvents" class="maintenanceEvents muted">Loading…</div></div></div>`;
  if(anchor)anchor.insertAdjacentElement('beforebegin',card);else $('maintenanceView').appendChild(card);
  $('maintenanceClearHistory').onclick=maintenanceHistoryClear;
}

function maintenanceEventDetail(event){
  const detail=event.detail||{};
  if(event.event_type==='conversion_history_cleared')return `${detail.deleted_jobs||0} terminal jobs removed`;
  if(event.event_type==='history_retention_prune')return `${detail.deleted_jobs||0} clean old jobs pruned`;
  if(event.event_type==='transaction_recovery')return detail.action||'transaction recovery check';
  if(event.event_type==='orphan_temp_cleanup')return detail.action||'orphan temp check';
  if(event.event_type==='manual_recovery_recheck')return detail.blocked?`${detail.manual_attention||0} manual, ${detail.errors||0} errors remain`:'recovery state clear';
  if(event.event_type==='scan_pause_requested')return `scan ${detail.scan_id||''} pause requested`.trim();
  if(event.event_type==='scan_resume_requested')return `resuming scan ${detail.resume_of_scan_id||''}`.trim();
  if(event.event_type==='storage_settings_changed')return 'storage safety settings changed';
  if(event.event_type==='read_only_mode_changed')return detail.enabled?'read-only mode enabled':'read-only mode disabled';
  return '';
}
function maintenanceScanRender(data){
  maintenanceScanInstall();
  const scan=data.scan||{};const resumable=data.scan_resumable||null;const latest=data.latest_scan||{};
  const active=Boolean(scan.running);
  const fullActive=active&&['full','full-resume'].includes(scan.mode);
  const reference=active?scan:(resumable||latest);
  const status=active?(scan.status||'running'):(resumable?.status||latest.status||'idle');
  const mode=reference?.mode||'—';
  $('maintenanceScanMetrics').innerHTML=`<div class="card metric"><span>Status</span><strong>${esc(status)}</strong></div><div class="card metric"><span>Mode</span><strong>${esc(mode)}</strong></div><div class="card metric"><span>Folders scanned</span><strong>${Number(scan.folders_scanned||0).toLocaleString()}</strong></div><div class="card metric"><span>FLACs seen</span><strong>${Number(active?scan.files_seen:(reference?.files_seen||0)).toLocaleString()}</strong></div><div class="card metric"><span>FLACs indexed</span><strong>${Number(active?scan.files_read:(reference?.files_read||0)).toLocaleString()}</strong></div><div class="card metric"><span>Issues</span><strong>${Number(active?scan.errors:(reference?.errors||0)).toLocaleString()}</strong></div>`;
  const current=scan.current_path||resumable?.current_path||'';
  $('maintenanceScanPath').textContent=current?`Current / paused location: ${current}`:(reference?.finished_at?`Last finished: ${fmtTime(reference.finished_at)}`:'No full scan progress yet.');
  $('maintenancePauseScan').classList.toggle('hidden',!fullActive||scan.status==='pausing');
  $('maintenanceResumeScan').classList.toggle('hidden',active||!resumable||Boolean(data.conversion_running));
  if(maintenanceScanPoll){clearTimeout(maintenanceScanPoll);maintenanceScanPoll=null}
  if(active)maintenanceScanPoll=setTimeout(()=>maintenanceHistoryLoad(),1500);
}
function maintenanceRecoveryRender(data){
  maintenanceRecoveryInstall();
  const summary=data.recovery_summary||{};
  const outcomes=data.transaction_recovery||[];
  const blocked=Boolean(summary.blocked);
  const busy=Boolean(data.conversion_running)||Boolean(data.scan?.running);
  $('maintenanceRecheckRecovery').disabled=busy;
  $('maintenanceRecheckRecovery').title=busy?'Recovery recheck waits until conversion and scanning are idle':'';
  $('maintenanceRecoveryMetrics').innerHTML=`<div class="card metric"><span>Conversion safety</span><strong>${blocked?'Blocked':'Clear'}</strong></div><div class="card metric"><span>Current records</span><strong>${Number(summary.items||0).toLocaleString()}</strong></div><div class="card metric"><span>Manual attention</span><strong>${Number(summary.manual_attention||0).toLocaleString()}</strong></div><div class="card metric"><span>Recovery errors</span><strong>${Number(summary.errors||0).toLocaleString()}</strong></div><div class="card metric"><span>Automatic actions</span><strong>${Number(summary.automatic_actions||0).toLocaleString()}</strong></div>`;
  const area=$('maintenanceRecoveryItems');
  if(!outcomes.length){
    area.innerHTML='<div class="notice good maintenanceRecoveryState">No outstanding transaction or orphan-temp recovery records are present.</div>';
    return;
  }
  const blockers=outcomes.filter(item=>item.action==='manual_attention'||String(item.action||'').startsWith('recovery_error'));
  const shown=blockers.length?blockers:outcomes;
  area.innerHTML=`<div class="notice ${blocked?'bad':'good'} maintenanceRecoveryState">${blocked?'Conversion remains blocked until the items below are resolved and Recovery State is rechecked.':'The latest recovery pass completed without a blocking condition.'}</div><div class="maintenanceRecoveryList">${shown.map(item=>`<div class="maintenanceRecoveryItem"><strong>${esc(String(item.action||'unknown').replaceAll('_',' '))}</strong><code>${esc(item.source||item.temp||'')}</code>${item.temp?`<div class="muted">Temp: <code>${esc(item.temp)}</code></div>`:''}${item.reason?`<div class="muted">${esc(item.reason)}</div>`:''}</div>`).join('')}</div>`;
}
function maintenanceHistoryRender(data){
  maintenanceScanRender(data);
  maintenanceRecoveryRender(data);
  maintenanceHistoryInstall();
  const history=data.history||{};const logs=data.logs||{};
  $('maintenanceHistoryMetrics').innerHTML=`<div class="card metric"><span>Total jobs</span><strong>${Number(history.total_jobs||0).toLocaleString()}</strong></div><div class="card metric"><span>Terminal</span><strong>${Number(history.terminal_jobs||0).toLocaleString()}</strong></div><div class="card metric"><span>Protected errors</span><strong>${Number(history.protected_error_jobs||0).toLocaleString()}</strong></div><div class="card metric"><span>Resumable</span><strong>${Number(history.resumable_jobs||0).toLocaleString()}</strong></div><div class="card metric"><span>Retention</span><strong>${Number(history.retention_days||180)} days</strong></div>`;
  const approxCap=(Number(logs.active_max_bytes||0)*(Number(logs.rotated_files||0)+1));
  $('maintenanceLogDetail').textContent=`${fmtBytes(logs.total_bytes||0)} currently stored · 10 MB active file + ${Number(logs.rotated_files||0)} rotated files · approximately ${fmtBytes(approxCap)} maximum`;
  const events=data.maintenance_events||[];
  $('maintenanceEvents').innerHTML=events.length?events.map(event=>`<div class="maintenanceEvent"><span>${esc(fmtTime(event.occurred_at))}</span><strong>${esc(String(event.event_type||'').replaceAll('_',' '))}</strong><span>${esc(maintenanceEventDetail(event))}</span></div>`).join(''):'No maintenance events recorded yet.';
}
async function maintenanceHistoryLoad(){
  maintenanceScanInstall();maintenanceRecoveryInstall();maintenanceHistoryInstall();
  try{
    const response=await fetch('/api/maintenance/status');
    const data=await response.json();if(!response.ok)throw new Error(data.detail||'Unable to load maintenance history');
    maintenanceHistoryRender(data);
  }catch(error){notice('maintenanceHistoryNotice',error.message,'bad')}
}
async function maintenanceScanPause(){
  try{
    const response=await fetch('/api/scan/pause',{method:'POST'});
    const data=await response.json();if(!response.ok)throw new Error(data.detail||'Unable to pause full scan');
    notice('maintenanceScanNotice','Pause requested. The scan will stop cleanly at the next checkpoint.','good');
    await maintenanceHistoryLoad();
  }catch(error){notice('maintenanceScanNotice',error.message,'bad')}
}
async function maintenanceScanResume(){
  try{
    const response=await fetch('/api/scan/resume',{method:'POST'});
    const data=await response.json();if(!response.ok)throw new Error(data.detail||'Unable to resume full scan');
    notice('maintenanceScanNotice','Full scan resume queued. Unchanged indexed FLACs will be skipped while the complete traversal is rebuilt.','good');
    setTimeout(()=>maintenanceHistoryLoad(),300);
  }catch(error){notice('maintenanceScanNotice',error.message,'bad')}
}
async function maintenanceRecoveryRecheck(){
  const button=$('maintenanceRecheckRecovery');
  button.disabled=true;
  const previous=button.textContent;
  button.textContent='Rechecking…';
  try{
    const response=await fetch('/api/maintenance/recovery/recheck',{method:'POST'});
    const data=await response.json();if(!response.ok)throw new Error(data.detail||'Unable to recheck recovery state');
    const summary=data.summary||{};
    notice('maintenanceRecoveryNotice',data.safe_for_conversion?'Recovery recheck completed. No recovery blocker remains.':`Recovery recheck completed, but ${Number(summary.manual_attention||0)} manual-attention item(s) and ${Number(summary.errors||0)} recovery error(s) remain.` ,data.safe_for_conversion?'good':'bad');
    await maintenanceHistoryLoad();await loadStatus();
  }catch(error){notice('maintenanceRecoveryNotice',error.message,'bad')}
  finally{button.textContent=previous;button.disabled=false}
}
async function maintenanceHistoryClear(){
  const message='Clear all terminal conversion history, including retained failure/error records? Queued, paused and interrupted jobs will be preserved.';
  if(!confirm(message))return;
  try{
    const response=await fetch('/api/maintenance/history/clear',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({confirmed:true})});
    const data=await response.json();if(!response.ok)throw new Error(data.detail||'Unable to clear conversion history');
    notice('maintenanceHistoryNotice',`Cleared ${Number(data.deleted_jobs||0).toLocaleString()} terminal jobs. Resumable jobs were preserved.`,'good');
    await maintenanceHistoryLoad();await loadHistory();
  }catch(error){notice('maintenanceHistoryNotice',error.message,'bad')}
}

maintenanceScanInstall();maintenanceRecoveryInstall();maintenanceHistoryInstall();
const maintenanceHistoryBaseLoad=loadMaintenance;
loadMaintenance=async function(){await maintenanceHistoryBaseLoad();await maintenanceHistoryLoad()};
$('refreshMaintenance').onclick=loadMaintenance;