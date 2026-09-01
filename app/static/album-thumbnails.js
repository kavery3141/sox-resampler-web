function albumThumbnailPlaceholder(){
  const placeholder=document.createElement('div');
  placeholder.className='albumThumb albumThumbPlaceholder';
  placeholder.setAttribute('role','img');
  placeholder.setAttribute('aria-label','No cached album artwork');
  const inset=document.createElement('span');
  inset.className='albumThumbPlaceholderInset';
  placeholder.appendChild(inset);
  return placeholder;
}

function albumThumbnailNode(album){
  if(!album.artwork_url)return albumThumbnailPlaceholder();
  const frame=document.createElement('div');
  frame.className='albumThumb';
  const image=document.createElement('img');
  image.src=album.artwork_url;
  image.alt='';
  image.loading='lazy';
  image.decoding='async';
  image.width=58;
  image.height=58;
  image.addEventListener('error',()=>{
    frame.replaceWith(albumThumbnailPlaceholder());
  },{once:true});
  frame.appendChild(image);
  return frame;
}

function decorateAlbumThumbnails(){
  for(const row of document.querySelectorAll('#results .row[data-key]')){
    const key=decodeURIComponent(row.dataset.key||'');
    const album=state.albums.find(item=>selectedKey(item)===key);
    if(!album)continue;
    const cell=row.children[1];
    if(!cell||cell.querySelector('.albumThumb'))continue;
    cell.classList.add('albumCellWithThumb');
    cell.prepend(albumThumbnailNode(album));
  }
}

(function installAlbumThumbnailStyles(){
  if(document.querySelector('style[data-album-thumbnails]'))return;
  const style=document.createElement('style');
  style.dataset.albumThumbnails='1';
  style.textContent=`
    .albumCellWithThumb{display:grid;grid-template-columns:58px minmax(0,1fr);column-gap:11px;align-items:center}
    .albumCellWithThumb>.albumThumb{grid-row:1 / span 4;grid-column:1}
    .albumCellWithThumb>.album-artist,.albumCellWithThumb>.album-title,.albumCellWithThumb>.badges,.albumCellWithThumb>.detailsBtn{grid-column:2}
    .albumThumb{width:58px;height:58px;border-radius:7px;overflow:hidden;background:var(--panel2);border:1px solid var(--border);display:flex;align-items:center;justify-content:center}
    .albumThumb img{display:block;width:100%;height:100%;object-fit:cover}
    .albumThumbPlaceholderInset{display:block;width:31px;height:31px;border:1px solid var(--border);border-radius:4px;position:relative}
    .albumThumbPlaceholderInset:after{content:'';position:absolute;left:6px;right:6px;bottom:7px;height:8px;border-left:1px solid var(--border);border-bottom:1px solid var(--border);transform:skewY(-28deg)}
    body[data-density='compact'] .albumCellWithThumb{display:block}
    body[data-density='compact'] .albumThumb{display:none}
  `;
  document.head.appendChild(style);
})();

const albumThumbnailBaseRender=render;
render=function(){
  albumThumbnailBaseRender();
  decorateAlbumThumbnails();
};

decorateAlbumThumbnails();
