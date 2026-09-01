const APPEARANCE_THEME_KEY='sox-resampler-theme';
const APPEARANCE_DENSITY_KEY='sox-resampler-density';

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
  resetAck();loadCandidates();showView('library');
}

$('navHome').onclick=()=>showView('home');
$('homeOpenCandidates').onclick=openHighRateCandidates;
$('themeSelect').onchange=saveAppearance;
$('densitySelect').onchange=saveAppearance;
applyAppearance();
if(window.matchMedia){window.matchMedia('(prefers-color-scheme: light)').addEventListener('change',()=>{if((localStorage.getItem(APPEARANCE_THEME_KEY)||'system')==='system')applyAppearance()})}
loadHome();
