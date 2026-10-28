fetch('../human-v1/layout.json').then(r=>r.json()).then(layout=>{
  const root=document.getElementById('layers');
  for(const layer of layout.layers){
    const img=new Image();img.src='../human-v1/'+layer.file;img.alt=layer.name;
    img.style.transform=`matrix(${layer.matrix.join(',')})`;
    if(layer.mask){
      const mask=layout.layers.find(l=>l.name===layer.mask), m=mask.matrix, wrap=document.createElement('div');
      Object.assign(wrap.style,{position:'absolute',inset:'0',maskImage:`url(../human-v1/${mask.file})`,maskRepeat:'no-repeat',maskSize:`${1024*m[0]}px ${1536*m[3]}px`,maskPosition:`${m[4]}px ${m[5]}px`});
      wrap.append(img);root.append(wrap);
    }else root.append(img);
  }
});
