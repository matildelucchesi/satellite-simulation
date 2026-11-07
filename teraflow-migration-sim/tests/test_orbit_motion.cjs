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
