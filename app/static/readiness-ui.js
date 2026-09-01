(function installReadinessStyles(){
  if(document.querySelector('style[data-readiness-ui]'))return;
  const style=document.createElement('style');
  style.dataset.readinessUi='1';
  style.textContent=`
    .readinessGrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(155px,1fr));gap:10px;margin-top:14px}
    .readinessGrid .metric{min-width:0}
    .readinessDetails{display:grid;grid-template-columns:minmax(150px,.55fr) minmax(0,1.45fr);gap:8px 14px;margin-top:14px}
    .readinessDetails code{overflow-wrap:anywhere;white-space:normal}
    .readinessBlockers{margin-top:12px}
    .readinessBlockers div+div{margin-top:5px}
    @media(max-width:720px){.readinessDetails{grid-template-columns:1fr}.readinessDetails .muted{margin-top:6px}}
  `;
  document.head.appendChild(style);
})();

function readinessInstall(){
  if($('deploymentReadinessCard'))return;
  const view=$('maintenanceView');
  if(!view)return;
  const card=document.createElement('section');
  card.id='deploymentReadinessCard';
  card.className='card';
  card.style.marginTop='14px';
  card.innerHTML=`
    <div class="sectionTitle">
      <div><h3 style="margin:0">Deployment Readiness</h3><div class="muted">Passive runtime checks for the TrueNAS deployment. This panel never scans, converts, replaces, or writes music files.</div></div>
      <span class="spacer"></span><button id="refreshReadiness">Refresh Readiness</button>
    </div>
    <div id="readinessMetrics" class="readinessGrid"></div>
    <div id="readinessDetails" class="readinessDetails"></div>
    <div id="readinessNotice" class="notice hidden readinessBlockers"></div>`;

  const recovery=$('maintenanceRecoveryCard');
  const scan=$('maintenanceScanCard');
  if(recovery)recovery.insertAdjacentElement('afterend',card);
  else if(scan)scan.insertAdjacentElement('afterend',card);
  else{
    const first=view.querySelector(':scope > .card');
    if(first)first.insertAdjacentElement('afterend',card);else view.appendChild(card);
  }
  $('refreshReadiness').onclick=readinessLoad;
}

function readinessBool(ok,good='Ready',bad='Blocked'){
  return `<strong class="statusPill ${ok?'completed':'interrupted'}">${esc(ok?good:bad)}</strong>`;
}

function readinessRecoveryBlocked(items){
  return (items||[]).some(item=>item?.action==='manual_attention'||String(item?.action||'').startsWith('recovery_error'));
}

function readinessRender(health,maintenance){
  readinessInstall();
  const music=health.music_root||{};
  const data=health.data_root||{};
  const zfs=health.zfs||{};
  const tools=health.tools||{};
  const identity=maintenance.runtime_identity||{};
  const recovery=health.transaction_recovery||[];
  const recoveryBlocked=readinessRecoveryBlocked(recovery);
  const musicReady=Boolean(music.exists&&music.readable&&music.writable);
  const dataReady=Boolean(data.exists&&data.writable);
  const dbReady=Boolean(health.database?.ok);
  const ultraReady=Boolean(tools.sox_ultra_37);
  const flacReady=Boolean(tools.flac);

  $('readinessMetrics').innerHTML=`
    <div class="card metric"><span>Service</span>${readinessBool(health.status==='ok','Healthy','Degraded')}</div>
    <div class="card metric"><span>Conversion</span>${readinessBool(Boolean(health.conversion_ready),'Ready','Blocked')}</div>
    <div class="card metric"><span>Music mount</span>${readinessBool(musicReady,'Read / write','Not ready')}</div>
    <div class="card metric"><span>App data</span>${readinessBool(dataReady,'Writable','Not ready')}</div>
    <div class="card metric"><span>ZFS pool</span>${readinessBool(Boolean(zfs.ok),zfs.state||'ONLINE','Blocked')}</div>
    <div class="card metric"><span>Recovery</span>${readinessBool(!recoveryBlocked,'Clear','Attention')}</div>
    <div class="card metric"><span>Ultra 37 backend</span>${readinessBool(ultraReady,'Available','Missing')}</div>
    <div class="card metric"><span>FLAC verifier</span>${readinessBool(flacReady,'Available','Missing')}</div>`;

  const cpuLimit=health.resource_control?.enabled?`${health.resource_control.cpu_limit_percent}% per SoX worker`:'Disabled';
  const uid=identity.uid??'—',gid=identity.gid??'—';
  $('readinessDetails').innerHTML=`
    <span class="muted">TrueNAS music path</span><code>${esc(music.host_path||'—')}</code>
    <span class="muted">Container music path</span><code>${esc(music.path||'—')}</code>
    <span class="muted">App data path</span><code>${esc(data.path||maintenance.data_root||'—')}</code>
    <span class="muted">Runtime identity</span><span>UID ${esc(uid)} / GID ${esc(gid)}</span>
    <span class="muted">ZFS health source</span><span>${esc(zfs.source||'Unavailable')}${zfs.detail?` · ${esc(zfs.detail)}`:''}</span>
    <span class="muted">Database</span><span>${dbReady?'Available':'Unavailable'} · schema ${esc(health.db_schema??maintenance.db_schema??'—')}</span>
    <span class="muted">CPU limit</span><span>${esc(cpuLimit)}</span>
    <span class="muted">Read-only Scan Mode</span><span>${health.read_only_mode?'Enabled — conversion intentionally disabled':'Disabled'}</span>`;

  const blockers=health.conversion_blockers||[];
  const notice=$('readinessNotice');
  notice.classList.remove('hidden','good','warn','bad');
  if(!blockers.length){
    notice.classList.add('good');
    notice.textContent='Runtime checks currently permit a manually reviewed conversion batch to start.';
  }else{
    const intentional=blockers.length===1&&blockers[0]==='Read-only Scan Mode is enabled';
    notice.classList.add(intentional?'warn':'bad');
    notice.innerHTML=`<strong>${intentional?'Conversion is intentionally disabled.':'Conversion readiness blockers:'}</strong>${blockers.map(item=>`<div>${esc(item)}</div>`).join('')}`;
  }
}

async function readinessLoad(){
  readinessInstall();
  const button=$('refreshReadiness');
  const old=button?.textContent;
  if(button){button.disabled=true;button.textContent='Checking…'}
  try{
    const [healthResponse,maintenanceResponse]=await Promise.all([
      fetch('/health'),
      fetch('/api/maintenance/status'),
    ]);
    const health=await healthResponse.json();
    const maintenance=await maintenanceResponse.json();
    if(!healthResponse.ok)throw new Error(health.detail||'Unable to load runtime health');
    if(!maintenanceResponse.ok)throw new Error(maintenance.detail||'Unable to load maintenance status');
    readinessRender(health,maintenance);
  }catch(error){
    const notice=$('readinessNotice');
    notice.className='notice bad readinessBlockers';
    notice.textContent=error.message;
  }finally{
    if(button){button.disabled=false;button.textContent=old||'Refresh Readiness'}
  }
}

readinessInstall();
const readinessBaseLoadMaintenance=loadMaintenance;
loadMaintenance=async function(){
  await readinessBaseLoadMaintenance();
  await readinessLoad();
};
if($('refreshMaintenance'))$('refreshMaintenance').onclick=loadMaintenance;
