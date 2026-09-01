const SOURCE_RATE_FILTER_KEY='sox-resampler-source-rate-filters';

activeRates=function(){
  const rates=[];
  if($('r882')?.checked)rates.push(88200);
  if($('r96')?.checked)rates.push(96000);
  if($('r1764')?.checked)rates.push(176400);
  if($('r192')?.checked)rates.push(192000);
  return rates;
};

function saveSourceRateFilters(){
  localStorage.setItem(SOURCE_RATE_FILTER_KEY,JSON.stringify({
    r882:Boolean($('r882')?.checked),
    r96:Boolean($('r96')?.checked),
    r1764:Boolean($('r1764')?.checked),
    r192:Boolean($('r192')?.checked),
    above48:Boolean($('above48')?.checked),
  }));
}
function loadSourceRateFilters(){
  let saved=null;
  try{saved=JSON.parse(localStorage.getItem(SOURCE_RATE_FILTER_KEY)||'null')}catch(e){saved=null}
  if(!saved||typeof saved!=='object')return false;
  for(const id of ['r882','r96','r1764','r192','above48']){
    if($(id)&&typeof saved[id]==='boolean')$(id).checked=saved[id];
  }
  return true;
}

for(const id of ['r882','r1764']){
  const input=$(id);
  if(input)input.addEventListener('change',()=>{resetAck();loadCandidates()});
}
for(const id of ['r882','r96','r1764','r192','above48']){
  const input=$(id);
  if(input)input.addEventListener('change',saveSourceRateFilters);
}

function installSelectionTrayEstimates(){
  const tray=$('tray');
  if(!tray)return;
  const spacer=tray.querySelector('.spacer');
  if(!$('selectedWarnings')){
    const warnings=document.createElement('span');
    warnings.id='selectedWarnings';warnings.className='muted';
    spacer?tray.insertBefore(warnings,spacer):tray.appendChild(warnings);
  }
  if(!$('selectedSavings')){
    const savings=document.createElement('span');
    savings.id='selectedSavings';savings.className='muted';
    spacer?tray.insertBefore(savings,spacer):tray.appendChild(savings);
  }
}

const sourceRateBaseUpdateTray=updateTray;
updateTray=function(){
  sourceRateBaseUpdateTray();
  installSelectionTrayEstimates();
  const albums=[...state.selected.values()];
  const warningAlbums=albums.filter(album=>(album.warnings||[]).length>0).length;
  const estimatedSavings=albums.reduce((total,album)=>total+Number(album.estimated_savings_48k_bytes||0),0);
  $('selectedWarnings').textContent=`${warningAlbums} warning album${warningAlbums===1?'':'s'}`;
  $('selectedSavings').textContent=`${fmtBytes(estimatedSavings)} est. savings @ 48 kHz`;
};

function installSavingsSort(){
  const select=$('sortFilter');
  if(!select||[...select.options].some(option=>option.value==='savings'))return;
  const option=document.createElement('option');
  option.value='savings';option.textContent='Estimated savings';
  const recent=[...select.options].find(item=>item.value==='recent');
  if(recent)select.insertBefore(option,recent);else select.appendChild(option);
  if(localStorage.getItem('sox-resampler-library-sort')==='savings')select.value='savings';
}

const sourceRateBaseFiltered=filtered;
filtered=function(){
  const rows=sourceRateBaseFiltered();
  if($('sortFilter')?.value!=='savings')return rows;
  return [...rows].sort((a,b)=>Number(b.estimated_savings_48k_bytes||0)-Number(a.estimated_savings_48k_bytes||0));
};

openHighRateCandidates=function(){
  if($('r882'))$('r882').checked=false;
  $('r96').checked=true;
  if($('r1764'))$('r1764').checked=false;
  $('r192').checked=true;
  $('above48').checked=false;
  $('healthFilter').value='convertible';
  $('recentFilter').value='all';
  saveLibraryFilters();
  saveSourceRateFilters();
  resetAck();
  loadCandidates();
  showView('library');
};

const restoredSourceRateFilters=loadSourceRateFilters();
installSelectionTrayEstimates();
installSavingsSort();
$('homeOpenCandidates').onclick=openHighRateCandidates;
render();
if(restoredSourceRateFilters)loadCandidates();
if(typeof loadUiAddon==='function')loadUiAddon('/static/job-events.js');