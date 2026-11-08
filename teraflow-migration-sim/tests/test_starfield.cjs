const {test}=require('node:test');
const assert=require('node:assert/strict');
const {starField}=require('../web/stars.js');

test('the starfield is seeded, fills the area and varies in brightness',()=>{
 const first=starField(800,600),second=starField(800,600);
 assert.deepEqual(first,second);
 assert.equal(first.length,Math.round(800*600/2600));
 assert.ok(first.every(star=>star.x>=0&&star.x<800&&star.y>=0&&star.y<600&&star.alpha>0&&star.alpha<=1));
 const faint=first.filter(star=>star.alpha<0.35).length,bright=first.filter(star=>star.alpha>0.7).length;
 assert.ok(faint>first.length/2,'most stars are faint');
 assert.ok(bright>0&&bright<first.length/10,'only a few stars are bright');
});

test('a different seed gives a different sky',()=>{
 assert.notDeepEqual(starField(400,400,{seed:1}),starField(400,400,{seed:2}));
});
