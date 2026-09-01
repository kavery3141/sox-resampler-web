(function installMaintenanceHistoryStyles(){
  if(document.querySelector('link[data-maint-history]'))return;
  const link=document.createElement('link');link.rel='stylesheet';link.href='/static/maintenance-history.css';link.dataset.maintHistory='1';document.head.appendChild(link);
})();

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
  if(event.event_type==='storage_settings_changed')return 'storage safety settings changed';
  if(event.event_type==='read_only_mode_changed')return detail.enabled?'read-only mode enabled':'read-only mode disabled';
  return '';
}
function maintenanceHistoryRender(data){
  maintenanceHistoryInstall();
  const history=data.history||{};const logs=data.logs||{};
  $('maintenanceHistoryMetrics').innerHTML=`<div class="card metric"><span>Total jobs</span><strong>${Number(history.total_jobs||0).toLocaleString()}</strong></div><div class="card metric"><span>Terminal</span><strong>${Number(history.terminal_jobs||0).toLocaleString()}</strong></div><div class="card metric"><span>Protected errors</span><strong>${Number(history.protected_error_jobs||0).toLocaleString()}</strong></div><div class="card metric"><span>Resumable</span><strong>${Number(history.resumable_jobs||0).toLocaleString()}</strong></div><div class="card metric"><span>Retention</span><strong>${Number(history.retention_days||180)} days</strong></div>`;
  const approxCap=(Number(logs.active_max_bytes||0)*(Number(logs.rotated_files||0)+1));
  $('maintenanceLogDetail').textContent=`${fmtBytes(logs.total_bytes||0)} currently stored · 10 MB active file + ${Number(logs.rotated_files||0)} rotated files · approximately ${fmtBytes(approxCap)} maximum`;
  const events=data.maintenance_events||[];
  $('maintenanceEvents').innerHTML=events.length?events.map(event=>`<div class="maintenanceEvent"><span>${esc(fmtTime(event.occurred_at))}</span><strong>${esc(String(event.event_type||'').replaceAll('_',' '))}</strong><span>${esc(maintenanceEventDetail(event))}</span></div>`).join(''):'No maintenance events recorded yet.';
}
async function maintenanceHistoryLoad(){
  maintenanceHistoryInstall();
  try{
    const response=await fetch('/api/maintenance/status');
    const data=await response.json();if(!response.ok)throw new Error(data.detail||'Unable to load maintenance history');
    maintenanceHistoryRender(data);
  }catch(error){notice('maintenanceHistoryNotice',error.message,'bad')}
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

maintenanceHistoryInstall();
const maintenanceHistoryBaseLoad=loadMaintenance;
loadMaintenance=async function(){await maintenanceHistoryBaseLoad();await maintenanceHistoryLoad()};
$('refreshMaintenance').onclick=loadMaintenance;
