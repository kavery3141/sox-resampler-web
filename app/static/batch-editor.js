const batchEditorState={order:[],dragKey:null};

function batchAlbumKey(album){
  return `${album.albumartist||''}\u0000${album.album||''}\u0000${album.folder||''}`;
}
function batchSyncOrder(){
  const selected=[...state.selected.values()];
  const liveKeys=new Set(selected.map(batchAlbumKey));
  batchEditorState.order=batchEditorState.order.filter(key=>liveKeys.has(key));
  for(const album of selected){
    const key=batchAlbumKey(album);
    if(!batchEditorState.order.includes(key))batchEditorState.order.push(key);
  }
  return batchEditorState.order;
}
function batchOrderedSelection(){
  batchSyncOrder();
  const lookup=new Map([...state.selected.values()].map(album=>[batchAlbumKey(album),album]));
  return batchEditorState.order.map(key=>lookup.get(key)).filter(Boolean);
}
function batchMove(key,direction){
  batchSyncOrder();
  const index=batchEditorState.order.indexOf(key);
  const target=index+direction;
  if(index<0||target<0||target>=batchEditorState.order.length)return;
  [batchEditorState.order[index],batchEditorState.order[target]]=[batchEditorState.order[target],batchEditorState.order[index]];
  resetAck();
  refreshReview();
}
function batchMoveBefore(key,beforeKey){
  batchSyncOrder();
  if(key===beforeKey)return;
  const next=batchEditorState.order.filter(item=>item!==key);
  const before=next.indexOf(beforeKey);
  if(before<0)next.push(key);else next.splice(before,0,key);
  batchEditorState.order=next;
  resetAck();
  refreshReview();
}
function batchRemove(key){
  state.selected.delete(key);
  batchEditorState.order=batchEditorState.order.filter(item=>item!==key);
  updateTray();
  render();
  resetAck();
  refreshReview();
}
function batchControlSvg(direction){
  if(direction==='up')return '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 19V5M6 11l6-6 6 6"/></svg>';
  if(direction==='down')return '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M18 13l-6 6-6-6"/></svg>';
  return '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M9 7V4h6v3M7 7l1 13h8l1-13"/></svg>';
}
function batchTechnicalSummary(album){
  const tracks=album.tracks||[];
  const groups=new Map();
  for(const track of tracks){
    const key=[track.sample_rate,track.target_rate,track.bits_per_sample,track.target_bits_per_sample,track.resample_ratio,track.dither||''].join('|');
    if(!groups.has(key))groups.set(key,{...track,count:0});
    groups.get(key).count+=1;
  }
  if(!groups.size)return '';
  return `<div class="batchTechnical">${[...groups.values()].map(item=>{
    const dither=item.dither?` · ${esc(item.dither)} dither`:'';
    return `<span>${item.count} track${item.count===1?'':'s'}: ${Number(item.sample_rate/1000).toLocaleString()} → ${Number(item.target_rate/1000).toLocaleString()} kHz · ${esc(item.resample_ratio||'')} · ${esc(item.bits_per_sample)} → ${esc(item.target_bits_per_sample)}-bit${dither}</span>`;
  }).join('')}</div>`;
}
function batchRateLabel(rate){
  const value=Number(rate||0);
  if(!value)return '—';
  return value%1000===0?`${value/1000} kHz`:`${(value/1000).toFixed(1)} kHz`;
}
function batchTrackDetailHtml(album){
  const tracks=album.tracks||[];
  if(!tracks.length)return '';
  return `<details class="batchTrackDetails"><summary>Exact matching tracks (${tracks.length})</summary><div class="batchTrackList">${tracks.map((track,index)=>{
    const path=track.display_path||track.path||'';
    const filename=basename(path)||track.filename||`Track ${index+1}`;
    const targetRate=track.target_rate||state.review?.profile?.target_rate;
    const targetBits=track.target_bits_per_sample||track.bits_per_sample;
    const specs=`${batchRateLabel(track.sample_rate)} → ${batchRateLabel(targetRate)} · ${track.bits_per_sample||'—'} → ${targetBits||'—'}-bit${track.resample_ratio?` · ratio ${track.resample_ratio}`:''}${track.dither?` · ${track.dither} dither`:''}`;
    const size=`${fmtBytes(track.source_bytes||0)} source${track.estimated_output_bytes?` · ${fmtBytes(track.estimated_output_bytes)} estimated output`:''}`;
    return `<div class="batchTrackRow"><div class="batchTrackMain"><strong>${esc(filename)}</strong><code>${esc(path)}</code><span class="muted">${esc(specs)}</span><span class="muted">${esc(size)}</span></div><button type="button" class="batchCopyTrackPath" data-track-index="${index}">Copy Path</button></div>`;
  }).join('')}</div></details>`;
}
async function batchCopyPath(button,text){
  if(!navigator.clipboard?.writeText)return;
  const prior=button.textContent;
  try{
    await navigator.clipboard.writeText(text||'');
    button.textContent='Copied';
  }catch(e){button.textContent='Copy failed'}
  setTimeout(()=>{button.textContent=prior},1200);
}
function batchDecorateReview(){
  const container=$('reviewAlbums');
  if(!container||container.classList.contains('hidden')||!state.review)return;
  const albums=state.review.albums||[];
  const rows=[...container.querySelectorAll('.reviewAlbum')];
  rows.forEach((row,index)=>{
    const album=albums[index];if(!album)return;
    const key=batchAlbumKey(album);
    row.dataset.batchKey=encodeURIComponent(key);
    row.draggable=true;
    row.classList.add('batchEditableAlbum');

    const controls=document.createElement('div');
    controls.className='batchControls';
    controls.innerHTML=`<span class="batchPosition">${index+1}</span><button type="button" class="iconbtn batchMoveUp" title="Move album up" aria-label="Move ${esc(album.album)} up" ${index===0?'disabled':''}>${batchControlSvg('up')}</button><button type="button" class="iconbtn batchMoveDown" title="Move album down" aria-label="Move ${esc(album.album)} down" ${index===albums.length-1?'disabled':''}>${batchControlSvg('down')}</button><button type="button" class="iconbtn danger batchRemove" title="Remove album from batch" aria-label="Remove ${esc(album.album)} from batch">${batchControlSvg('remove')}</button><span class="batchDragHint muted">Drag to reorder</span>`;
    row.prepend(controls);
    const summary=batchTechnicalSummary(album);
    if(summary)row.insertAdjacentHTML('beforeend',summary);
    const trackDetails=batchTrackDetailHtml(album);
    if(trackDetails)row.insertAdjacentHTML('beforeend',trackDetails);

    controls.querySelector('.batchMoveUp').onclick=()=>batchMove(key,-1);
    controls.querySelector('.batchMoveDown').onclick=()=>batchMove(key,1);
    controls.querySelector('.batchRemove').onclick=()=>batchRemove(key);
    row.querySelectorAll('.batchCopyTrackPath').forEach(button=>{
      const track=album.tracks?.[Number(button.dataset.trackIndex)];
      button.onclick=()=>batchCopyPath(button,track?.display_path||track?.path||'');
    });
    row.addEventListener('dragstart',event=>{
      batchEditorState.dragKey=key;
      row.classList.add('dragging');
      event.dataTransfer.effectAllowed='move';
      event.dataTransfer.setData('text/plain',key);
    });
    row.addEventListener('dragend',()=>{batchEditorState.dragKey=null;row.classList.remove('dragging');document.querySelectorAll('.batchDropTarget').forEach(node=>node.classList.remove('batchDropTarget'))});
    row.addEventListener('dragover',event=>{event.preventDefault();event.dataTransfer.dropEffect='move';row.classList.add('batchDropTarget')});
    row.addEventListener('dragleave',()=>row.classList.remove('batchDropTarget'));
    row.addEventListener('drop',event=>{
      event.preventDefault();row.classList.remove('batchDropTarget');
      const dragged=batchEditorState.dragKey||event.dataTransfer.getData('text/plain');
      if(dragged)batchMoveBefore(dragged,key);
    });
  });
}

const batchBaseBuildReviewBody=buildReviewBody;
buildReviewBody=function(){
  const body=batchBaseBuildReviewBody();
  const ordered=batchOrderedSelection();
  const desired=ordered.map(album=>batchAlbumKey(album));
  const source=new Map((body.albums||[]).map(album=>[batchAlbumKey(album),album]));
  body.albums=desired.map(key=>source.get(key)).filter(Boolean);
  return body;
};

const batchBaseRefreshReview=refreshReview;
refreshReview=async function(){
  await batchBaseRefreshReview();
  batchDecorateReview();
};
$('reviewRefresh').onclick=refreshReview;

const batchBaseUpdateTray=updateTray;
updateTray=function(){batchSyncOrder();batchBaseUpdateTray()};

(function installBatchStyles(){
  if(document.querySelector('link[data-batch-editor]'))return;
  const link=document.createElement('link');link.rel='stylesheet';link.href='/static/batch-editor.css';link.dataset.batchEditor='1';document.head.appendChild(link);
})();
