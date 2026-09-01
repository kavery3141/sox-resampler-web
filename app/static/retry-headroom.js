const retryHeadroomState={sourceJobId:null,options:null,review:null};

(function installRetryHeadroomStyles(){
  if(document.querySelector('link[data-retry-headroom]'))return;
  const link=document.createElement('link');link.rel='stylesheet';link.href='/static/retry-headroom.css';link.dataset.retryHeadroom='1';document.head.appendChild(link);
})();

function retryHeadroomInstall(){
  if(!$('retryHeadroomBtn')){
    const controls=document.querySelector('#activeJob .jobControls');
    if(controls){
      const button=document.createElement('button');button.id='retryHeadroomBtn';button.type='button';button.className='iconbtn hidden';
      button.innerHTML='<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M20 11a8 8 0 1 0-2.34 5.66M20 4v7h-7"/><path d="M12 7v10M8 13l4 4 4-4"/></svg>Retry Clipping with Headroom';
      button.onclick=()=>retryHeadroomPrepare(state.jobId);
      const failed=$('retryFailedBtn');if(failed)failed.insertAdjacentElement('afterend',button);else controls.insertBefore(button,controls.firstChild);
    }
  }
  if(!$('retryHeadroomCard')){
    const card=document.createElement('section');card.id='retryHeadroomCard';card.className='card retryHeadroomCard hidden';
    card.innerHTML=`
      <div class="sectionTitle"><div><h3 style="margin:0">Retry Clipping with Headroom</h3><div id="retryHeadroomSubtitle" class="muted"></div></div><span class="spacer"></span><button id="retryHeadroomClose">Close Retry Review</button></div>
      <div class="notice warn retryHeadroomPrinciple">Only files whose previous failure was identified as clipping are included. A fresh preflight is required, the original DSP snapshot is preserved except for the explicit headroom change, and no source file is written until you acknowledge replacement and press Start Headroom Retry.</div>
      <div class="toolbar">
        <label>Total headroom (dB)<input id="retryHeadroomDb" type="number" min="-30" max="-0.1" step="0.1"></label>
        <label>Concurrent conversions <select id="retryHeadroomWorkers"><option value="1">1 — Low load</option><option value="2">2 — Faster</option></select></label>
        <button id="retryHeadroomRefresh">Refresh Headroom Review</button>
      </div>
      <div id="retryHeadroomChange" class="notice info hidden"></div>
      <div id="retryHeadroomStatus" class="notice">Preparing clipping retry preflight…</div>
      <div id="retryHeadroomSummary" class="reviewGrid hidden"></div>
      <div id="retryHeadroomAlbums" class="retryHeadroomAlbums"></div>
      <div id="retryHeadroomAckArea" class="ack hidden"><input id="retryHeadroomAck" type="checkbox"><label for="retryHeadroomAck"><strong>I understand these clipping-failed source FLAC files will be replaced in place only after the new output passes verification.</strong><div class="muted" style="margin-top:4px">This acknowledgment applies only to this headroom retry batch and resets whenever the review changes.</div></label></div>
      <div id="retryHeadroomActions" class="actions hidden"><button id="retryHeadroomStart" class="iconbtn primary" disabled><svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5l11 7-11 7z"/></svg>Start Headroom Retry</button></div>`;
    const failedCard=$('retryFailedCard');if(failedCard)failedCard.insertAdjacentElement('afterend',card);else $('activeJob').insertAdjacentElement('afterend',card);
    $('retryHeadroomClose').onclick=retryHeadroomClose;
    $('retryHeadroomRefresh').onclick=retryHeadroomRefresh;
    $('retryHeadroomWorkers').onchange=()=>{retryHeadroomResetAck();retryHeadroomRefresh()};
    $('retryHeadroomDb').onchange=()=>{retryHeadroomResetAck();retryHeadroomRefresh()};
    $('retryHeadroomAck').onchange=retryHeadroomEnableStart;
    $('retryHeadroomStart').onclick=retryHeadroomStart;
  }
}

function retryHeadroomResetAck(){
  if($('retryHeadroomAck'))$('retryHeadroomAck').checked=false;
  if($('retryHeadroomStart'))$('retryHeadroomStart').disabled=true;
}
function retryHeadroomEnableStart(){
  $('retryHeadroomStart').disabled=!(retryHeadroomState.review?.can_start&&$('retryHeadroomAck').checked&&!state.readOnly);
}
function retryHeadroomClose(){
  retryHeadroomState.sourceJobId=null;retryHeadroomState.review=null;
  $('retryHeadroomCard').classList.add('hidden');retryHeadroomResetAck();
}
function retryHeadroomProfileText(profile){
  const bit=profile.bit_depth==='preserve'?'Preserve source':`${profile.bit_depth}-bit`;
  return `${Number(profile.target_rate).toLocaleString()} Hz · ${bit} · ${profile.quality} · passband ${profile.passband_percent}% · phase ${profile.phase_percent}% · headroom ${Number(profile.headroom_db||0).toFixed(1)} dB`;
}
function retryHeadroomAlbumHtml(album){
  const tracks=(album.tracks||[]).map(track=>`<div class="retryHeadroomTrack"><div><strong>${esc(track.filename)}</strong><div class="muted">${esc(track.path)}</div></div><div>${Number(track.sample_rate/1000).toLocaleString()} → ${Number(track.target_rate/1000).toLocaleString()} kHz</div><div>${esc(track.resample_ratio||'')}</div><div>${esc(track.bits_per_sample)} → ${esc(track.target_bits_per_sample)}-bit</div></div>`).join('');
  const blockers=(album.blockers||[]).map(text=>`<div class="notice bad">${esc(text)}</div>`).join('');
  return `<div class="retryHeadroomAlbum"><div class="album-artist">${esc(album.albumartist)}</div><div class="album-title">${esc(album.album)}</div><div class="muted">${esc(album.folder)}</div>${blockers}<div class="retryHeadroomTracks">${tracks}</div></div>`;
}
async function retryHeadroomOptions(jobId){
  const response=await fetch(`/api/convert/jobs/${jobId}/retry-options`);const data=await response.json();
  if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:'Unable to determine retry options');
  return data;
}
async function retryHeadroomPrepare(jobId){
  if(!jobId)return;retryHeadroomInstall();retryHeadroomState.sourceJobId=Number(jobId);retryHeadroomState.review=null;
  try{
    const options=await retryHeadroomOptions(jobId);retryHeadroomState.options=options;
    if(!options.retry_with_headroom_available)throw new Error(options.clipping_failures?'Maximum supported headroom is already in use.':'This job has no clipping failures eligible for Retry with Headroom.');
    $('retryHeadroomDb').value=Number(options.default_headroom_db).toFixed(1);$('retryHeadroomWorkers').value='1';$('retryHeadroomCard').classList.remove('hidden');
    $('retryHeadroomCard').scrollIntoView({behavior:'smooth',block:'start'});await retryHeadroomRefresh();
  }catch(error){
    $('jobError').classList.remove('hidden');$('jobError').textContent=error.message;
  }
}
async function retryHeadroomRefresh(){
  const jobId=retryHeadroomState.sourceJobId;if(!jobId)return;
  const headroom=Number($('retryHeadroomDb').value);const workers=Number($('retryHeadroomWorkers').value||1);
  retryHeadroomResetAck();$('retryHeadroomStatus').className='notice';$('retryHeadroomStatus').textContent='Running fresh clipping/headroom preflight checks…';
  try{
    const params=new URLSearchParams({workers:String(workers),headroom_db:String(headroom)});
    const response=await fetch(`/api/convert/jobs/${jobId}/retry-headroom-review?${params}`);const review=await response.json();
    if(!response.ok)throw new Error(typeof review.detail==='string'?review.detail:'Headroom retry review failed');
    retryHeadroomState.review=review;const retry=review.retry||{};
    $('retryHeadroomSubtitle').textContent=`Source job ${retry.source_job_id} · ${retry.clipping_failures||0} clipping-failed file${retry.clipping_failures===1?'':'s'}`;
    $('retryHeadroomChange').className='notice info';$('retryHeadroomChange').textContent=`Headroom change: ${Number(retry.original_headroom_db||0).toFixed(1)} dB → ${Number(retry.headroom_db).toFixed(1)} dB. All other resolved DSP settings remain from the source job snapshot.`;
    $('retryHeadroomStatus').className='notice '+(review.can_start?'good':'bad');$('retryHeadroomStatus').textContent=review.can_start?'Headroom retry preflight passed. Review the exact files and DSP change, then acknowledge replacement to enable Start Headroom Retry.':(review.blockers?.[0]||'Headroom retry cannot start yet.');
    $('retryHeadroomSummary').classList.remove('hidden');$('retryHeadroomSummary').innerHTML=`<div class="reviewMetric"><span>Clipping failures</span><strong>${retry.clipping_failures||0}</strong></div><div class="reviewMetric"><span>Headroom</span><strong>${Number(retry.headroom_db).toFixed(1)} dB</strong></div><div class="reviewMetric"><span>Source size</span><strong>${fmtBytes(review.source_bytes)}</strong></div><div class="reviewMetric"><span>Resolved DSP</span><strong>${esc(review.profile?.name||review.profile?.id||'Snapshot')}</strong></div><div class="reviewMetric"><span>Free space</span><strong>${fmtBytes(review.free_bytes)}</strong></div><div class="reviewMetric"><span>ZFS</span><strong>${review.zfs?.ok?'Healthy':'Blocked'}</strong></div>`;
    $('retryHeadroomAlbums').innerHTML=`<div class="retryHeadroomDsp"><strong>Resolved retry DSP</strong><div class="muted">${esc(retryHeadroomProfileText(review.profile||{}))}</div></div>${(review.albums||[]).map(retryHeadroomAlbumHtml).join('')}`;
    $('retryHeadroomAckArea').classList.toggle('hidden',!review.can_start);$('retryHeadroomActions').classList.toggle('hidden',!review.can_start);
  }catch(error){
    retryHeadroomState.review=null;$('retryHeadroomStatus').className='notice bad';$('retryHeadroomStatus').textContent=error.message;$('retryHeadroomSummary').classList.add('hidden');$('retryHeadroomAlbums').innerHTML='';$('retryHeadroomAckArea').classList.add('hidden');$('retryHeadroomActions').classList.add('hidden');
  }
}
async function retryHeadroomStart(){
  const jobId=retryHeadroomState.sourceJobId;if(!jobId||!retryHeadroomState.review?.can_start||!$('retryHeadroomAck').checked)return;
  const button=$('retryHeadroomStart');button.disabled=true;const old=button.innerHTML;button.textContent='Starting Headroom Retry…';
  try{
    const body={workers:Number($('retryHeadroomWorkers').value||1),headroom_db:Number($('retryHeadroomDb').value),acknowledged_replace_in_place:true};
    const response=await fetch(`/api/convert/jobs/${jobId}/retry-headroom-start`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const data=await response.json();
    if(!response.ok){const detail=typeof data.detail==='string'?data.detail:(data.detail?.blockers||[]).join('; ');throw new Error(detail||'Unable to start headroom retry')}
    retryHeadroomClose();watchJob(data.job_id,true);
  }catch(error){$('retryHeadroomStatus').className='notice bad';$('retryHeadroomStatus').textContent=error.message;retryHeadroomEnableStart()}
  finally{button.innerHTML=old}
}

retryHeadroomInstall();
let retryHeadroomOptionRequest=0;
const retryHeadroomBaseRenderJob=renderJob;
renderJob=function(job){
  retryHeadroomBaseRenderJob(job);retryHeadroomInstall();
  const button=$('retryHeadroomBtn');button.classList.add('hidden');button.disabled=true;
  const eligible=Number(job.counts?.failed||0)>0&&['completed','cancelled','stopped'].includes(job.status);
  if(!eligible)return;
  const request=++retryHeadroomOptionRequest;
  retryHeadroomOptions(job.id).then(options=>{
    if(request!==retryHeadroomOptionRequest||Number(state.jobId)!==Number(job.id))return;
    retryHeadroomState.options=options;const show=Boolean(options.retry_with_headroom_available);button.classList.toggle('hidden',!show);button.disabled=!show;
  }).catch(()=>{});
};
