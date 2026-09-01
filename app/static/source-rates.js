activeRates=function(){
  const rates=[];
  if($('r882')?.checked)rates.push(88200);
  if($('r96')?.checked)rates.push(96000);
  if($('r1764')?.checked)rates.push(176400);
  if($('r192')?.checked)rates.push(192000);
  return rates;
};

for(const id of ['r882','r1764']){
  const input=$(id);
  if(input)input.addEventListener('change',()=>{resetAck();loadCandidates()});
}

openHighRateCandidates=function(){
  if($('r882'))$('r882').checked=false;
  $('r96').checked=true;
  if($('r1764'))$('r1764').checked=false;
  $('r192').checked=true;
  $('above48').checked=false;
  $('healthFilter').value='convertible';
  $('recentFilter').value='all';
  saveLibraryFilters();
  resetAck();
  loadCandidates();
  showView('library');
};

$('homeOpenCandidates').onclick=openHighRateCandidates;