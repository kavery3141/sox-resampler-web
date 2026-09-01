function artworkMaintenanceInstall(){
  if($('artworkCacheCard'))return;
  const view=$('maintenanceView');
  if(!view)return;
  const cards=[...view.querySelectorAll(':scope > .card')];
  const versions=cards.find(card=>card.textContent?.includes('Versions and health'))||cards[cards.length-1]||null;
  const card=document.createElement('section');
  card.id='artworkCacheCard';
  card.className='card';
  card.style.marginTop='14px';
  card.innerHTML=`
    <div class="sectionTitle"><div><h3 style="margin:0">Album artwork cache</h3><div class="muted">Thumbnails are generated during library scans and served only from the local app dataset. The browser never reads album artwork directly from the music mount.</div></div></div>
    <div id="artworkCacheMetrics" class="summary artworkCacheMetrics"></div>
    <div id="artworkCacheNotice" class="notice hidden"></div>`;
  if(versions)versions.insertAdjacentElement('beforebegin',card);else view.appendChild(card);

  const style=document.createElement('style');
  style.dataset.artworkMaintenance='1';
  style.textContent='.artworkCacheMetrics{margin-top:14px}.artworkCacheMetrics .metric{min-width:140px}';
  document.head.appendChild(style);
}

async function artworkMaintenanceLoad(){
  artworkMaintenanceInstall();
  try{
    const r=await fetch('/api/artwork/status');
    const data=await r.json();
    if(!r.ok)throw new Error(data.detail||'Unable to load artwork cache status');
    $('artworkCacheMetrics').innerHTML=`<div class="card metric"><span>Cached</span><strong>${Number(data.ready||0).toLocaleString()}</strong></div><div class="card metric"><span>No artwork</span><strong>${Number(data.missing||0).toLocaleString()}</strong></div><div class="card metric"><span>Cache errors</span><strong>${Number(data.error||0).toLocaleString()}</strong></div><div class="card metric"><span>Indexed folders</span><strong>${Number(data.total||0).toLocaleString()}</strong></div>`;
    const errors=Number(data.error||0);
    if(errors)notice('artworkCacheNotice',`${errors.toLocaleString()} album folder${errors===1?' has':'s have'} an artwork-cache error. An incremental rescan retries current local artwork sources.`,'warn');
    else $('artworkCacheNotice').classList.add('hidden');
  }catch(error){notice('artworkCacheNotice',error.message,'bad')}
}

artworkMaintenanceInstall();
const artworkMaintenanceBaseLoad=loadMaintenance;
loadMaintenance=async function(){
  await artworkMaintenanceBaseLoad();
  await artworkMaintenanceLoad();
};
