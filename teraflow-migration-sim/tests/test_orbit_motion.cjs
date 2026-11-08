const {test}=require('node:test');
const assert=require('node:assert/strict');
const {orbitLayout,pathEdges,ORBIT_SIZE}=require('../web/orbit-view.js');

test('each plane is a ring and satellites sit at their argument of latitude',()=>{
 const layout=orbitLayout([{norad:1,plane:1,argument_of_latitude_deg:0},{norad:2,plane:2,argument_of_latitude_deg:90}]);
 const first=layout.positions.get(1),second=layout.positions.get(2);
 assert.ok(Math.abs(first.x-(layout.cx+layout.inner))<1e-9);
 assert.ok(Math.abs(first.y-layout.cy)<1e-9);
 assert.ok(Math.abs(second.x-layout.cx)<1e-9);
 assert.ok(Math.abs(second.y-(layout.cy-layout.outer))<1e-9);
 assert.ok(layout.outer<ORBIT_SIZE.width/2);
});

test('path edges are undirected and ignore missing paths',()=>{
 assert.deepEqual([...pathEdges([3,1,2])],['1-3','1-2']);
 assert.equal(pathEdges(null).size,0);
});

const {nodeAt,circularMean}=require('../web/orbit-view.js');

test('satellites advance at their angular speed and flip light at the transition',()=>{
 const node={argument_of_latitude_deg:350,argument_of_latitude_rate_deg_s:.064,eclipsed:false,next_transition_s:1600};
 const later=nodeAt(node,1557,1757);
 assert.ok(Math.abs(later.angle-((350+.064*200)%360))<1e-9);
 assert.equal(later.eclipsed,true);
 assert.equal(nodeAt(node,1557,1599).eclipsed,false);
 assert.equal(nodeAt(node,1557,1557).angle,350);
});

test('the shadow direction is the circular mean of eclipsed angles',()=>{
 assert.ok(Math.abs(circularMean([350,10])-0)<1e-9||Math.abs(circularMean([350,10])-360)<1e-9);
 assert.ok(Math.abs(circularMean([80,100])-90)<1e-9);
 assert.equal(circularMean([]),null);
});
