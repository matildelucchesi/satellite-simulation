/* Schematic view of the two orbital planes: each plane is a ring, satellites sit at their
   argument of latitude. Laser links, the controller domain, the service path and the migration
   path of the selected event are drawn on top. Geometry is modeled, not to scale. */
const ORBIT_SIZE={width:640,height:640};

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

function renderOrbit(svg,topology){
 const ns='http://www.w3.org/2000/svg';
 const make=(tag,attributes,parent)=>{const element=document.createElementNS(ns,tag);for(const [key,value] of Object.entries(attributes))element.setAttribute(key,value);parent.append(element);return element;};
 svg.replaceChildren();
 svg.setAttribute('viewBox',`0 0 ${ORBIT_SIZE.width} ${ORBIT_SIZE.height}`);
 const layout=orbitLayout(topology.nodes);
 make('circle',{cx:layout.cx,cy:layout.cy,r:layout.inner-70,class:'earth'},svg);
 make('circle',{cx:layout.cx,cy:layout.cy,r:layout.inner,class:'ring'},svg);
 make('circle',{cx:layout.cx,cy:layout.cy,r:layout.outer,class:'ring'},svg);
 const service=pathEdges(topology.service_path),migration=pathEdges(topology.migration_path);
 const links=make('g',{class:'links'},svg);
 for(const [a,b,kind] of topology.links){
  const p=layout.positions.get(a),q=layout.positions.get(b);if(!p||!q)continue;
  const key=[a,b].sort((x,y)=>x-y).join('-');
  const role=migration.has(key)?' migration':service.has(key)?' service':'';
  make('line',{x1:p.x,y1:p.y,x2:q.x,y2:q.y,class:`link ${kind||''}${role}`},links);
 }
 const event=topology.event;
 const group=make('g',{class:'satellites'},svg);
 for(const node of topology.nodes){
  const p=layout.positions.get(node.norad);
  const classes=['satellite',node.in_domain?'domain':'outside',node.eclipsed?'shadow':'lit'];
  if(event&&node.norad===event.source)classes.push('source');
  if(event&&node.norad===event.destination)classes.push('destination');
  const item=make('circle',{cx:p.x,cy:p.y,r:node.in_domain?7:4.5,class:classes.join(' ')},group);
  const title=document.createElementNS(ns,'title');
  title.textContent=`NORAD ${node.norad} · piano ${node.plane} · ${node.in_domain?'dominio del controller':'solo modello'} · ${node.eclipsed?'in ombra':'al sole'}`;
  item.append(title);
 }
 if(event){
  for(const [norad,label] of [[event.source,'S'],[event.destination,'D']]){
   const p=layout.positions.get(norad);if(!p)continue;
   const text=make('text',{x:p.x,y:p.y-12,class:'marker'},svg);text.textContent=label;
  }
 }
}

if(typeof module!=='undefined')module.exports={orbitLayout,pathEdges,ORBIT_SIZE};
