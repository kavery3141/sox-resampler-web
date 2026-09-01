const issueUiState={issues:[],severity:'all',query:'',loaded:false};

function issueFolderPaths(issue){
  if((issue.display_folders||[]).length)return issue.display_folders;
  if((issue.folders||[]).length)return issue.folders;
  return [issue.display_folder||issue.folder].filter(Boolean);
}
function issueTrackPath(track){return track?.display_path||track?.path||''}
function issueSummaryText(issue){
  const lines=[
    `[${String(issue.severity||'issue').toUpperCase()}] ${issue.albumartist||'Missing Album Artist'} / ${issue.album||'Missing Album'}`,
    `Issue: ${issue.summary||''}`,
    `Type: ${issue.issue_type||''}`,
  ];
  const folders=issueFolderPaths(issue);
  if(folders.length){
    lines.push(folders.length===1?`Folder: ${folders[0]}`:'Folders:');
    if(folders.length>1)for(const folder of folders)lines.push(`  ${folder}`);
  }
  const tracks=issue.affected_tracks||[];
  if(tracks.length){
    lines.push('Affected tracks:');
    for(const track of tracks){
      const path=issueTrackPath(track)||track.filename||'Unknown track';
      const value=track.value?` — ${track.value}`:'';
      lines.push(`  ${path}${value}`);
    }
  }
  return lines.join('\n');
}
async function issueCopyText(button,text,successLabel='Copied'){
  if(!navigator.clipboard?.writeText)return;
  const prior=button.textContent;
  try{
    await navigator.clipboard.writeText(text);
    button.textContent=successLabel;
    setTimeout(()=>{button.textContent=prior},1200);
  }catch(e){
    button.textContent='Copy failed';
    setTimeout(()=>{button.textContent=prior},1500);
  }
}

function installIssuesUi(){
  const nav=document.querySelector('header nav');
  const issuesButton=document.createElement('button');
  issuesButton.id='navIssues';
  issuesButton.textContent='Metadata Issues';
  const history=$('navHistory');
  nav.insertBefore(issuesButton,history);

  const section=document.createElement('section');
  section.id='issuesView';
  section.className='hidden';
  section.innerHTML=`
    <div class="sectionTitle">
      <div><h2 style="margin-bottom:4px">Metadata Issues</h2><div class="muted">Read-only diagnostics from the local index. Nothing here changes music files or tags.</div></div>
      <span class="spacer"></span><button id="refreshIssues">Refresh</button>
    </div>
    <section class="summary issueSummary" style="margin-top:14px">
      <div class="card metric"><span>All issues</span><strong id="issueCountAll">—</strong></div>
      <div class="card metric"><span>Blocking</span><strong id="issueCountBlocking">—</strong></div>
      <div class="card metric"><span>Warnings</span><strong id="issueCountWarning">—</strong></div>
      <div class="card metric"><span>Informational</span><strong id="issueCountInfo">—</strong></div>
    </section>
    <section class="card" style="margin-bottom:14px">
      <div class="toolbar" style="margin-bottom:0">
        <input id="issueSearch" class="search" type="search" placeholder="Filter by artist, album, folder, issue, or filename…" autocomplete="off">
        <label>Severity <select id="issueSeverity"><option value="all">All</option><option value="blocking">Blocking</option><option value="warning">Warnings</option><option value="info">Informational</option></select></label>
        <a id="issueExportTxt" class="buttonLink" href="/api/library/issues/report.txt?severity=all" download>Export TXT</a>
        <a id="issueExportCsv" class="buttonLink" href="/api/library/issues/report.csv?severity=all" download>Export CSV</a>
      </div>
    </section>
    <div id="issuesNotice" class="notice hidden"></div>
    <div id="issueRows"></div>`;
  document.querySelector('main').appendChild(section);

  const homeActions=document.querySelector('#homeView .homeActions');
  if(homeActions){const button=document.createElement('button');button.id='homeOpenIssues';button.textContent='Metadata Issues';homeActions.appendChild(button)}

  const style=document.createElement('style');
  style.textContent=`
    .issueSummary{grid-template-columns:repeat(4,minmax(130px,1fr))}
    .buttonLink{display:inline-flex;align-items:center;border:1px solid var(--border);background:var(--panel2);color:var(--text);border-radius:9px;padding:9px 12px;text-decoration:none}
    .buttonLink:hover{border-color:#52647a}
    .issueCard{margin-bottom:12px;padding:0;overflow:hidden}
    .issueHead{display:flex;align-items:flex-start;gap:12px;padding:14px 16px;border-bottom:1px solid var(--border)}
    .issueHeadMain{min-width:0;flex:1}.issueHeadActions{display:flex;gap:8px;align-items:flex-start}.issueHeadActions button{white-space:nowrap}.issueAlbum{font-weight:700}.issueArtist{color:var(--muted);font-size:13px;margin-bottom:3px}.issueSummaryText{margin-top:8px}.issueFolder{display:flex;gap:8px;align-items:flex-start;padding:10px 16px;border-bottom:1px solid var(--border);background:#0e1724}.issueFolder code{overflow-wrap:anywhere;flex:1;color:inherit}.issueFolder button,.issueTrack button{padding:5px 8px;font-size:12px;white-space:nowrap}
    body[data-theme="light"] .issueFolder{background:#f8fafc}
    .issueTracks{padding:8px 16px 14px}.issueTrack{display:grid;grid-template-columns:minmax(220px,1fr) minmax(220px,1fr) auto;gap:12px;align-items:center;padding:8px 0;border-bottom:1px solid var(--border)}.issueTrack:last-child{border-bottom:0}.issueTrack code{overflow-wrap:anywhere;color:inherit}.issueType{font-size:11px;color:var(--muted);margin-top:4px}.statusPill.blocking{border-color:#733737;color:#ffb0b0}.statusPill.warning{border-color:#6b5328;color:#ffd393}.statusPill.info{border-color:#365b82;color:#bddcff}
    @media(max-width:900px){.issueSummary{grid-template-columns:1fr 1fr}.issueHead{flex-wrap:wrap}.issueHeadActions{width:100%}.issueTrack{grid-template-columns:1fr}.issueTrack button{justify-self:start}}
  `;
  document.head.appendChild(style);

  const priorShowView=showView;
  showView=function(which){
    if(which==='issues'){
      for(const name of ['home','library','convert','history','settings','maintenance'])$(`${name}View`).classList.add('hidden');
      $('issuesView').classList.remove('hidden');
      for(const name of ['Home','Library','Issues','Convert','History','Settings','Maintenance'])$(`nav${name}`).classList.toggle('active',name==='Issues');
      loadIssues();
      return;
    }
    $('issuesView').classList.add('hidden');
    priorShowView(which);
    $('navIssues').classList.remove('active');
  };

  $('navIssues').onclick=()=>showView('issues');
  $('homeOpenIssues').onclick=()=>showView('issues');
  $('refreshIssues').onclick=()=>loadIssues(true);
  $('issueSeverity').onchange=()=>{issueUiState.severity=$('issueSeverity').value;updateIssueExportLinks();renderIssues()};
  let issueDebounce;
  $('issueSearch').oninput=()=>{clearTimeout(issueDebounce);issueDebounce=setTimeout(()=>{issueUiState.query=$('issueSearch').value.trim().toLowerCase();renderIssues()},180)};
}

function updateIssueExportLinks(){
  const severity=encodeURIComponent(issueUiState.severity||'all');
  $('issueExportTxt').href=`/api/library/issues/report.txt?severity=${severity}`;
  $('issueExportCsv').href=`/api/library/issues/report.csv?severity=${severity}`;
}

async function loadIssues(force=false){
  if(issueUiState.loaded&&!force){renderIssues();return}
  $('issueRows').innerHTML='<section class="card"><div class="muted">Loading metadata diagnostics…</div></section>';
  try{
    const r=await fetch('/api/library/issues?severity=all');
    const d=await r.json();
    if(!r.ok)throw new Error(d.detail||'Unable to load metadata issues');
    issueUiState.issues=d.issues||[];issueUiState.loaded=true;
    const counts={blocking:0,warning:0,info:0};for(const issue of issueUiState.issues)counts[issue.severity]=(counts[issue.severity]||0)+1;
    $('issueCountAll').textContent=issueUiState.issues.length.toLocaleString();
    $('issueCountBlocking').textContent=counts.blocking.toLocaleString();
    $('issueCountWarning').textContent=counts.warning.toLocaleString();
    $('issueCountInfo').textContent=counts.info.toLocaleString();
    $('issuesNotice').classList.add('hidden');
    renderIssues();
  }catch(e){notice('issuesNotice',e.message,'bad');$('issueRows').innerHTML=''}
}

function issueMatches(issue){
  if(issueUiState.severity!=='all'&&issue.severity!==issueUiState.severity)return false;
  if(!issueUiState.query)return true;
  const tracks=(issue.affected_tracks||[]).map(t=>`${t.filename||''} ${issueTrackPath(t)} ${t.value||''}`).join(' ');
  const folders=issueFolderPaths(issue).join(' ');
  return `${issue.albumartist||''} ${issue.album||''} ${issue.display_folder||issue.folder||''} ${folders} ${issue.summary||''} ${issue.issue_type||''} ${tracks}`.toLowerCase().includes(issueUiState.query);
}

function renderIssues(){
  const rows=issueUiState.issues.filter(issueMatches);
  const box=$('issueRows');
  if(!rows.length){box.innerHTML='<section class="card"><div class="muted">No metadata issues match the current filter.</div></section>';return}
  box.innerHTML=rows.map((issue,index)=>{
    const folders=issueFolderPaths(issue);
    return `
    <section class="card issueCard" data-issue-index="${index}">
      <div class="issueHead"><span class="statusPill ${esc(issue.severity)}">${esc(issue.severity)}</span><div class="issueHeadMain"><div class="issueArtist">${esc(issue.albumartist||'Missing Album Artist')}</div><div class="issueAlbum">${esc(issue.album||'Missing Album')}</div><div class="issueSummaryText">${esc(issue.summary||'')}</div><div class="issueType">${esc(issue.issue_type||'')}</div></div><div class="issueHeadActions"><button type="button" data-copy-summary="${index}">Copy Issue Summary</button></div></div>
      ${folders.map((folder,folderIndex)=>`<div class="issueFolder"><span class="muted">${folders.length===1?'Folder':`Folder ${folderIndex+1}`}</span><code>${esc(folder)}</code><button data-copy-folder="${index}:${folderIndex}">Copy Path</button></div>`).join('')}
      <div class="issueTracks">${(issue.affected_tracks||[]).map((track,trackIndex)=>`<div class="issueTrack"><code>${esc(track.filename||issueTrackPath(track)||'Unknown track')}</code><span>${esc(track.value||'')}</span><button data-copy-track="${index}:${trackIndex}">Copy Track Path</button></div>`).join('')}</div>
    </section>`;
  }).join('');

  box.querySelectorAll('[data-copy-summary]').forEach(button=>button.onclick=()=>{const issue=rows[Number(button.dataset.copySummary)];if(issue)issueCopyText(button,issueSummaryText(issue),'Copied Summary')});
  box.querySelectorAll('[data-copy-folder]').forEach(button=>button.onclick=()=>{const [i,f]=button.dataset.copyFolder.split(':').map(Number);const issue=rows[i];const folders=issue?issueFolderPaths(issue):[];issueCopyText(button,folders[f]||'','Copied')});
  box.querySelectorAll('[data-copy-track]').forEach(button=>button.onclick=()=>{const [i,t]=button.dataset.copyTrack.split(':').map(Number);const track=rows[i]?.affected_tracks?.[t];issueCopyText(button,issueTrackPath(track),'Copied')});
}

installIssuesUi();
