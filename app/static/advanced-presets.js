const ADVANCED_LAST_PRESET_KEY='sox-resampler-last-preset';
const advancedState={override:null,dirty:false,importDocument:null,importPreview:null};

(function installAdvancedStyles(){
  if(document.querySelector('link[data-advanced-presets]'))return;
  const link=document.createElement('link');
  link.rel='stylesheet';
  link.href='/static/advanced-presets.css';
  link.dataset.advancedPresets='1';
  document.head.appendChild(link);
})();

function advancedSelectedProfile(){
  return (state.profiles||[]).find(profile=>profile.id===$('profileSelect').value)||null;
}
function advancedNumber(id){return Number($(id).value)}
function advancedBitDepth(){const value=$('advBitDepth').value;return value==='preserve'?'preserve':Number(value)}
function advancedDspPayload(){
  return {
    target_rate:advancedNumber('advTargetRate'),
    bit_depth:advancedBitDepth(),
    quality:$('advQuality').value,
    passband_percent:advancedNumber('advPassband'),
    phase_percent:advancedNumber('advPhase'),
    allow_aliasing:$('advAliasing').checked,
    flac_compression:advancedNumber('advCompression'),
    dither:$('advDither').value===''?null:$('advDither').value,
    headroom_db:advancedNumber('advHeadroom'),
  };
}
function advancedIdentityPayload(){
  return {
    name:$('advPresetName').value.trim(),
    description:$('advDescription').value.trim(),
    notes:$('advNotes').value.trim(),
  };
}
function advancedFullPayload(){return {...advancedIdentityPayload(),...advancedDspPayload()}}
function advancedEqual(a,b){return JSON.stringify(a)===JSON.stringify(b)}
function advancedBaseDsp(profile){
  return {
    target_rate:Number(profile.target_rate),
    bit_depth:profile.bit_depth,
    quality:profile.quality,
    passband_percent:Number(profile.passband_percent),
    phase_percent:Number(profile.phase_percent),
    allow_aliasing:Boolean(profile.allow_aliasing),
    flac_compression:Number(profile.flac_compression),
    dither:profile.dither??null,
    headroom_db:Number(profile.headroom_db||0),
  };
}
function advancedMessage(text,kind='info'){
  const box=$('advancedNotice');
  box.className=`notice ${kind}`;
  box.textContent=text;
  box.classList.remove('hidden');
}
function advancedClearMessage(){$('advancedNotice').classList.add('hidden')}
function advancedMarkChanged(){
  const profile=advancedSelectedProfile();if(!profile)return;
  const current=advancedDspPayload();
  advancedState.override=advancedEqual(current,advancedBaseDsp(profile))?null:current;
  advancedState.dirty=Boolean(advancedState.override);
  $('advancedDirty').classList.toggle('hidden',!advancedState.dirty);
  resetAck();
  if(advancedState.dirty)advancedMessage('Advanced DSP settings changed for this batch. Refresh Review before conversion.','warn');
  else advancedClearMessage();
  advancedUpdateWarnings();
}
function advancedUpdateWarnings(){
  const warnings=[];
  const bits=advancedBitDepth();
  const dither=$('advDither').value||'automatic TPDF';
  if(bits!=='preserve')warnings.push(`Target bit depth is ${bits}-bit. When this reduces source precision, ${dither==='none'?'dither is disabled':'dither will be applied'}.`);
  const target=advancedNumber('advTargetRate');
  if(target!==48000)warnings.push(`Target sample rate is ${Number(target).toLocaleString()} Hz instead of the normal 48 kHz workflow target.`);
  const headroom=advancedNumber('advHeadroom');
  if(headroom<0)warnings.push(`${Math.abs(headroom).toFixed(1)} dB headroom will be applied before resampling.`);
  $('advancedWarnings').classList.toggle('hidden',warnings.length===0);
  $('advancedWarnings').innerHTML=warnings.map(text=>`<div>${esc(text)}</div>`).join('');
}
function advancedLoadEditor(profile){
  if(!profile)return;
  $('advTargetRate').value=String(profile.target_rate);
  const bit=String(profile.bit_depth);
  if(![...$('advBitDepth').options].some(option=>option.value===bit)){
    const option=document.createElement('option');option.value=bit;option.textContent=`${bit}-bit`;$('advBitDepth').appendChild(option);
  }
  $('advBitDepth').value=bit;
  $('advQuality').value=profile.quality;
  $('advPassband').value=String(profile.passband_percent);
  $('advPhase').value=String(profile.phase_percent);
  $('advAliasing').checked=Boolean(profile.allow_aliasing);
  $('advCompression').value=String(profile.flac_compression);
  $('advDither').value=profile.dither??'';
  $('advHeadroom').value=String(profile.headroom_db||0);
  $('advPresetName').value=profile.read_only?`${profile.name} Copy`:profile.name;
  $('advDescription').value=profile.description||'';
  $('advNotes').value=profile.notes||'';
  $('advancedPresetKind').textContent=profile.read_only?'Built-in reference preset':'Custom preset';
  $('advancedPresetKind').className=`statusPill ${profile.read_only?'completed':'running'}`;
  $('advancedDescriptionText').textContent=profile.description||'No description.';
  $('updateCustomPreset').classList.toggle('hidden',Boolean(profile.read_only));
  $('deleteCustomPreset').classList.toggle('hidden',Boolean(profile.read_only));
  advancedState.override=null;advancedState.dirty=false;$('advancedDirty').classList.add('hidden');advancedClearMessage();advancedUpdateWarnings();
}

function advancedInstallPanel(){
  if($('advancedDspPanel'))return;
  const panel=document.createElement('details');
  panel.id='advancedDspPanel';
  panel.className='advancedPanel';
  panel.innerHTML=`
    <summary><strong>Advanced DSP & Presets</strong><span class="muted">Edit batch processing or manage custom presets</span></summary>
    <div class="advancedBody">
      <div class="advancedHeader"><div><span id="advancedPresetKind" class="statusPill">Preset</span><span id="advancedDirty" class="badge warn hidden">Unsaved batch override</span><div id="advancedDescriptionText" class="muted advancedDescription"></div></div></div>
      <div id="advancedWarnings" class="notice warn hidden"></div>
      <div class="advancedGrid">
        <label>Target sample rate (Hz)<input id="advTargetRate" type="number" min="8000" max="768000" step="1"></label>
        <label>Bit depth<select id="advBitDepth"><option value="preserve">Preserve source</option><option value="16">16-bit</option><option value="24">24-bit</option><option value="32">32-bit</option></select></label>
        <label>Quality<select id="advQuality"><option value="ultra-37">Ultra 37 (~222.8 dB)</option><option value="very-high">Very High</option><option value="high">High</option><option value="medium">Medium</option><option value="quick">Quick</option></select></label>
        <label>Passband (%)<input id="advPassband" type="number" min="0.1" max="99.7" step="0.1"></label>
        <label>Phase response (%)<input id="advPhase" type="number" min="0" max="100" step="1"></label>
        <label>FLAC compression<input id="advCompression" type="number" min="0" max="8" step="1"></label>
        <label>Dither<select id="advDither"><option value="">Automatic TPDF when reducing bit depth</option><option value="tpdf">TPDF</option><option value="shibata">Shibata noise-shaped</option><option value="none">Disabled</option></select></label>
        <label>Headroom (dB)<input id="advHeadroom" type="number" min="-30" max="0" step="0.1"></label>
        <label class="advancedCheck"><input id="advAliasing" type="checkbox">Allow aliasing / imaging</label>
      </div>
      <div style="margin-top:16px;padding-top:14px;border-top:1px solid var(--border)"><strong>Per-batch safety</strong><label class="advancedCheck" style="margin-top:10px"><input id="advSourcePreHash" type="checkbox">SHA-256 pre-hash each source FLAC before SoX</label><div class="muted" style="margin-top:6px">Disabled by default. This adds one full source-file read before conversion, is recorded with the job, and is never saved in DSP presets.</div></div>
      <div class="advancedActions"><button id="resetAdvanced">Reset to Selected Preset</button><button id="saveCustomPreset" class="primary">Save as Custom Preset</button><button id="updateCustomPreset" class="hidden">Update Custom Preset</button><button id="duplicatePreset">Duplicate Selected Preset</button><button id="exportPreset">Export JSON</button><button id="deleteCustomPreset" class="danger hidden">Delete Custom Preset</button></div>
      <details class="presetIdentity"><summary>Custom preset name, description and notes</summary><div class="advancedIdentityGrid"><label>Preset name<input id="advPresetName" type="text" maxlength="100"></label><label>Description<textarea id="advDescription" rows="3" maxlength="2000"></textarea></label><label>Notes<textarea id="advNotes" rows="3" maxlength="4000"></textarea></label></div></details>
      <div class="advancedImport"><div><strong>Import preset JSON</strong><div class="muted">Files are validated and previewed before anything is saved.</div></div><input id="presetImportFile" type="file" accept="application/json,.json"><button id="importPresetButton" disabled>Import Validated Preset</button></div>
      <div id="importPreview" class="notice hidden"></div>
      <div id="advancedNotice" class="notice hidden"></div>
    </div>`;
  $('workerNotice').insertAdjacentElement('afterend',panel);
  for(const id of ['advTargetRate','advBitDepth','advQuality','advPassband','advPhase','advCompression','advDither','advHeadroom','advAliasing']){
    $(id).addEventListener('change',advancedMarkChanged);
    if($(id).tagName==='INPUT'&&$(id).type!=='checkbox')$(id).addEventListener('input',advancedMarkChanged);
  }
  $('resetAdvanced').onclick=()=>{advancedLoadEditor(advancedSelectedProfile());resetAck();advancedMessage('Advanced DSP settings reset to the selected preset. Refresh Review to confirm the batch.','info')};
  $('saveCustomPreset').onclick=advancedSaveAsCustom;
  $('updateCustomPreset').onclick=advancedUpdateCustom;
  $('duplicatePreset').onclick=advancedDuplicate;
  $('exportPreset').onclick=advancedExport;
  $('deleteCustomPreset').onclick=advancedDelete;
  $('presetImportFile').onchange=advancedPreviewImport;
  $('importPresetButton').onclick=advancedImport;
  $('advSourcePreHash').onchange=()=>{resetAck();advancedMessage($('advSourcePreHash').checked?'Source SHA-256 pre-hash enabled for this batch. Refresh Review before conversion.':'Source SHA-256 pre-hash disabled for this batch. Refresh Review before conversion.','info')};
}

function resetOperationalBatchOptions(){
  if($('advSourcePreHash'))$('advSourcePreHash').checked=false;
}

async function advancedFetchJson(url,options){
  const response=await fetch(url,options);const data=await response.json();
  if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:'Preset operation failed');
  return data;
}
async function advancedRefreshProfiles(preferredId=null){
  const data=await advancedFetchJson('/api/profiles');
  state.profiles=data.profiles||[];
  const remembered=preferredId||localStorage.getItem(ADVANCED_LAST_PRESET_KEY)||$('profileSelect').value||data.default;
  const selected=state.profiles.some(profile=>profile.id===remembered)?remembered:data.default;
  $('profileSelect').innerHTML=state.profiles.map(profile=>`<option value="${esc(profile.id)}">${esc(profile.name)}${profile.read_only?'':' (Custom)'}</option>`).join('');
  $('profileSelect').value=selected;
  localStorage.setItem(ADVANCED_LAST_PRESET_KEY,selected);
  advancedLoadEditor(advancedSelectedProfile());
}
async function advancedProfileChanged(){
  localStorage.setItem(ADVANCED_LAST_PRESET_KEY,$('profileSelect').value);
  advancedLoadEditor(advancedSelectedProfile());
  resetAck();
  await refreshReview();
}
async function advancedSaveAsCustom(){
  try{
    const payload=advancedFullPayload();
    if(!payload.name)throw new Error('Enter a custom preset name first.');
    const created=await advancedFetchJson('/api/profiles',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    await advancedRefreshProfiles(created.id);resetAck();advancedMessage(`Saved custom preset: ${created.name}`,'good');
  }catch(e){advancedMessage(e.message,'bad')}
}
async function advancedUpdateCustom(){
  const profile=advancedSelectedProfile();if(!profile||profile.read_only)return;
  try{
    const updated=await advancedFetchJson(`/api/profiles/${encodeURIComponent(profile.id)}`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(advancedFullPayload())});
    await advancedRefreshProfiles(updated.id);resetAck();advancedMessage(`Updated custom preset: ${updated.name}`,'good');
  }catch(e){advancedMessage(e.message,'bad')}
}
async function advancedDuplicate(){
  const profile=advancedSelectedProfile();if(!profile)return;
  try{
    const created=await advancedFetchJson(`/api/profiles/${encodeURIComponent(profile.id)}/duplicate`,{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
    await advancedRefreshProfiles(created.id);resetAck();advancedMessage(`Created custom copy: ${created.name}`,'good');
  }catch(e){advancedMessage(e.message,'bad')}
}
function advancedExport(){
  const profile=advancedSelectedProfile();if(!profile)return;
  const anchor=document.createElement('a');anchor.href=`/api/profiles/${encodeURIComponent(profile.id)}/export.json`;anchor.download='';document.body.appendChild(anchor);anchor.click();anchor.remove();
}
async function advancedDelete(){
  const profile=advancedSelectedProfile();if(!profile||profile.read_only)return;
  if(!confirm(`Delete custom preset "${profile.name}"? Existing conversion-job snapshots are unaffected.`))return;
  try{
    await advancedFetchJson(`/api/profiles/${encodeURIComponent(profile.id)}`,{method:'DELETE'});
    await advancedRefreshProfiles('foobar-ultra-37-48k');resetAck();advancedMessage('Custom preset deleted.','good');
  }catch(e){advancedMessage(e.message,'bad')}
}
async function advancedPreviewImport(event){
  advancedState.importDocument=null;advancedState.importPreview=null;$('importPresetButton').disabled=true;$('importPreview').classList.add('hidden');
  const file=event.target.files?.[0];if(!file)return;
  try{
    const documentData=JSON.parse(await file.text());
    const preview=await advancedFetchJson('/api/profiles/import/preview',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({document:documentData})});
    advancedState.importDocument=documentData;advancedState.importPreview=preview.profile;$('importPresetButton').disabled=false;
    $('importPreview').className='notice good';$('importPreview').innerHTML=`Validated preset <strong>${esc(preview.profile.name)}</strong>: ${Number(preview.profile.target_rate).toLocaleString()} Hz, ${esc(String(preview.profile.bit_depth))}, ${esc(preview.profile.quality)}, passband ${esc(preview.profile.passband_percent)}%, phase ${esc(preview.profile.phase_percent)}%.`;
  }catch(e){$('importPreview').className='notice bad';$('importPreview').textContent=e.message}
}
async function advancedImport(){
  if(!advancedState.importDocument)return;
  try{
    const created=await advancedFetchJson('/api/profiles/import',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({document:advancedState.importDocument})});
    advancedState.importDocument=null;advancedState.importPreview=null;$('presetImportFile').value='';$('importPresetButton').disabled=true;$('importPreview').classList.add('hidden');
    await advancedRefreshProfiles(created.id);resetAck();advancedMessage(`Imported custom preset: ${created.name}`,'good');
  }catch(e){advancedMessage(e.message,'bad')}
}

function advancedRenderResolvedReview(){
  if(!state.review?.profile)return;
  const profile=state.review.profile;
  let box=$('resolvedDspSummary');
  if(!box){box=document.createElement('div');box.id='resolvedDspSummary';box.className='resolvedDspSummary';$('reviewSummary').insertAdjacentElement('afterend',box)}
  box.innerHTML=`<div class="resolvedDspTitle"><strong>Resolved DSP for this batch</strong>${advancedState.override?'<span class="badge warn">Batch override</span>':''}</div><div class="resolvedDspGrid"><span>Target</span><strong>${Number(profile.target_rate).toLocaleString()} Hz</strong><span>Bit depth</span><strong>${esc(String(profile.bit_depth))}</strong><span>Quality</span><strong>${esc(profile.quality)}</strong><span>Passband</span><strong>${esc(profile.passband_percent)}%</strong><span>Phase</span><strong>${esc(profile.phase_percent)}%</strong><span>Aliasing</span><strong>${profile.allow_aliasing?'Allowed':'Disabled'}</strong><span>Compression</span><strong>FLAC ${esc(profile.flac_compression)}</strong><span>Dither</span><strong>${esc(profile.dither||'Automatic TPDF')}</strong><span>Headroom</span><strong>${Number(profile.headroom_db||0).toFixed(1)} dB</strong></div><div class="resolvedDspTitle" style="margin-top:12px"><strong>Per-batch safety</strong></div><div class="resolvedDspGrid"><span>Source SHA-256 pre-hash</span><strong>${state.review.source_pre_hash?'Enabled':'Disabled'}</strong></div>`;
}

const advancedBaseBuildReviewBody=buildReviewBody;
buildReviewBody=function(){
  const body=advancedBaseBuildReviewBody();
  if(advancedState.override)body.profile_override={...advancedState.override};
  body.source_pre_hash=Boolean($('advSourcePreHash')?.checked);
  return body;
};
const advancedBaseRefreshReview=refreshReview;
refreshReview=async function(){await advancedBaseRefreshReview();advancedRenderResolvedReview()};

advancedInstallPanel();
$('profileSelect').onchange=advancedProfileChanged;
$('reviewRefresh').onclick=refreshReview;
advancedRefreshProfiles().catch(error=>advancedMessage(error.message,'bad'));
setTimeout(()=>advancedRefreshProfiles().catch(()=>{}),500);
