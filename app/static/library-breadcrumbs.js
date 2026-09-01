const libraryBreadcrumbState={key:null};

function libraryBreadcrumbSvg(){
  return '<svg class="libraryBreadcrumbChevron" viewBox="0 0 24 24" aria-hidden="true"><path d="M9 5l7 7-7 7"/></svg>';
}
function libraryBreadcrumbRender(album=null){
  const box=$('libraryBreadcrumb');
  if(!box)return;
  if(!album){
    libraryBreadcrumbState.key=null;
    box.innerHTML='<button type="button" class="libraryBreadcrumbRoot">Library</button>';
  }else{
    libraryBreadcrumbState.key=selectedKey(album);
    box.innerHTML=`<button type="button" class="libraryBreadcrumbRoot">Library</button>${libraryBreadcrumbSvg()}<span class="libraryBreadcrumbPart">${esc(album.albumartist||'Missing Album Artist')}</span>${libraryBreadcrumbSvg()}<span class="libraryBreadcrumbCurrent">${esc(album.album||'Missing Album')}</span>`;
  }
  box.querySelector('.libraryBreadcrumbRoot').onclick=()=>{
    libraryBreadcrumbState.key=null;
    openAlbumDetails.clear();
    render();
    libraryBreadcrumbRender();
  };
}
function libraryBreadcrumbInstall(){
  if($('libraryBreadcrumb'))return;
  const view=$('libraryView');
  if(!view)return;
  const nav=document.createElement('nav');
  nav.id='libraryBreadcrumb';
  nav.className='libraryBreadcrumb';
  nav.setAttribute('aria-label','Library location');
  view.insertBefore(nav,view.firstChild);

  const style=document.createElement('style');
  style.dataset.libraryBreadcrumb='1';
  style.textContent=`
    .libraryBreadcrumb{display:flex;align-items:center;gap:7px;min-height:30px;margin:0 0 10px;color:var(--muted);font-size:13px;overflow:hidden}
    .libraryBreadcrumb button{padding:3px 7px;border:0;background:transparent;color:var(--muted);font:inherit;border-radius:6px}
    .libraryBreadcrumb button:hover{background:var(--panel2);color:var(--text)}
    .libraryBreadcrumbChevron{width:14px;height:14px;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round;flex:0 0 auto}
    .libraryBreadcrumbPart,.libraryBreadcrumbCurrent{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:34vw}
    .libraryBreadcrumbCurrent{color:var(--text);font-weight:650}
  `;
  document.head.appendChild(style);
  libraryBreadcrumbRender();
}

libraryBreadcrumbInstall();

const libraryBreadcrumbBaseToggle=toggleAlbumDetail;
toggleAlbumDetail=function(key,force=null){
  libraryBreadcrumbBaseToggle(key,force);
  const open=openAlbumDetails.has(key);
  if(open){
    const album=state.albums.find(item=>selectedKey(item)===key);
    libraryBreadcrumbRender(album||null);
  }else if(libraryBreadcrumbState.key===key){
    libraryBreadcrumbRender();
  }
};

const libraryBreadcrumbBaseSetAll=setAllVisibleDetails;
setAllVisibleDetails=function(open){
  libraryBreadcrumbBaseSetAll(open);
  if(!open)libraryBreadcrumbRender();
};
