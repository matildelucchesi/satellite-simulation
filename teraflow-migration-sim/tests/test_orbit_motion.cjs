const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');

function harness(){
 const elements=new Map(),callbacks=[],intervals=[];let now=500;
 function element(){const classes=new Set();return {dataset:{},style:{},textContent:'',attrs:{},addEventListener(){},
  classList:{toggle(name,on){if(on)classes.add(name);else classes.delete(name);},contains(name){return classes.has(name);}},
  setAttribute(name,value){this.attrs[name]=value;},querySelectorAll(){return [];}};}
 for(const id of ['map-zoom','show-initial','show-service','show-all-phases','satellite-select','orbital-time'])elements.set(id,element());
 const group=element();group.dataset.norad='11';
 const graph=element();graph.querySelectorAll=selector=>selector==='.node'?[group]:[];elements.set('topology',graph);
 const row=element();row.dataset.norad='11';const countdown=element(),label=element(),bar=element();
 row.querySelector=selector=>selector==='strong'?countdown:selector==='.phase-next'?label:bar;
 const list=element();list.querySelectorAll=()=>[row];elements.set('phase-countdowns',list);
 const context=vm.createContext({phaseLabels:{},outcomeLabels:{},$:id=>elements.get(id),
  window:{matchMedia:()=>({matches:false})},performance:{now:()=>now},
  requestAnimationFrame:callback=>{callbacks.push(callback);return callbacks.length;},cancelAnimationFrame(){},
  setInterval:callback=>{intervals.push(callback);},number:value=>Number(value).toFixed(1),
  simulations:[],selectedSimulation:'',simulationTick:null,selectedRun:'',replayTick:null,initialConfigurationRequest:null,URLSearchParams});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../web/orbit-view.js'),'utf8'),context);
 return {context,group,row,countdown,label,elements,intervals,advance(value){now=value;callbacks.shift()(now);}};
}

test('live positions and phase countdown follow the same bounded model clock',()=>{
 const h=harness();
 vm.runInContext(`
  const node=(angle,eclipsed)=>({norad:11,plane:1,phase_rank:0,orbital_angle_rad:angle,eclipsed,
    phase_start_s:eclipsed?101:0,next_transition_s:eclipsed?105:101});
  const data={orbital_s:100,presentation:{mode:'live'},nodes:[node(0,false)],motion_frames:[
    {orbital_s:101,nodes:[node(.02,true)]},{orbital_s:102,nodes:[node(.04,true)]}]};
  orbitAnimationEpoch=500;animateOrbit(data,orbitLayout(data.nodes));
 `,h.context);
 assert.equal(h.countdown.textContent,'0m 01s');
 const initial=h.group.attrs.transform;
 h.advance(1000);assert.notEqual(h.group.attrs.transform,initial);
 h.advance(1500);assert.equal(h.countdown.textContent,'0m 04s');assert.equal(h.row.classList.contains('shadow'),true);
 assert.match(h.label.textContent,/luce/);
 h.advance(9000);const bounded=h.group.attrs.transform;
 assert.match(h.elements.get('orbital-time').textContent,/102.0.*attesa/);
 h.advance(10000);assert.equal(h.group.attrs.transform,bounded);
 assert.equal(h.countdown.textContent,'0m 03s');
});

test('countdown rounds up remaining fractions and never becomes negative',()=>{
 const h=harness();
 assert.equal(vm.runInContext('phaseCountdown(.1)',h.context),'0m 01s');
 assert.equal(vm.runInContext('phaseCountdown(-1)',h.context),'0m 00s');
 assert.equal(vm.runInContext('phaseCountdown(null)',h.context),'—');
});

test('candidate labels show recorded scores and preserve missing values',()=>{
 const h=harness();
 assert.equal(vm.runInContext('candidateLabel({candidate_score:81.25})',h.context),'Score 81.3');
 assert.equal(vm.runInContext('candidateLabel({candidate_score:0})',h.context),'Score 0.0');
 assert.equal(vm.runInContext('candidateLabel({candidate_score:null})',h.context),'Score —');
});

test('overlapping topology polls share the in-flight request',async()=>{
 const h=harness();let calls=0,resolve;
 h.context.api=()=>{calls++;return new Promise(done=>{resolve=done;});};
 h.context.renderLiveProgress=()=>{};
 vm.runInContext('drawOrbit=()=>{}',h.context);
 const first=vm.runInContext('topology()',h.context);
 await vm.runInContext('topology()',h.context);assert.equal(calls,1);
 resolve({});await first;
});

test('an edited initial configuration replaces a stale in-flight preview',async()=>{
 const h=harness(),requests=[],drawn=[];
 h.context.api=url=>new Promise(resolve=>requests.push({url,resolve}));
 h.context.renderLiveProgress=()=>{};h.context.drawOrbit=data=>drawn.push(data);
 const first=vm.runInContext('topology()',h.context);
 vm.runInContext('++topologyRequest;initialConfigurationRequest={initial_satellite_id:51726,start_orbital_s:2979}',h.context);
 await vm.runInContext('topology(true)',h.context);
 requests[0].resolve({old:true});await first;
 assert.equal(requests.length,2);assert.match(requests[1].url,/start_orbital_s=2979/);
 requests[1].resolve({current:true});await new Promise(resolve=>setImmediate(resolve));
 assert.equal(drawn.length,1);assert.equal(drawn[0].current,true);
});

test('dedicated polling runs only for a running session outside replay',()=>{
 const h=harness();let calls=0;h.context.topology=()=>{calls++;};
 const poll=h.intervals[h.intervals.length-1];
 poll();assert.equal(calls,0);
 h.context.simulations=[{simulation_id:'sim-one',phase:'migrating'}];h.context.selectedSimulation='sim-one';
 poll();assert.equal(calls,1);
 h.context.simulationTick=12;poll();assert.equal(calls,1);
 h.context.simulationTick=null;h.context.simulations[0].phase='finished';poll();assert.equal(calls,1);
});
