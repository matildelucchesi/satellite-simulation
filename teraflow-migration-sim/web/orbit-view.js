/* Live schematic of the two orbital planes. Each plane is a ring and each satellite sits at its
   argument of latitude, moving at its own angular speed between topology samples. Satellites in
   sunlight are yellow, in shadow blue; the satellite that hosts the controller is purple. The
   shadow zone of each ring and the night side of the Earth follow the eclipsed satellites.
   Geometry is modeled, not to scale. */
const ORBIT_SIZE={width:640,height:640};
const SVG_NS='http://www.w3.org/2000/svg';

function orbitLayout(nodes,size=ORBIT_SIZE){
 const cx=size.width/2,cy=size.height/2,outer=Math.min(cx,cy)-46,inner=outer-46;
 const positions=new Map();
 for(const node of nodes){
  const radius=node.plane===1?inner:outer,angle=node.argument_of_latitude_deg*Math.PI/180;
  positions.set(node.norad,{x:cx+radius*Math.cos(angle),y:cy-radius*Math.sin(angle)});
 }
 return {cx,cy,inner,outer,positions};
}

function pathEdges(path){
 const edges=new Set();
 for(let i=1;i<(path||[]).length;i++)edges.add([path[i-1],path[i]].sort((a,b)=>a-b).join('-'));
 return edges;
}

/* Angle and illumination of a satellite at an orbital instant, from one topology sample. */
function nodeAt(node,sampleS,orbitalS){
 const dt=orbitalS-sampleS;
 const angle=((node.argument_of_latitude_deg+(node.argument_of_latitude_rate_deg_s||0)*dt)%360+360)%360;
 const flipped=Number.isFinite(node.next_transition_s)&&orbitalS>=node.next_transition_s&&sampleS<node.next_transition_s;
 return {angle,eclipsed:flipped?!node.eclipsed:node.eclipsed};
}

/* Mean direction of a set of angles in degrees, or null for an empty set. */
function circularMean(angles){
 if(!angles.length)return null;
 let x=0,y=0;for(const a of angles){x+=Math.cos(a*Math.PI/180);y+=Math.sin(a*Math.PI/180);}
 return Math.hypot(x,y)<1e-9?null:(Math.atan2(y,x)*180/Math.PI+360)%360;
}

function createOrbitScene(svg){
 const make=(tag,attributes,parent)=>{const element=document.createElementNS(SVG_NS,tag);for(const [key,value] of Object.entries(attributes||{}))element.setAttribute(key,value);if(parent)parent.append(element);return element;};
 svg.replaceChildren();
 svg.setAttribute('viewBox',`0 0 ${ORBIT_SIZE.width} ${ORBIT_SIZE.height}`);
 const base=orbitLayout([]),{cx,cy,inner,outer}=base,earthR=inner-70;
 const point=(plane,angle)=>{const r=plane===1?inner:outer,a=angle*Math.PI/180;return {x:cx+r*Math.cos(a),y:cy-r*Math.sin(a)};};

 const defs=make('defs',{},svg);
 const earthFill=make('radialGradient',{id:'earth-fill',r:'78%'},defs);
 for(const [offset,klass] of [['0%','earth-day'],['55%','earth-mid'],['100%','earth-night']])make('stop',{offset,class:klass},earthFill);
 const halo=make('radialGradient',{id:'earth-halo'},defs);
 for(const [offset,klass] of [['80%','halo-inner'],['100%','halo-outer']])make('stop',{offset,class:klass},halo);
 for(const [id,blur] of [['glow-sun',2.4],['glow-controller',4]]){
  const filter=make('filter',{id,x:'-150%',y:'-150%',width:'400%',height:'400%'},defs);
  make('feGaussianBlur',{in:'SourceGraphic',stdDeviation:blur,result:'blur'},filter);
  const merge=make('feMerge',{},filter);make('feMergeNode',{in:'blur'},merge);make('feMergeNode',{in:'SourceGraphic'},merge);
 }

 const sky=make('g',{class:'sky','aria-hidden':'true'},svg);
 if(typeof starField==='function')for(const star of starField(ORBIT_SIZE.width,ORBIT_SIZE.height,{density:1/900,seed:11}))
  make('circle',{cx:star.x.toFixed(1),cy:star.y.toFixed(1),r:(star.r*.9).toFixed(2),fill:`rgb(${star.tint})`,'fill-opacity':(star.alpha*.8).toFixed(2)},sky);
 const shade=make('path',{class:'shade'},svg);
 make('circle',{cx,cy,r:earthR*1.14,class:'atmosphere'},svg);
 make('circle',{cx,cy,r:earthR,class:'earth'},svg);
 make('circle',{cx,cy,r:inner,class:'ring'},svg);
 make('circle',{cx,cy,r:outer,class:'ring'},svg);
 const linkLayer=make('g',{class:'links'},svg);
 /* The laser links the controller crosses to reach the destination, drawn over the plain links */
 const routeLayer=make('g',{class:'route-layer'},svg);
 const route=make('polyline',{class:'route'},routeLayer);
 const relays=make('g',{class:'relays'},routeLayer);
 const flow=make('polyline',{class:'route-flow'},svg);
 const leader=make('line',{class:'leader'},svg);
 const shadowLayer=make('g',{class:'sats shadow'},svg);
 const litLayer=make('g',{class:'sats lit',filter:'url(#glow-sun)'},svg);
 const targetRing=make('circle',{r:12,class:'target-ring'},svg);
 const controllerLayer=make('g',{class:'controller',filter:'url(#glow-controller)'},svg);
 const halo2=make('circle',{r:16,class:'controller-ring'},controllerLayer);
 const core=make('circle',{r:8.5,class:'controller-core'},controllerLayer);
 const tags=make('g',{class:'tags'},svg);
 const hostTag=make('text',{class:'tag-label host'},tags),targetTag=make('text',{class:'tag-label'},tags);

 let sample=null,satellites=new Map(),links=[];

 function setTopology(topology){
  const ids=topology.nodes.map(node=>node.norad).join(',');
  if(!sample||sample.ids!==ids){
   shadowLayer.replaceChildren();litLayer.replaceChildren();satellites=new Map();
   for(const node of topology.nodes){
    const circle=make('circle',{r:node.in_domain?6:3.8,class:node.in_domain?'sat domain':'sat outside'});
    const title=make('title',{},circle);
    satellites.set(node.norad,{circle,title,lit:null});
   }
  }
  const service=pathEdges(topology.service_path);
  const linkIds=topology.links.map(([a,b])=>a+'-'+b).join(',');
  if(!sample||sample.linkIds!==linkIds){
   linkLayer.replaceChildren();
   links=topology.links.map(([a,b,kind])=>({a,b,element:make('line',{class:`link ${kind||''}${service.has([a,b].sort((x,y)=>x-y).join('-'))?' service':''}`},linkLayer)}));
  }
  sample={ids,linkIds,orbital:topology.orbital_s,nodes:new Map(topology.nodes.map(node=>[node.norad,node])),route:topology.migration_path||[]};
 }

 /* view: {controller, controllerState, linkActive, transferring, communicating, source, destination} */
 function update(orbitalS,view={}){
  if(!sample)return null;
  const where=new Map(),eclipsed=[];
  for(const [norad,node] of sample.nodes){
   const state=nodeAt(node,sample.orbital,orbitalS),p=point(node.plane,state.angle);
   where.set(norad,{...p,plane:node.plane,angle:state.angle,eclipsed:state.eclipsed});
   if(state.eclipsed)eclipsed.push(state.angle);
   const item=satellites.get(norad);if(!item)continue;
   item.circle.setAttribute('cx',p.x.toFixed(2));item.circle.setAttribute('cy',p.y.toFixed(2));
   const lit=!state.eclipsed;
   if(item.lit!==lit){
    item.lit=lit;(lit?litLayer:shadowLayer).append(item.circle);
    item.title.textContent=`NORAD ${norad} · piano ${node.plane} · ${node.in_domain?'dominio del controller':'solo modello'} · ${lit?'al sole':'in ombra'}`;
   }
  }
  for(const link of links){
   const p=where.get(link.a),q=where.get(link.b);if(!p||!q)continue;
   link.element.setAttribute('x1',p.x.toFixed(2));link.element.setAttribute('y1',p.y.toFixed(2));
   link.element.setAttribute('x2',q.x.toFixed(2));link.element.setAttribute('y2',q.y.toFixed(2));
  }
  /* Shadow zone: arcs of each ring between consecutive eclipsed satellites */
  let d='';
  for(const plane of [1,2]){
   const ring=[...where.values()].filter(row=>row.plane===plane).sort((a,b)=>a.angle-b.angle);
   for(let i=0;i<ring.length;i++){
    const a=ring[i],b=ring[(i+1)%ring.length];
    if(!a.eclipsed||!b.eclipsed)continue;
    const span=((b.angle-a.angle)%360+360)%360;if(span>90)continue;
    const r=plane===1?inner:outer;
    d+=`M${a.x.toFixed(1)} ${a.y.toFixed(1)}A${r} ${r} 0 0 0 ${b.x.toFixed(1)} ${b.y.toFixed(1)}`;
   }
  }
  shade.setAttribute('d',d);
  /* Night side of the Earth faces the shadow zone */
  const night=circularMean(eclipsed);
  if(night!==null){
   const sun=(night+180)*Math.PI/180;
   earthFill.setAttribute('cx',(50+30*Math.cos(sun)).toFixed(1)+'%');earthFill.setAttribute('cy',(50-30*Math.sin(sun)).toFixed(1)+'%');
   earthFill.setAttribute('fx',(50+38*Math.cos(sun)).toFixed(1)+'%');earthFill.setAttribute('fy',(50-38*Math.sin(sun)).toFixed(1)+'%');
  }
  /* Migration route, highlighted once the destination is chosen */
  const routePoints=sample.route.map(id=>where.get(id)).filter(Boolean);
  const pointsAttribute=routePoints.map(p=>`${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ');
  route.setAttribute('points',pointsAttribute);flow.setAttribute('points',pointsAttribute);
  /* Satellites that relay the transfer between the controller and the destination */
  const middle=routePoints.slice(1,-1);
  while(relays.childElementCount<middle.length)make('circle',{r:11,class:'relay'},relays);
  [...relays.children].forEach((ring,index)=>{const p=middle[index];ring.style.display=p?'':'none';if(p){ring.setAttribute('cx',p.x.toFixed(2));ring.setAttribute('cy',p.y.toFixed(2));}});
  svg.classList.toggle('route-planned',Boolean(!view.linkActive&&routePoints.length>1));
  svg.classList.toggle('route-active',Boolean(view.linkActive&&routePoints.length>1));
  svg.classList.toggle('route-flowing',Boolean(view.transferring));
  /* While the route carries the migration (alignment and transfers) its relays are filled */
  svg.classList.toggle('route-talking',Boolean(view.communicating));
  const target=where.get(view.destination);
  targetRing.style.display=target&&view.destination!==view.controller?'':'none';
  if(target){targetRing.setAttribute('cx',target.x.toFixed(2));targetRing.setAttribute('cy',target.y.toFixed(2));}
  /* Controller host */
  const host=where.get(view.controller);
  controllerLayer.style.display=host?'':'none';
  if(host){for(const element of [halo2,core]){element.setAttribute('cx',host.x.toFixed(2));element.setAttribute('cy',host.y.toFixed(2));}}
  controllerLayer.dataset.state=view.controllerState||'active';
  /* The host is named after what it carries: the controller; the destination keeps its role until the cutover */
  for(const [tag,id,text] of [[hostTag,view.controller,'controller'],[targetTag,view.destination!==view.controller?view.destination:null,'destinazione']]){
   const p=where.get(id);tag.style.display=p?'':'none';if(!p)continue;
   /* Inner ring: label towards the Earth; outer ring: label towards space. Either way it never
      lands next to a satellite of the other ring. */
   const inward=p.plane===1,a=Math.atan2(cy-p.y,p.x-cx),r=Math.hypot(p.x-cx,p.y-cy)+(inward?-20:20);
   const c=Math.cos(a)*(inward?-1:1);
   tag.setAttribute('x',(cx+r*Math.cos(a)).toFixed(1));tag.setAttribute('y',(cy-r*Math.sin(a)+4).toFixed(1));
   tag.setAttribute('text-anchor',c>.3?'start':c<-.3?'end':'middle');tag.textContent=text;
  }
  /* Anchor for the phase label: over the Earth, towards the middle of the route */
  let anchor=null;
  if(routePoints.length){
   const mid=routePoints[Math.floor(routePoints.length/2)],a=Math.atan2(cy-mid.y,mid.x-cx);
   /* The label opens away from the route, towards the far side of the Earth */
   anchor={x:cx+earthR*.62*Math.cos(a),y:cy-earthR*.42*Math.sin(a),routeX:mid.x,routeY:mid.y,side:Math.cos(a)<0?'left':'right'};
   leader.setAttribute('x1',anchor.x.toFixed(1));leader.setAttribute('y1',anchor.y.toFixed(1));
   leader.setAttribute('x2',mid.x.toFixed(1));leader.setAttribute('y2',mid.y.toFixed(1));
  }
  return {anchor,size:ORBIT_SIZE};
 }

 return {setTopology,update,get sampleOrbital(){return sample?sample.orbital:null;}};
}

if(typeof module!=='undefined')module.exports={orbitLayout,pathEdges,nodeAt,circularMean,ORBIT_SIZE};
