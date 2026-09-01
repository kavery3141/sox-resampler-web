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

    controls.querySelector('.batchMoveUp').onclick=()=>batchMove(key,-1);
    controls.querySelector('.batchMoveDown').onclick=()=>batchMove(key,1);
    controls.querySelector('.batchRemove').onclick=()=>batchRemove(key);
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
