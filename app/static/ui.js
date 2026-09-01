const APPEARANCE_THEME_KEY='sox-resampler-theme';
const APPEARANCE_DENSITY_KEY='sox-resampler-density';
const LIBRARY_HEALTH_KEY='sox-resampler-library-health';
const LIBRARY_RECENT_KEY='sox-resampler-library-recent';
const LIBRARY_SORT_KEY='sox-resampler-library-sort';
const openAlbumDetails=new Set();

function effectiveTheme(){
  const pref=localStorage.getItem(APPEARANCE_THEME_KEY)||'system';
  if(pref==='light'||pref==='dark')return pref;
  return window.matchMedia&&window.matchMedia('(prefers-color-scheme: light)').matches?'light':'dark';
}
function applyAppearance(){
  const themePref=localStorage.getItem(APPEARANCE_THEME_KEY)||'system';
  const density=localStorage.getItem(APPEARANCE_DENSITY_KEY)||'comfortable';
  document.body.dataset.theme=effectiveTheme();
  document.body.dataset.density=density;
  const themeSelect=$('themeSelect');if(themeSelect)themeSelect.value=themePref;
  const densitySelect=$('densitySelect');if(densitySelect)densitySelect.value=density;
}
function saveAppearance(){
  const theme=$('themeSelect')?.value||'system';
  const density=$('densitySelect')?.value||'comfortable';
  localStorage.setItem(APPEARANCE_THEME_KEY,theme);
  localStorage.setItem(APPEARANCE_DENSITY_KEY,density);
  applyAppearance();
}

const baseShowView=showView;
showView=function(which){
  const home=$('homeView');
  if(which==='home'){
    for(const name of ['library','convert','history','settings','maintenance'])$(`${name}View`).classList.add('hidden');
    home.classList.remove('hidden');
    for(const name of ['Home','Library','Convert','History','Settings','Maintenance'])$(`nav${name}`).classList.toggle('active',name==='Home');
    loadHome();
    return;
  }
  home.classList.add('hidden');
  baseShowView(which);
  $('navHome').classList.remove('active');
};

async function loadHome(){
  try{
    const params=new URLSearchParams();params.append('rates','96000');params.append('rates','192000');
    const [status,candidates,jobs]=await Promise.all([
      fetch('/api/status').then(r=>{if(!r.ok)throw new Error('Unable to load app status');return r.json()}),
      fetch('/api/library/candidates?'+params).then(r=>{if(!r.ok)throw new Error('Unable to load candidates');return r.json()}),
      fetch('/api/convert/jobs?limit=50').then(r=>{if(!r.ok)throw new Error('Unable to load job history');return r.json()}),
    ]);
    const albums=candidates.albums||[];
    const blocked=albums.filter(a=>!a.selectable).length;
    const warnings=albums.filter(a=>(a.warnings||[]).length>0&&a.selectable).length;
    const interrupted=(jobs.jobs||[]).filter(j=>j.status==='interrupted').length;
    $('homeCandidateCount').textContent=albums.length.toLocaleString();
    $('homeBlockedCount').textContent=blocked.toLocaleString();
    $('homeWarningCount').textContent=warnings.toLocaleString();
    $('homeInterruptedCount').textContent=interrupted.toLocaleString();
    const scan=status.latest_scan||{};
    $('homeLastScan').textContent=scan.finished_at||scan.started_at||'Never';
    $('homeNasState').textContent=status.zfs?.ok?'Ready':'Blocked';
    $('homeNasState').className=`statusPill ${status.zfs?.ok?'completed':'interrupted'}`;
    $('homeFreeSpace').textContent=fmtBytes(status.free_bytes);
    $('homeReadOnly').textContent=status.read_only_mode?'Enabled':'Disabled';
    $('homeReadOnly').className=`statusPill ${status.read_only_mode?'paused':'completed'}`;

    const resumable=(jobs.jobs||[]).find(j=>['interrupted','paused'].includes(j.status));
    const card=$('homeInterruptedCard');
    card.classList.toggle('hidden',!resumable);
    if(resumable){
      $('homeInterruptedTitle').textContent=`Job ${resumable.id} — ${resumable.status}`;
      $('homeInterruptedDetail').textContent=`Preset: ${resumable.profile_id} · Created: ${fmtTime(resumable.created_at)}`;
      $('homeResumeJob').onclick=()=>watchJob(resumable.id,false);
    }
  }catch(e){
    notice('homeNotice',e.message,'bad');
  }
}

function openHighRateCandidates(){
  $('r96').checked=true;$('r192').checked=true;$('above48').checked=false;
  $('healthFilter').value='convertible';$('recentFilter').value='all';
  saveLibraryFilters();resetAck();loadCandidates();showView('library');
}

const baseFiltered=filtered;
filtered=function(){
  let rows=baseFiltered();
  const health=$('healthFilter')?.value||'convertible';
  if(health==='convertible')rows=rows.filter(a=>a.selectable);
  else if(health==='clean')rows=rows.filter(a=>a.selectable&&!(a.warnings||[]).length);
  else if(health==='warnings')rows=rows.filter(a=>a.selectable&&(a.warnings||[]).length>0);
  else if(health==='blocked')rows=rows.filter(a=>!a.selectable);

  const recent=$('recentFilter')?.value||'all';
  if(recent!=='all'){
    const days=Number(recent);const cutoff=Date.now()-days*86400000;
    rows=rows.filter(a=>{const t=Date.parse(a.first_seen||'');return Number.isFinite(t)&&t>=cutoff});
  }

  const sort=$('sortFilter')?.value||'albumartist';
  rows=[...rows].sort((a,b)=>{
    if(sort==='album')return String(a.album||'').localeCompare(String(b.album||''),undefined,{sensitivity:'base'});
    if(sort==='rate')return Math.max(...(b.source_rates||[0]))-Math.max(...(a.source_rates||[0]));
    if(sort==='size')return Number(b.matching_bytes||0)-Number(a.matching_bytes||0);
    if(sort==='recent')return Date.parse(b.first_seen||0)-Date.parse(a.first_seen||0);
    const aa=String(a.albumartist||'').localeCompare(String(b.albumartist||''),undefined,{sensitivity:'base'});
    return aa||String(a.album||'').localeCompare(String(b.album||''),undefined,{sensitivity:'base'});
  });
  return rows;
};

function loadLibraryFilters(){
  $('healthFilter').value=localStorage.getItem(LIBRARY_HEALTH_KEY)||'convertible';
  $('recentFilter').value=localStorage.getItem(LIBRARY_RECENT_KEY)||'all';
  $('sortFilter').value=localStorage.getItem(LIBRARY_SORT_KEY)||'albumartist';
}
function saveLibraryFilters(){
  localStorage.setItem(LIBRARY_HEALTH_KEY,$('healthFilter').value);
  localStorage.setItem(LIBRARY_RECENT_KEY,$('recentFilter').value);
  localStorage.setItem(LIBRARY_SORT_KEY,$('sortFilter').value);
}
function libraryFilterChanged(){saveLibraryFilters();render()}

function detailHtml(album){
  const release=(album.releasetypes||'').split(',').filter(Boolean).join(', ')||'Missing';
  const mbid=(album.mbids||'').split(',').filter(Boolean).join(', ')||'Missing';
  const channels=(album.channels||'').split(',').filter(Boolean).map(x=>`${x} ch`).join(', ')||'Unknown';
  const rg=(album.warnings||[]).includes('ReplayGain incomplete')?'Incomplete':'Complete';
  const relative=String(album.folder||'').replace(/^\/music\/?/,'');
  return `<div class="albumDetailGrid"><span class="muted">ALBUMARTIST</span><span>${esc(album.albumartist||'Missing')}</span><span class="muted">ALBUM</span><span>${esc(album.album||'Missing')}</span><span class="muted">RELEASETYPE</span><span>${esc(release)}</span><span class="muted">MUSICBRAINZ_ALBUMID</span><span class="copyLine"><code>${esc(mbid)}</code><button class="copyMbid">Copy</button></span><span class="muted">ReplayGain</span><span>${esc(rg)}</span><span class="muted">Channels</span><span>${esc(channels)}</span><span class="muted">First seen</span><span>${esc(fmtTime(album.first_seen)||'Unknown')}</span><span class="muted">Folder</span><span class="copyLine"><code>${esc(album.folder||'')}</code><button class="copyPath">Copy Path</button></span><span class="muted">Relative path</span><span><code>${esc(relative)}</code></span></div>`;
}
function toggleAlbumDetail(key,force=null){
  const open=force===null?!openAlbumDetails.has(key):Boolean(force);
  if(open)openAlbumDetails.add(key);else openAlbumDetails.delete(key);
  const detail=document.querySelector(`.albumDetail[data-key="${CSS.escape(encodeURIComponent(key))}"]`);
  const button=document.querySelector(`.detailsBtn[data-key="${CSS.escape(encodeURIComponent(key))}"]`);
  if(detail)detail.classList.toggle('hidden',!open);
  if(button)button.textContent=open?'Hide Details':'Details';
}
function decorateRows(){
  const rows=[...document.querySelectorAll('#results .row[data-key]')];
  rows.forEach((row,index)=>{
    const key=decodeURIComponent(row.dataset.key);const album=state.albums.find(a=>selectedKey(a)===key);if(!album)return;
    const albumCell=row.children[1];
    const button=document.createElement('button');button.type='button';button.className='detailsBtn';button.dataset.key=encodeURIComponent(key);button.textContent=openAlbumDetails.has(key)?'Hide Details':'Details';button.onclick=event=>{event.stopPropagation();toggleAlbumDetail(key)};albumCell.appendChild(button);
    const detail=document.createElement('div');detail.className='albumDetail'+(openAlbumDetails.has(key)?'':' hidden');detail.dataset.key=encodeURIComponent(key);detail.innerHTML=detailHtml(album);row.after(detail);
    detail.querySelector('.copyPath').onclick=()=>navigator.clipboard?.writeText(album.folder||'');
    detail.querySelector('.copyMbid').onclick=()=>navigator.clipboard?.writeText((album.mbids||'').split(',').filter(Boolean).join(', '));
    row.tabIndex=0;
    row.addEventListener('keydown',event=>{
      if(event.key==='ArrowDown'||event.key==='ArrowUp'){
        event.preventDefault();const next=index+(event.key==='ArrowDown'?1:-1);if(rows[next])rows[next].focus();
      }else if(event.key===' '){
        const check=row.querySelector('.albumCheck');if(check&&!check.disabled){event.preventDefault();check.checked=!check.checked;check.dispatchEvent(new Event('change',{bubbles:true}))}
      }else if(event.key==='Enter'){event.preventDefault();toggleAlbumDetail(key)}
    });
  });
}
const baseRender=render;
render=function(){baseRender();decorateRows()};

function setAllVisibleDetails(open){for(const album of filtered()){const key=selectedKey(album);if(open)openAlbumDetails.add(key);else openAlbumDetails.delete(key)}render()}
function editableTarget(target){return target&&['INPUT','TEXTAREA','SELECT'].includes(target.tagName)}
document.addEventListener('keydown',event=>{
  if((event.key==='/'||(event.ctrlKey&&event.key.toLowerCase()==='f'))&&!event.altKey&&!event.metaKey){
    if(!editableTarget(event.target)||event.ctrlKey){event.preventDefault();showView('library');$('textSearch').focus();$('textSearch').select()}
    return;
  }
  if(editableTarget(event.target)||event.ctrlKey||event.metaKey||event.altKey)return;
  if(event.key.toLowerCase()==='a')$('checkAll').click();
  else if(event.key.toLowerCase()==='n')$('uncheckAll').click();
});

$('navHome').onclick=()=>showView('home');
$('homeOpenCandidates').onclick=openHighRateCandidates;
$('themeSelect').onchange=saveAppearance;
$('densitySelect').onchange=saveAppearance;
$('healthFilter').onchange=libraryFilterChanged;
$('recentFilter').onchange=libraryFilterChanged;
$('sortFilter').onchange=libraryFilterChanged;
$('expandAll').onclick=()=>setAllVisibleDetails(true);
$('collapseAll').onclick=()=>setAllVisibleDetails(false);
applyAppearance();
loadLibraryFilters();
if(window.matchMedia){window.matchMedia('(prefers-color-scheme: light)').addEventListener('change',()=>{if((localStorage.getItem(APPEARANCE_THEME_KEY)||'system')==='system')applyAppearance()})}
loadHome();
render();

const issuesUiScript=document.createElement('script');
issuesUiScript.src='/static/issues-ui.js';
document.body.appendChild(issuesUiScript);
