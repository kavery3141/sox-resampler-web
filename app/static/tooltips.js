const TOOLTIP_ENABLED_KEY='sox-resampler-tooltips-enabled';

const BUTTON_TOOLTIPS={
  navHome:'Open the Home dashboard.',
  navLibrary:'Browse indexed albums and choose high-rate conversion candidates.',
  navConvert:'Open the conversion review and active-job controls.',
  navHistory:'View previous conversion jobs and their reports.',
  navSettings:'Open application and browser-specific settings.',
  navMaintenance:'Open database, index, version, and health maintenance tools.',
  homeOpenCandidates:'Open the Library filtered to the standard 96 kHz and 192 kHz conversion candidates.',
  homeResumeJob:'Open the interrupted or paused conversion job. This does not automatically resume conversion.',
  refreshBtn:'Reload candidate results from the existing local index. This does not rescan the music files.',
  scanBtn:'Run an incremental library scan to discover new or changed FLAC files and refresh the local index.',
  checkAll:'Select every currently visible, selectable album.',
  uncheckAll:'Clear selection from every currently visible album.',
  expandAll:'Expand details for every currently visible album.',
  collapseAll:'Collapse details for every currently visible album.',
  backLibrary:'Return to the Library without starting a conversion.',
  pauseJob:'Finish each currently active file, then pause the conversion job.',
  resumeJob:'Resume a paused conversion job using its existing reviewed settings.',
  stopJob:'Finish the current album, then stop the job before beginning another album.',
  cancelJob:'Finish only the files already in progress, then cancel the remaining queued work.',
  reviewRefresh:'Rebuild destructive preflight using the current selection, preset, worker count, and source state.',
  exportReviewTxt:'Download the current preflight review as a plain-text report.',
  exportReviewCsv:'Download the current preflight review as a CSV report.',
  startBtn:'Start the manually reviewed conversion batch. Source files are replaced only after output verification succeeds.',
  refreshHistory:'Reload conversion-job history from the local database.',
  enableReadOnly:'Enable scan-only mode. Conversion remains unavailable until read-only mode is disabled.',
  disableReadOnly:'Allow manual conversion again. This does not start any conversion.',
  previewExclusions:'Show what the current exclusion paths and patterns would exclude without saving them.',
  saveStorageSettings:'Save the free-space reserve and scan exclusion settings.',
  refreshMaintenance:'Reload maintenance, version, database, and storage-health information.',
  maintenanceIncremental:'Scan for new or changed files and update only affected index records.',
  maintenanceFull:'Read the full music library and refresh the index without deleting the database first.',
  maintenanceRebuild:'Discard and rebuild the library index from the music files. This affects the index only, not the FLAC files.',
  maintenanceVacuum:'Run SQLite VACUUM: rebuild the local database file to reclaim unused space and reduce fragmentation. It does not rescan, retag, or alter music files.',
  clearSelected:'Clear the current album selection.',
  reviewBtn:'Open Convert and build a destructive preflight for the currently selected albums.',
  selectedWarnings:'Temporarily show only selected albums that contain warnings.',
};

const TEXT_TOOLTIPS={
  'details':'Show indexed metadata and path details for this album.',
  'hide details':'Collapse this album’s metadata and path details.',
  'copy':'Copy this value to the clipboard.',
  'copy path':'Copy the TrueNAS-visible path to the clipboard.',
  'report txt':'Download the conversion report as plain text.',
  'report csv':'Download the conversion report as CSV.',
  'retry failed files':'Build a new manual review containing only files that failed in the original job.',
  'retry clipping with headroom':'Build a new manual retry review for clipping failures with additional headroom. Nothing is converted until you review and start it.',
  'check for updates':'Check GitHub for a newer application release. The app never installs updates automatically.',
  'recheck recovery':'Re-run interrupted-transaction and orphan-temp safety checks. This does not start conversion.',
  'refresh artwork cache':'Refresh locally cached album artwork used by the interface.',
  'clear artwork cache':'Remove generated local artwork-cache entries so they can be rebuilt. Source artwork in the music library is not deleted.',
  'reset settings':'Restore application settings to their defaults. Browser-only interface preferences are also reset where documented.',
};

let tooltipNode=null;
let tooltipTarget=null;

function tooltipsEnabled(){
  const value=localStorage.getItem(TOOLTIP_ENABLED_KEY);
  return value===null?true:value!=='false';
}

function setTooltipsEnabled(enabled){
  localStorage.setItem(TOOLTIP_ENABLED_KEY,enabled?'true':'false');
  document.body.dataset.tooltips=enabled?'on':'off';
  const toggle=document.getElementById('tooltipToggle');
  if(toggle)toggle.checked=enabled;
  if(!enabled)hideTooltip();
}

function tooltipText(button){
  if(button.dataset.tooltip)return button.dataset.tooltip;
  if(button.id&&BUTTON_TOOLTIPS[button.id])return BUTTON_TOOLTIPS[button.id];
  const text=String(button.textContent||'').replace(/\s+/g,' ').trim().toLowerCase();
  if(TEXT_TOOLTIPS[text])return TEXT_TOOLTIPS[text];
  if(text.startsWith('retry failed'))return TEXT_TOOLTIPS['retry failed files'];
  if(text.startsWith('retry clipping'))return TEXT_TOOLTIPS['retry clipping with headroom'];
  if(button.title)return button.title;
  return '';
}

function ensureTooltipNode(){
  if(tooltipNode)return tooltipNode;
  tooltipNode=document.createElement('div');
  tooltipNode.id='buttonTooltip';
  tooltipNode.className='buttonTooltip hidden';
  tooltipNode.setAttribute('role','tooltip');
  document.body.appendChild(tooltipNode);
  return tooltipNode;
}

function positionTooltip(target){
  if(!tooltipNode||tooltipNode.classList.contains('hidden'))return;
  const rect=target.getBoundingClientRect();
  const gap=9;
  const margin=10;
  const tip=tooltipNode.getBoundingClientRect();
  let left=rect.left+(rect.width-tip.width)/2;
  left=Math.max(margin,Math.min(left,window.innerWidth-tip.width-margin));
  let top=rect.bottom+gap;
  if(top+tip.height>window.innerHeight-margin)top=rect.top-tip.height-gap;
  tooltipNode.style.left=`${Math.round(left)}px`;
  tooltipNode.style.top=`${Math.round(Math.max(margin,top))}px`;
}

function showTooltip(target){
  if(!tooltipsEnabled())return;
  const text=tooltipText(target);
  if(!text)return;
  const node=ensureTooltipNode();
  tooltipTarget=target;
  node.textContent=text;
  node.classList.remove('hidden');
  positionTooltip(target);
}

function hideTooltip(){
  tooltipTarget=null;
  if(tooltipNode)tooltipNode.classList.add('hidden');
}

function installTooltipToggle(){
  const grid=document.querySelector('#settingsView .appearanceGrid');
  if(!grid||document.getElementById('tooltipToggle'))return;
  const label=document.createElement('label');
  label.className='tooltipSetting';
  label.innerHTML='<span>Button tooltips</span><span class="toggleLine"><input id="tooltipToggle" type="checkbox"><span>Show explanations on hover or keyboard focus</span></span>';
  grid.appendChild(label);
  const toggle=document.getElementById('tooltipToggle');
  toggle.checked=tooltipsEnabled();
  toggle.addEventListener('change',()=>setTooltipsEnabled(toggle.checked));
}

function installTooltipStyles(){
  if(document.querySelector('style[data-button-tooltips]'))return;
  const style=document.createElement('style');
  style.dataset.buttonTooltips='1';
  style.textContent=`
.buttonTooltip{position:fixed;z-index:10000;max-width:360px;padding:9px 11px;border:1px solid var(--border);border-radius:8px;background:var(--panel2);color:var(--text);font-size:12px;line-height:1.4;box-shadow:0 8px 24px rgba(0,0,0,.35);pointer-events:none}
.tooltipSetting{display:flex;flex-direction:column;gap:7px;color:var(--muted);font-size:13px}.toggleLine{display:flex;align-items:center;gap:8px;min-height:39px}.toggleLine input{width:18px;height:18px;accent-color:var(--orange)}
`;
  document.head.appendChild(style);
}

function buttonFromEvent(event){
  const target=event.target instanceof Element?event.target.closest('button'):null;
  return target&&document.body.contains(target)?target:null;
}

document.addEventListener('pointerover',event=>{
  const button=buttonFromEvent(event);
  if(button&&button!==tooltipTarget)showTooltip(button);
});
document.addEventListener('pointerout',event=>{
  const button=buttonFromEvent(event);
  if(button&&tooltipTarget===button)hideTooltip();
});
document.addEventListener('focusin',event=>{
  const button=buttonFromEvent(event);
  if(button)showTooltip(button);
});
document.addEventListener('focusout',event=>{
  const button=buttonFromEvent(event);
  if(button&&tooltipTarget===button)hideTooltip();
});
window.addEventListener('scroll',()=>{if(tooltipTarget)positionTooltip(tooltipTarget)},true);
window.addEventListener('resize',()=>{if(tooltipTarget)positionTooltip(tooltipTarget)});

installTooltipStyles();
installTooltipToggle();
setTooltipsEnabled(tooltipsEnabled());
