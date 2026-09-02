const retryFailedState={sourceJobId:null,review:null};

(function installRetryStyles(){
  if(document.querySelector('link[data-retry-failed]'))return;
  const link=document.createElement('link');link.rel='stylesheet';link.href='/static/retry-failed.css';link.dataset.retryFailed='1';document.head.appendChild(link);
})();

function retryFailedInstall(){
  if($('retryFailedBtn'))return;
  const controls=document.querySelector('#activeJob .jobControls');
  if(controls){
    const button=document.createElement('button');
    button.id='retryFailedBtn';button.type='button';button.className='iconbtn hidden';
    button.innerHTML='<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M20 11a8 8 0 1 0-2.34 5.66M20 4v7h-7"/></svg>Retry Failed Files';
    button.onclick=()=>retryFailedPrepare(state.jobId);
    controls.insertBefore(button,controls.firstChild);
  }
  if(!$('retryFailedCard')){
    const card=document.createElement('section');
    card.id='retryFailedCard';card.className='card retryFailedCard hidden';
    card.innerHTML=`
      <div class="sectionTitle"><div><h3 style="margin:0">Retry Failed Files</h3><div id="retryFailedSubtitle" class="muted"></div></div><span class="spacer"></span><button id="retryFailedClose">Close Retry Review</button></div>
      <div class="notice info retryFailedPrinciple">This creates a new manual batch containing only the exact files that failed. The original job's resolved DSP snapshot is reused. Nothing is written until you acknowledge replacement and press Start Retry.</div>
      <div class="toolbar"><label>Concurrent conversions <select id="retryFailedWorkers"><option value="1">1 — Low load</option><option value="2">2 — Faster</option><option value="3">3 — Maximum</option></select></label><label><input id="retryFailedSourcePreHash" type="checkbox"> SHA-256 pre-hash sources</label><button id="retryFailedRefresh">Refresh Retry Review</button></div>
      <div id="retryFailedStatus" class="notice">Preparing retry preflight…</div>
      <div id="retryFailedSummary" class="reviewGrid hidden"></div>
      <div id="retryFailedAlbums" class="retryFailedAlbums"></div>
      <div id="retryFailedAckArea" class="ack hidden"><input id="retryFailedAck" type="checkbox"><label for="retryFailedAck"><strong>I understand these failed source FLAC files will be replaced in place only after verification passes.</strong><div class="muted" style="margin-top:4px">This acknowledgment applies only to this retry batch and resets whenever the retry review changes.</div></label></div>
      <div id="retryFailedActions" class="actions hidden"><button id="retryFailedStart" class="iconbtn primary" disabled><svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5l11 7-11 7z"/></svg>Start Retry</button></div>`;
    $('activeJob').insertAdjacentElement('afterend',card);
    $('retryFailedClose').onclick=retryFailedClose;
    $('retryFailedRefresh').onclick=retryFailedRefresh;
    $('retryFailedWorkers').onchange=()=>{retryFailedResetAck();retryFailedRefresh()};
    $('retryFailedSourcePreHash').onchange=()=>{retryFailedResetAck();retryFailedRefresh()};
    $('retryFailedAck').onchange=retryFailedEnableStart;
    $('retryFailedStart').onclick=retryFailedStart;
  }
}

function retryFailedResetAck(){
  if($('retryFailedAck'))$('retryFailedAck').checked=false;
  if($('retryFailedStart'))$('retryFailedStart').disabled=true;
}
function retryFailedEnableStart(){
  const review=retryFailedState.review;
  $('retryFailedStart').disabled=!(review?.can_start&&$('retryFailedAck').checked&&!state.readOnly);
}
function retryFailedClose(){
  retryFailedState.sourceJobId=null;retryFailedState.review=null;
  $('retryFailedCard').classList.add('hidden');retryFailedResetAck();
}
function retryFailedProfileSummary(profile){
  const bit=profile.bit_depth==='preserve'?'Preserve source':`${profile.bit_depth}-bit`;
  const dither=profile.dither||'Automatic TPDF when reducing bit depth';
  return `${Number(profile.target_rate).toLocaleString()} Hz · ${bit} · ${profile.quality} · passband ${profile.passband_percent}% · phase ${profile.phase_percent}% · ${dither}`;
}
function retryFailedAlbumHtml(album){
  const tracks=(album.tracks||[]).map(track=>`<div class="retryFailedTrack"><div><strong>${esc(track.filename)}</strong><div class="muted">${esc(track.path)}</div></div><div>${Number(track.sample_rate/1000).toLocaleString()} → ${Number(track.target_rate/1000).toLocaleString()} kHz</div><div>${esc(track.resample_ratio||'')}</div><div>${esc(track.bits_per_sample)} → ${esc(track.target_bits_per_sample)}-bit</div></div>`).join('');
  const blockers=(album.blockers||[]).map(text=>`<div class="notice bad">${esc(text)}</div>`).join('');
  const warnings=(album.warnings||[]).map(text=>`<span class="badge warn">${esc(text)}</span>`).join('');
  return `<div class="retryFailedAlbum"><div class="album-artist">${esc(album.albumartist)}</div><div class="album-title">${esc(album.album)}</div><div class="muted">${esc(album.folder)}</div><div class="badges">${warnings}</div>${blockers}<div class="retryFailedTracks">${tracks}</div></div>`;
}
function retryFailedRender(review){
  retryFailedState.review=review;
  const retry=review.retry||{};
  $('retryFailedSubtitle').textContent=`Source job ${retry.source_job_id} · ${retry.failed_files||0} failed file${retry.failed_files===1?'':'s'}`;
  $('retryFailedStatus').className='notice '+(review.can_start?'good':'bad');
  $('retryFailedStatus').textContent=review.can_start?'Retry preflight passed. Review the exact failed files and acknowledge replacement to enable Start Retry.':(review.blockers?.[0]||'Retry cannot start yet.');
  $('retryFailedSummary').classList.remove('hidden');
  $('retryFailedSummary').innerHTML=`<div class="reviewMetric"><span>Failed files</span><strong>${retry.failed_files||0}</strong></div><div class="reviewMetric"><span>Albums</span><strong>${review.album_count||0}</strong></div><div class="reviewMetric"><span>Resolved DSP</span><strong>${esc(review.profile?.name||review.profile?.id||'Snapshot')}</strong></div><div class="reviewMetric"><span>Source size</span><strong>${fmtBytes(review.source_bytes)}</strong></div><div class="reviewMetric"><span>Free space</span><strong>${fmtBytes(review.free_bytes)}</strong></div><div class="reviewMetric"><span>ZFS</span><strong>${review.zfs?.ok?'Healthy':'Blocked'}</strong></div><div class="reviewMetric"><span>Source pre-hash</span><strong>${review.source_pre_hash?'Enabled':'Disabled'}</strong></div>`;
  $('retryFailedAlbums').innerHTML=`<div class="retryFailedDsp"><strong>Exact DSP snapshot</strong><div class="muted">${esc(retryFailedProfileSummary(review.profile||{}))}</div></div>${(review.albums||[]).map(retryFailedAlbumHtml).join('')}`;
  $('retryFailedAckArea').classList.toggle('hidden',!review.can_start);
  $('retryFailedActions').classList.toggle('hidden',!review.can_start);
  retryFailedResetAck();
}
async function retryFailedPrepare(jobId){
  if(!jobId)return;
  retryFailedInstall();retryFailedState.sourceJobId=Number(jobId);$('retryFailedWorkers').value='1';$('retryFailedSourcePreHash').checked=false;$('retryFailedCard').classList.remove('hidden');
  $('retryFailedCard').scrollIntoView({behavior:'smooth',block:'start'});
  await retryFailedRefresh();
}
async function retryFailedRefresh(){
  const jobId=retryFailedState.sourceJobId;if(!jobId)return;
  retryFailedResetAck();$('retryFailedStatus').className='notice';$('retryFailedStatus').textContent='Running fresh retry preflight checks…';
  try{
    const workers=Number($('retryFailedWorkers').value||1);
    const params=new URLSearchParams({workers:String(workers),source_pre_hash:String(Boolean($('retryFailedSourcePreHash').checked))});
    const response=await fetch(`/api/convert/jobs/${jobId}/retry-review?${params}`);
    const text=await response.text();
    let data=null;
    try{data=text?JSON.parse(text):null}catch(_error){data=null}
    if(!response.ok){
      const detail=typeof data?.detail==='string'?data.detail:(text||`Retry review failed (HTTP ${response.status})`);
      throw new Error(detail);
    }
    if(!data||typeof data!=='object')throw new Error('Retry review returned an invalid response');
    retryFailedRender(data);
  }catch(error){
    retryFailedState.review=null;$('retryFailedStatus').className='notice bad';$('retryFailedStatus').textContent=error.message;$('retryFailedSummary').classList.add('hidden');$('retryFailedAlbums').innerHTML='';$('retryFailedAckArea').classList.add('hidden');$('retryFailedActions').classList.add('hidden');
  }
}
async function retryFailedStart(){
  const jobId=retryFailedState.sourceJobId;
  if(!jobId||!retryFailedState.review?.can_start||!$('retryFailedAck').checked)return;
  const button=$('retryFailedStart');button.disabled=true;const old=button.innerHTML;button.textContent='Starting Retry…';
  try{
    const response=await fetch(`/api/convert/jobs/${jobId}/retry-start`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({workers:Number($('retryFailedWorkers').value||1),source_pre_hash:Boolean($('retryFailedSourcePreHash').checked),acknowledged_replace_in_place:true})});
    const text=await response.text();
    let data=null;
    try{data=text?JSON.parse(text):null}catch(_error){data=null}
    if(!response.ok){
      const detail=typeof data?.detail==='string'?data.detail:(Array.isArray(data?.detail?.blockers)?data.detail.blockers.join('; '):(text||`Unable to start retry (HTTP ${response.status})`));
      throw new Error(detail||'Unable to start retry');
    }
    if(!data||!data.job_id)throw new Error('Retry start returned an invalid response');
    retryFailedClose();watchJob(data.job_id,true);
  }catch(error){$('retryFailedStatus').className='notice bad';$('retryFailedStatus').textContent=error.message;retryFailedEnableStart()}
  finally{button.innerHTML=old}
}

retryFailedInstall();
const retryFailedBaseRenderJob=renderJob;
renderJob=function(job){
  retryFailedBaseRenderJob(job);
  retryFailedInstall();
  const failures=Number(job.counts?.failed||0);
  const eligible=failures>0&&['completed','cancelled','stopped'].includes(job.status);
  $('retryFailedBtn').classList.toggle('hidden',!eligible);
  $('retryFailedBtn').disabled=!eligible;
  if(retryFailedState.sourceJobId&&Number(job.id)!==retryFailedState.sourceJobId&&job.status==='running')retryFailedClose();
};
