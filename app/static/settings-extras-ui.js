function settingsExtrasInstall(){
  if($('dailyScanSettingsCard'))return;
  const view=$('settingsView');
  if(!view)return;
  const cards=[...view.querySelectorAll(':scope > .card')];
  const appearance=cards[0]||null;

  const schedule=document.createElement('section');
  schedule.id='dailyScanSettingsCard';
  schedule.className='card';
  schedule.style.marginTop='14px';
  schedule.innerHTML=`
    <h3 style="margin-top:0">Daily discovery scan</h3>
    <div class="muted" style="margin-bottom:12px">The scheduled scan only refreshes the local index; it never starts conversion. If conversion or another scan is active at the scheduled time, the daily scan retries after 30 minutes.</div>
    <div class="settingsExtrasRow">
      <label>Daily scan time<input id="dailyScanTime" type="time" step="60" value="10:00"></label>
      <div><span class="muted">Timezone</span><strong id="dailyScanTimezone">—</strong></div>
      <div><span class="muted">Next scheduled run</span><strong id="dailyScanNext">—</strong></div>
    </div>
    <div class="toolbar" style="margin-top:14px"><button id="saveDailyScan" class="primary">Save Scan Schedule</button></div>
    <div id="dailyScanNotice" class="notice hidden"></div>`;
  if(appearance)appearance.insertAdjacentElement('afterend',schedule);else view.appendChild(schedule);

  const reset=document.createElement('section');
  reset.id='resetDefaultsCard';
  reset.className='card';
  reset.style.marginTop='14px';
  reset.innerHTML=`
    <h3 style="margin-top:0">Reset to Defaults</h3>
    <div class="muted">Restores app and browser preference defaults, including the 10 GB free-space reserve, disabled conversion CPU cap, 10:00 daily scan time, System theme, Comfortable density, the normal 96/192 kHz source filter and the built-in default resampler preset. Library index data, exclusions, history, logs and custom presets are preserved.</div>
    <div class="toolbar" style="margin-top:14px"><button id="resetAppDefaults" class="danger">Reset App Defaults</button></div>
    <div id="resetDefaultsNotice" class="notice hidden"></div>`;
  view.appendChild(reset);

  const style=document.createElement('style');
  style.dataset.settingsExtras='1';
  style.textContent=`
    .settingsExtrasRow{display:grid;grid-template-columns:minmax(180px,.7fr) minmax(220px,1fr) minmax(250px,1.2fr);gap:14px;align-items:end}
    .settingsExtrasRow>div{display:grid;gap:6px}.settingsExtrasRow label{display:grid;gap:6px}
    @media(max-width:850px){.settingsExtrasRow{grid-template-columns:1fr}}
  `;
  document.head.appendChild(style);

  $('saveDailyScan').onclick=settingsExtrasSaveSchedule;
  $('resetAppDefaults').onclick=settingsExtrasResetDefaults;
}

async function settingsExtrasLoadSchedule(){
  settingsExtrasInstall();
  try{
    const r=await fetch('/api/settings/schedule');
    const data=await r.json();
    if(!r.ok)throw new Error(data.detail||'Unable to load daily scan schedule');
    $('dailyScanTime').value=data.daily_scan_time||'10:00';
    $('dailyScanTimezone').textContent=data.timezone||'—';
    const next=data.deferred_next_run_time||data.next_run_time;
    $('dailyScanNext').textContent=next?fmtTime(next):'Pending scheduler start';
    $('dailyScanNext').title=data.deferred_next_run_time?'A deferred busy-time retry is scheduled':'Normal daily schedule';
  }catch(error){notice('dailyScanNotice',error.message,'bad')}
}

async function settingsExtrasSaveSchedule(){
  const value=$('dailyScanTime').value;
  try{
    const r=await fetch('/api/settings/schedule',{
      method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({daily_scan_time:value}),
    });
    const data=await r.json();
    if(!r.ok)throw new Error(data.detail||'Unable to save daily scan schedule');
    notice('dailyScanNotice',`Daily discovery scan set to ${data.daily_scan_time} ${data.timezone}.`,'good');
    await settingsExtrasLoadSchedule();
  }catch(error){notice('dailyScanNotice',error.message,'bad')}
}

function settingsExtrasClearBrowserDefaults(){
  for(const key of [
    'sox-resampler-theme',
    'sox-resampler-density',
    'sox-resampler-library-health',
    'sox-resampler-library-recent',
    'sox-resampler-library-sort',
    'sox-resampler-source-rate-filters',
    'sox-resampler-last-preset',
    'sox-resampler-cover-thumbnails',
  ])localStorage.removeItem(key);
  selectedWarningFocus=false;
  if($('r882'))$('r882').checked=false;
  if($('r96'))$('r96').checked=true;
  if($('r1764'))$('r1764').checked=false;
  if($('r192'))$('r192').checked=true;
  if($('above48'))$('above48').checked=false;
  if($('healthFilter'))$('healthFilter').value='convertible';
  if($('recentFilter'))$('recentFilter').value='all';
  if($('sortFilter'))$('sortFilter').value='albumartist';
  if($('workerSelect'))$('workerSelect').value='1';
  if(typeof applyAppearance==='function')applyAppearance();
  if(typeof applyAlbumThumbnailPreference==='function')applyAlbumThumbnailPreference();
  resetAck();
}

async function settingsExtrasResetDefaults(){
  const first='Reset app and browser preferences to their defaults? Library index data, exclusions, history, logs and custom presets will be preserved.';
  if(!confirm(first))return;
  let confirmReadOnly=false;
  if(state.readOnly){
    confirmReadOnly=confirm('Read-only Scan Mode is enabled. Resetting defaults will disable it and restore conversion capability. Continue?');
    if(!confirmReadOnly)return;
  }
  try{
    const r=await fetch('/api/settings/reset-defaults',{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({confirmed:true,confirmed_disable_read_only:confirmReadOnly}),
    });
    const data=await r.json();
    if(!r.ok)throw new Error(data.detail||'Unable to reset defaults');
    settingsExtrasClearBrowserDefaults();
    notice('resetDefaultsNotice','Defaults restored. Exclusions, index data, history, logs and custom presets were preserved.','good');
    await Promise.all([loadSettings(),loadStatus(),loadProfiles(),loadCandidates(),settingsExtrasLoadSchedule()]);
  }catch(error){notice('resetDefaultsNotice',error.message,'bad')}
}

settingsExtrasInstall();
const settingsExtrasBaseLoadSettings=loadSettings;
loadSettings=async function(){
  await settingsExtrasBaseLoadSettings();
  await settingsExtrasLoadSchedule();
};
