function resourceControlInstall(){
  if($("resourceControlCard"))return;
  const view=$("settingsView");
  if(!view)return;
  const card=document.createElement("section");
  card.id="resourceControlCard";
  card.className="card";
  card.style.marginTop="14px";
  card.innerHTML=`
    <h3 style="margin-top:0">Conversion resource control</h3>
    <div class="muted" style="margin-bottom:12px">Optional CPU throttling applies only to the SoX resampling process and is disabled by default. The percentage is a per-worker ceiling relative to one logical CPU; with two workers, each worker is capped independently. Changes take effect when the next file starts and never start conversion.</div>
    <div class="resourceControlRow">
      <label class="resourceControlToggle"><input id="cpuCapEnabled" type="checkbox"> Enable per-worker CPU cap</label>
      <label>CPU cap per worker (%)<input id="cpuCapPercent" type="number" min="10" max="100" step="5" value="75"></label>
      <div><span class="muted">Limiter runtime</span><strong id="cpuCapRuntime">—</strong></div>
      <div><span class="muted">Current setting</span><strong id="cpuCapState">Disabled</strong></div>
    </div>
    <div class="toolbar" style="margin-top:14px"><button id="saveResourceControl" class="primary">Save Resource Control</button></div>
    <div id="resourceControlNotice" class="notice hidden"></div>`;
  const reset=$("resetDefaultsCard");
  if(reset)reset.insertAdjacentElement("beforebegin",card);else view.appendChild(card);

  if(!document.querySelector("style[data-resource-control]")){
    const style=document.createElement("style");
    style.dataset.resourceControl="1";
    style.textContent=`.resourceControlRow{display:grid;grid-template-columns:minmax(220px,1.2fr) minmax(190px,.8fr) minmax(160px,.7fr) minmax(160px,.7fr);gap:14px;align-items:end}.resourceControlRow>div,.resourceControlRow>label{display:grid;gap:6px}.resourceControlToggle{display:flex!important;align-items:center;gap:8px;padding-bottom:9px}@media(max-width:900px){.resourceControlRow{grid-template-columns:1fr}}`;
    document.head.appendChild(style);
  }
  $("cpuCapEnabled").onchange=resourceControlToggle;
  $("saveResourceControl").onclick=resourceControlSave;
}

function resourceControlToggle(){
  const enabled=Boolean($("cpuCapEnabled")?.checked);
  if($("cpuCapPercent"))$("cpuCapPercent").disabled=!enabled;
}

function resourceControlRender(data){
  resourceControlInstall();
  const enabled=Boolean(data.enabled);
  $("cpuCapEnabled").checked=enabled;
  if(data.cpu_limit_percent!==null&&data.cpu_limit_percent!==undefined){
    $("cpuCapPercent").value=String(data.cpu_limit_percent);
  }
  $("cpuCapPercent").min=String(data.min_percent||10);
  $("cpuCapPercent").max=String(data.max_percent||100);
  $("cpuCapRuntime").textContent=data.available?"Available":"Unavailable";
  $("cpuCapState").textContent=enabled?`${data.cpu_limit_percent}% per worker`:"Disabled";
  $("cpuCapEnabled").disabled=!data.available&&!enabled;
  resourceControlToggle();
}

async function resourceControlLoad(){
  resourceControlInstall();
  try{
    const response=await fetch("/api/settings/resources");
    const data=await response.json();
    if(!response.ok)throw new Error(data.detail||"Unable to load resource-control settings");
    resourceControlRender(data);
  }catch(error){notice("resourceControlNotice",error.message,"bad")}
}

async function resourceControlSave(){
  const enabled=Boolean($("cpuCapEnabled").checked);
  let limit=null;
  if(enabled){
    limit=Number($("cpuCapPercent").value);
    const min=Number($("cpuCapPercent").min||10);
    const max=Number($("cpuCapPercent").max||100);
    if(!Number.isInteger(limit)||limit<min||limit>max){
      notice("resourceControlNotice",`CPU cap must be a whole number from ${min} through ${max}.`,"bad");
      return;
    }
  }
  const button=$("saveResourceControl");
  button.disabled=true;
  try{
    const response=await fetch("/api/settings/resources",{
      method:"POST",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify({cpu_limit_percent:limit}),
    });
    const data=await response.json();
    if(!response.ok)throw new Error(data.detail||"Unable to save resource-control settings");
    resourceControlRender(data);
    const suffix=data.active_job_id?` Active job ${data.active_job_id} will use the new setting when its next file starts.`:"";
    notice("resourceControlNotice",data.enabled?`CPU cap set to ${data.cpu_limit_percent}% per worker.${suffix}`:`CPU cap disabled.${suffix}`,"good");
    await loadStatus();
  }catch(error){notice("resourceControlNotice",error.message,"bad")}
  finally{button.disabled=false}
}

resourceControlInstall();
const resourceControlBaseLoadSettings=loadSettings;
loadSettings=async function(){
  await resourceControlBaseLoadSettings();
  await resourceControlLoad();
};
