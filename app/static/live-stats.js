const LIVE_STATS_WINDOW_MS=30*60*1000;
const LIVE_STATS_MAX_SAMPLES=40;
const liveStatsState={jobId:null,lastStatus:null,samples:[]};
const liveRuntimeState={jobId:null,lastFetch:0,pending:false,previous:null};

(function installLiveStatsStyles(){
  if(document.querySelector('link[data-live-stats]'))return;
  const link=document.createElement('link');
  link.rel='stylesheet';
  link.href='/static/live-stats.css';
  link.dataset.liveStats='1';
  document.head.appendChild(link);
})();

function liveSeconds(value){
  const seconds=Math.max(0,Math.round(Number(value)||0));
  if(seconds<60)return `${seconds}s`;
  const minutes=Math.floor(seconds/60),rest=seconds%60;
  if(minutes<60)return `${minutes}m ${rest}s`;
  const hours=Math.floor(minutes/60),mins=minutes%60;
  if(hours<24)return `${hours}h ${mins}m`;
  const days=Math.floor(hours/24),hrs=hours%24;
  return `${days}d ${hrs}h`;
}
function liveRate(bytesPerSecond){
  const value=Number(bytesPerSecond);
  return Number.isFinite(value)&&value>0?`${fmtBytes(value)}/s`:'Learning…';
}
function liveIoRate(bytesPerSecond){
  const value=Number(bytesPerSecond);
  return Number.isFinite(value)&&value>=0?`${fmtBytes(value)}/s`:'—';
}
function liveFilesPerHour(value){
  const rate=Number(value);
  if(!Number.isFinite(rate)||rate<=0)return 'Learning…';
  return rate>=10?`${Math.round(rate)}/hr`:`${rate.toFixed(1)}/hr`;
}
function liveFinish(etaSeconds){
  if(!Number.isFinite(etaSeconds)||etaSeconds<0)return 'Learning…';
  return new Date(Date.now()+etaSeconds*1000).toLocaleTimeString([],{hour:'numeric',minute:'2-digit'});
}
function liveElapsed(j){
  if(!j.started_at)return null;
  const start=Date.parse(j.started_at);
  const end=j.finished_at?Date.parse(j.finished_at):Date.now();
  if(!Number.isFinite(start)||!Number.isFinite(end)||end<start)return null;
  return (end-start)/1000;
}
function liveByteCounts(j){
  const bytes=j.bytes_by_status||{};
  const completed=Number(bytes.completed||0);
  const failed=Number(bytes.failed||0);
  const pending=Number(bytes.pending||0);
  const running=Number(bytes.running||0);
  return {completed,failed,processed:completed+failed,remaining:pending+running};
}
function liveReset(j){
  liveStatsState.jobId=Number(j.id);
  liveStatsState.lastStatus=j.status;
  liveStatsState.samples=[];
  const bytes=liveByteCounts(j);
  liveStatsState.samples.push({time:Date.now(),bytes:bytes.completed,files:Number(j.counts?.completed||0)});
}
function liveSample(j){
  const id=Number(j.id),status=String(j.status||'');
  if(liveStatsState.jobId!==id){liveReset(j);return}
  const wasActive=['running','pausing','stopping','cancelling'].includes(liveStatsState.lastStatus||'');
  const isRunning=status==='running';
  if(isRunning&&!wasActive){liveReset(j);return}
  liveStatsState.lastStatus=status;
  if(!['running','pausing','stopping','cancelling'].includes(status))return;

  const now=Date.now(),bytes=liveByteCounts(j),files=Number(j.counts?.completed||0);
  const last=liveStatsState.samples[liveStatsState.samples.length-1];
  if(!last||last.bytes!==bytes.completed||last.files!==files){
    liveStatsState.samples.push({time:now,bytes:bytes.completed,files});
  }
  liveStatsState.samples=liveStatsState.samples
    .filter(sample=>now-sample.time<=LIVE_STATS_WINDOW_MS)
    .slice(-LIVE_STATS_MAX_SAMPLES);
}
function liveEstimate(){
  const samples=liveStatsState.samples;
  if(samples.length<2)return {bytesPerSecond:null,filesPerHour:null};
  const newest=samples[samples.length-1];
  let oldest=null;
  for(const sample of samples){
    if(sample.time<newest.time&&(sample.bytes<newest.bytes||sample.files<newest.files)){oldest=sample;break}
  }
  if(!oldest)return {bytesPerSecond:null,filesPerHour:null};
  const seconds=(newest.time-oldest.time)/1000;
  if(seconds<=0)return {bytesPerSecond:null,filesPerHour:null};
  const byteDelta=newest.bytes-oldest.bytes;
  const fileDelta=newest.files-oldest.files;
  return {
    bytesPerSecond:byteDelta>0?byteDelta/seconds:null,
    filesPerHour:fileDelta>0?(fileDelta/seconds)*3600:null,
  };
}
function ensureLiveStatsPanel(){
  let panel=document.getElementById('jobTelemetry');
  if(panel)return panel;
  const stats=document.querySelector('#activeJob .jobStats');
  if(!stats)return null;
  panel=document.createElement('section');
  panel.id='jobTelemetry';
  panel.className='jobTelemetry';
  panel.innerHTML=`
    <div class="telemetryHeader"><strong>Live conversion telemetry</strong><span id="jobTelemetryNote" class="muted">Updates as files finish</span></div>
    <div class="telemetryGrid">
      <div class="telemetryStat"><span>Source processed</span><strong id="jobSourceProcessed">—</strong></div>
      <div class="telemetryStat"><span>Source remaining</span><strong id="jobSourceRemaining">—</strong></div>
      <div class="telemetryStat"><span>Conversion throughput</span><strong id="jobThroughput">—</strong></div>
      <div class="telemetryStat"><span>Completion rate</span><strong id="jobFilesPerHour">—</strong></div>
      <div class="telemetryStat"><span>ETA</span><strong id="jobEta">—</strong></div>
      <div class="telemetryStat"><span>Estimated finish</span><strong id="jobFinishEstimate">—</strong></div>
      <div class="telemetryStat"><span>Wall time</span><strong id="jobWallTime">—</strong></div>
      <div class="telemetryStat"><span>File-active time</span><strong id="jobActiveTime">—</strong></div>
      <div class="telemetryStat"><span>Paused / idle</span><strong id="jobPausedTime">—</strong></div>
      <div class="telemetryStat"><span>NAS read</span><strong id="jobNasRead">—</strong></div>
      <div class="telemetryStat"><span>NAS write</span><strong id="jobNasWrite">—</strong></div>
      <div class="telemetryStat"><span>CPU / memory</span><strong id="jobCpuMemory">—</strong></div>
      <div class="telemetryStat"><span>Safe to Restart</span><strong id="jobSafeRestart" class="statusPill">—</strong></div>
    </div>
    <div class="telemetryFootnote muted">NAS read/write counters are system-wide and may include activity from other TrueNAS apps.</div>`;
  stats.insertAdjacentElement('afterend',panel);
  return panel;
}
function updateCurrentFileTelemetry(j){
  const files=j.current_files||[];
  const cards=[...document.querySelectorAll('#jobCurrentList .currentFile')];
  cards.forEach((card,index)=>{
    const file=files[index];if(!file)return;
    const started=Date.parse(file.started_at||'');
    const elapsed=Number.isFinite(started)?Math.max(0,(Date.now()-started)/1000):null;
    const line=document.createElement('div');
    line.className='liveCurrentMeta muted';
    line.textContent=[elapsed===null?null:`Running ${liveSeconds(elapsed)}`,file.source_bytes?`${fmtBytes(file.source_bytes)} source`:null].filter(Boolean).join(' · ');
    card.appendChild(line);
  });
}
function resetRuntimeSamples(jobId){
  liveRuntimeState.jobId=Number(jobId);
  liveRuntimeState.previous=null;
  liveRuntimeState.lastFetch=0;
}
async function updateRuntimeMetrics(j){
  const jobId=Number(j.id);
  if(liveRuntimeState.jobId!==jobId)resetRuntimeSamples(jobId);
  const now=Date.now();
  if(liveRuntimeState.pending||now-liveRuntimeState.lastFetch<2500)return;
  liveRuntimeState.pending=true;
  liveRuntimeState.lastFetch=now;
  try{
    const response=await fetch(`/api/runtime/metrics?job_id=${jobId}`);
    if(!response.ok)throw new Error('Runtime metrics unavailable');
    const data=await response.json();
    const sample={
      time:Date.now(),
      read:Number(data.disk_read_bytes_total),
      write:Number(data.disk_write_bytes_total),
    };
    let readRate=null,writeRate=null;
    const previous=liveRuntimeState.previous;
    if(previous&&Number.isFinite(sample.read)&&Number.isFinite(sample.write)&&sample.read>=previous.read&&sample.write>=previous.write){
      const seconds=(sample.time-previous.time)/1000;
      if(seconds>0){readRate=(sample.read-previous.read)/seconds;writeRate=(sample.write-previous.write)/seconds}
    }
    liveRuntimeState.previous=sample;
    $('jobNasRead').textContent=liveIoRate(readRate);
    $('jobNasWrite').textContent=liveIoRate(writeRate);
    $('jobCpuMemory').textContent=`${Math.round(Number(data.cpu_percent||0))}% / ${Math.round(Number(data.memory_percent||0))}%`;
    $('jobActiveTime').textContent=liveSeconds(data.job_time?.active_seconds||0);
    $('jobPausedTime').textContent=liveSeconds(data.job_time?.paused_or_idle_seconds||0);
    $('jobSafeRestart').textContent=data.safe_to_restart?'Safe':'Wait';
    $('jobSafeRestart').className=`statusPill ${data.safe_to_restart?'completed':'interrupted'}`;
    $('jobSafeRestart').title=data.safe_to_restart_reason||'';
  }catch(e){
    $('jobNasRead').textContent='—';$('jobNasWrite').textContent='—';$('jobCpuMemory').textContent='—';
  }finally{
    liveRuntimeState.pending=false;
  }
}
function updateLiveStats(j){
  const panel=ensureLiveStatsPanel();if(!panel)return;
  liveSample(j);
  const bytes=liveByteCounts(j),estimate=liveEstimate();
  const active=['running','pausing','stopping','cancelling'].includes(j.status);
  const paused=['paused','interrupted'].includes(j.status);
  let eta=null;
  if(active&&estimate.bytesPerSecond&&bytes.remaining>0)eta=bytes.remaining/estimate.bytesPerSecond;

  $('jobSourceProcessed').textContent=fmtBytes(bytes.processed);
  $('jobSourceRemaining').textContent=fmtBytes(bytes.remaining);
  $('jobThroughput').textContent=active?liveRate(estimate.bytesPerSecond):(j.status==='completed'?'Finished':'—');
  $('jobFilesPerHour').textContent=active?liveFilesPerHour(estimate.filesPerHour):'—';
  $('jobEta').textContent=j.status==='completed'?'Done':paused?'Paused':eta===null?'Learning…':liveSeconds(eta);
  $('jobFinishEstimate').textContent=j.status==='completed'?(j.finished_at?fmtTime(j.finished_at):'Done'):paused?'Unavailable':eta===null?'Learning…':liveFinish(eta);
  const elapsed=liveElapsed(j);$('jobWallTime').textContent=elapsed===null?'—':liveSeconds(elapsed);
  $('jobTelemetryNote').textContent=active
    ?(estimate.bytesPerSecond?'Rolling estimate from completed files':'Learning after the next completed file')
    :(paused?'ETA is unavailable while paused':'Final job statistics');
  updateCurrentFileTelemetry(j);
  updateRuntimeMetrics(j);
}

const baseRenderJobForLiveStats=renderJob;
renderJob=function(j){
  baseRenderJobForLiveStats(j);
  updateLiveStats(j);
};
