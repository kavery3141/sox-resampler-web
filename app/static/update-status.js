(function installUpdateStatusStyles(){
  if(document.querySelector('style[data-update-status]'))return;
  const style=document.createElement('style');
  style.dataset.updateStatus='1';
  style.textContent='.updateStatusGrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-top:12px}.updateStatusGrid .metric{min-width:0}.updateReleaseLink{display:inline-flex;align-items:center;min-height:32px}.updateStatusActions{display:flex;align-items:center;gap:10px;flex-wrap:wrap}';
  document.head.appendChild(style);
})();

function updateStatusInstall(){
  if($('maintenanceUpdateCard'))return;
  const maintenance=$('maintenanceView');
  if(!maintenance)return;
  const versions=[...maintenance.querySelectorAll('.card')].find(card=>card.textContent.includes('Versions and health'));
  const card=document.createElement('section');
  card.id='maintenanceUpdateCard';card.className='card';card.style.marginTop='14px';
  card.innerHTML=`
    <div class="sectionTitle"><div><h3 style="margin:0">Update Status</h3><div class="muted">Checks published GitHub releases only. Updates are never installed automatically.</div></div><span class="spacer"></span><button id="maintenanceCheckUpdate">Check Now</button></div>
    <div id="maintenanceUpdateMetrics" class="updateStatusGrid"></div>
    <div id="maintenanceUpdateDetail" class="muted" style="margin-top:10px"></div>`;
  if(versions)versions.insertAdjacentElement('afterend',card);else maintenance.appendChild(card);
  $('maintenanceCheckUpdate').onclick=()=>loadMaintenanceUpdate(true);
}

function updateStatusLabel(data){
  if(data.comparison_status==='update-available')return 'Update available';
  if(data.comparison_status==='up-to-date')return 'Up to date';
  if(data.comparison_status==='unknown')return 'Version comparison unavailable';
  return 'Check unavailable';
}

function renderMaintenanceUpdate(data){
  updateStatusInstall();
  const current=data.current_version||'Unknown';
  const latest=data.latest_version||'No published release';
  const state=updateStatusLabel(data);
  $('maintenanceUpdateMetrics').innerHTML=`<div class="card metric"><span>Current</span><strong>${esc(current)}</strong></div><div class="card metric"><span>Latest release</span><strong>${esc(latest)}</strong></div><div class="card metric"><span>Status</span><strong>${esc(state)}</strong></div><div class="card metric"><span>Automatic install</span><strong>Disabled</strong></div>`;
  const detail=$('maintenanceUpdateDetail');
  const checked=data.checked_at?`Checked ${fmtTime(data.checked_at)}.`:'';
  const reason=data.reason?` ${data.reason}`:'';
  const link=data.release_url?` <a class="updateReleaseLink" href="${esc(data.release_url)}" target="_blank" rel="noopener noreferrer">View published release</a>`:'';
  detail.innerHTML=`${esc(checked+reason)}${link}`;
}

async function loadMaintenanceUpdate(force=false){
  updateStatusInstall();
  const button=$('maintenanceCheckUpdate');
  const oldText=button?.textContent;
  if(button){button.disabled=true;button.textContent='Checking…'}
  try{
    const response=await fetch(`/api/maintenance/update${force?'?force=true':''}`);
    const data=await response.json();
    if(!response.ok)throw new Error(data.detail||'Unable to check for updates');
    renderMaintenanceUpdate(data);
  }catch(error){
    $('maintenanceUpdateMetrics').innerHTML='<div class="card metric"><span>Status</span><strong>Check unavailable</strong></div>';
    $('maintenanceUpdateDetail').textContent=error.message;
  }finally{
    if(button){button.disabled=false;button.textContent=oldText||'Check Now'}
  }
}

updateStatusInstall();
const updateStatusBaseLoadMaintenance=loadMaintenance;
loadMaintenance=async function(){
  await updateStatusBaseLoadMaintenance();
  await loadMaintenanceUpdate(false);
};
if($('refreshMaintenance'))$('refreshMaintenance').onclick=loadMaintenance;
