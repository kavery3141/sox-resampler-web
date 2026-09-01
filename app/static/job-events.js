(function installJobEventStyles(){
  if(document.querySelector('link[data-job-events]'))return;
  const link=document.createElement('link');
  link.rel='stylesheet';
  link.href='/static/job-events.css';
  link.dataset.jobEvents='1';
  document.head.appendChild(link);
})();

function jobEventLabel(type){
  return ({
    job_created:'Job created',
    job_started:'Job started',
    job_resumed:'Job resumed',
    workers_changed:'Concurrency changed',
    pause_requested:'Pause requested',
    stop_after_album_requested:'Stop after album requested',
    cancel_requested:'Cancel requested',
    runtime_pause:'Safety pause',
    restart_interrupted:'Restart interruption',
    file_deferred_busy:'Busy file deferred',
    job_finished:'Job state saved',
  })[type]||String(type||'Job event').replaceAll('_',' ');
}
function jobEventDetail(event){
  const detail=event.detail||{};
  switch(event.event_type){
    case 'workers_changed': return `${detail.from} → ${detail.to} workers; applies between files`;
    case 'pause_requested': return 'Finish active file work, then pause';
    case 'stop_after_album_requested': return 'Finish the current album, then stop';
    case 'cancel_requested': return 'Finish active file work, then cancel remaining files';
    case 'runtime_pause': return detail.reason||'A runtime safety check paused the batch';
    case 'restart_interrupted': return `Container or NAS restart interrupted ${detail.previous_status||'active'} state`;
    case 'file_deferred_busy': return `${basename(detail.path||'file')} will receive one end-of-batch retry`;
    case 'job_started':
    case 'job_resumed': return `${detail.workers||1} worker${Number(detail.workers||1)===1?'':'s'}`;
    case 'job_finished': return detail.message?`${detail.status||'saved'} · ${detail.message}`:(detail.status||'saved');
    case 'job_created': return `${detail.workers||1} worker${Number(detail.workers||1)===1?'':'s'} · ${detail.albums||0} album${Number(detail.albums||0)===1?'':'s'}`;
    default: return '';
  }
}
function ensureJobEventPanel(){
  let panel=$('jobEventPanel');
  if(panel)return panel;
  const error=$('jobError');
  if(!error)return null;
  panel=document.createElement('details');
  panel.id='jobEventPanel';
  panel.className='jobEventPanel';
  panel.innerHTML='<summary><strong>Job activity</strong><span id="jobEventCount" class="muted"></span></summary><div id="jobEventRows" class="jobEventRows"></div>';
  error.insertAdjacentElement('afterend',panel);
  return panel;
}
function updateJobEventPanel(job){
  const panel=ensureJobEventPanel();
  if(!panel)return;
  const events=job.recent_events||[];
  $('jobEventCount').textContent=events.length?`${events.length} recent event${events.length===1?'':'s'}`:'No recorded changes';
  $('jobEventRows').innerHTML=events.length?events.map(event=>{
    const detail=jobEventDetail(event);
    return `<div class="jobEventRow"><span class="jobEventTime muted">${esc(fmtTime(event.occurred_at))}</span><strong>${esc(jobEventLabel(event.event_type))}</strong>${detail?`<span>${esc(detail)}</span>`:'<span></span>'}</div>`;
  }).join(''):'<div class="muted">No control or safety events have been recorded for this job.</div>';
}

const jobEventBaseRender=renderJob;
renderJob=function(job){
  jobEventBaseRender(job);
  updateJobEventPanel(job);
};
