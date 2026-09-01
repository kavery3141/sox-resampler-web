function formatLibraryRate(rate){
  const hz=Number(rate||0);
  if(!hz)return 'Unknown';
  const khz=hz/1000;
  return `${Number.isInteger(khz)?khz:khz.toFixed(1)} kHz`;
}
function formatLibraryRates(rates){
  const values=(rates||[]).map(formatLibraryRate);
  return values.length?values.join(', '):'None';
}
function albumFolderDetail(album){
  const folders=(album.folders||[]).length?album.folders:[album.folder].filter(Boolean);
  if(folders.length<=1)return '';
  return `<span class="muted">Physical folders</span><span class="multiFolderPaths">${folders.map(path=>`<code>${esc(path)}</code>`).join('')}</span>`;
}

const mixedRateBaseDetailHtml=detailHtml;
detailHtml=function(album){
  const base=mixedRateBaseDetailHtml(album);
  const matching=Number(album.matching_tracks||0);
  const untouched=Number(album.untouched_tracks||0);
  const total=Number(album.total_tracks||0);
  const scope=`<span class="muted">Conversion scope</span><span><strong>${matching}</strong> of ${total} FLAC track${total===1?'':'s'} match the active source-rate filter</span><span class="muted">Will convert</span><span>${matching} track${matching===1?'':'s'} · ${esc(formatLibraryRates(album.source_rates))}</span><span class="muted">Will remain untouched</span><span>${untouched} track${untouched===1?'':'s'}${untouched?` · ${esc(formatLibraryRates(album.untouched_rates))}`:''}</span>${albumFolderDetail(album)}`;
  const close=base.lastIndexOf('</div>');
  return close>=0?`${base.slice(0,close)}${scope}${base.slice(close)}`:`${base}${scope}`;
};

function decorateMixedRateRows(){
  for(const row of document.querySelectorAll('#results .row[data-key]')){
    const key=decodeURIComponent(row.dataset.key||'');
    const album=state.albums.find(item=>selectedKey(item)===key);
    if(!album)continue;
    const badges=row.querySelector('.badges');
    if(!badges)continue;
    if(Number(album.untouched_tracks||0)>0&&!badges.querySelector('[data-mixed-rate-badge]')){
      const badge=document.createElement('span');
      badge.className='badge';
      badge.dataset.mixedRateBadge='1';
      badge.textContent=`Mixed rates · ${album.matching_tracks}/${album.total_tracks} selected`;
      badge.title=`Matching: ${formatLibraryRates(album.source_rates)}; untouched: ${formatLibraryRates(album.untouched_rates)}`;
      badges.appendChild(badge);
    }
    if(Number(album.folder_count||0)>1&&!badges.querySelector('[data-multi-folder-badge]')){
      const badge=document.createElement('span');
      badge.className='badge';
      badge.dataset.multiFolderBadge='1';
      badge.textContent=`${album.folder_count} folders`;
      badge.title='This ALBUMARTIST + ALBUM spans multiple physical folders and is handled as one album.';
      badges.appendChild(badge);
    }
  }
}

(function installMixedRateStyles(){
  if(document.querySelector('style[data-mixed-rate-ui]'))return;
  const style=document.createElement('style');
  style.dataset.mixedRateUi='1';
  style.textContent='.multiFolderPaths{display:grid;gap:5px;min-width:0}.multiFolderPaths code{white-space:normal;overflow-wrap:anywhere}';
  document.head.appendChild(style);
})();

const mixedRateBaseRender=render;
render=function(){
  mixedRateBaseRender();
  decorateMixedRateRows();
};

decorateMixedRateRows();
