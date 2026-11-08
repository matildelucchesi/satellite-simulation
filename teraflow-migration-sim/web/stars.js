/* Starfield: dots of different size, brightness and tint, drawn behind the whole console and
   inside the orbit view. The field is seeded, so it stays the same across reloads; a few stars
   twinkle slowly unless the viewer prefers reduced motion. Purely decorative. */
function seededRandom(seed){
 let s=seed>>>0;
 return ()=>{s=s+0x6d2b79f5|0;let t=Math.imul(s^s>>>15,1|s);t=t+Math.imul(t^t>>>7,61|t)^t;return((t^t>>>14)>>>0)/4294967296;};
}

const STAR_TINTS=['255,255,255','202,220,255','255,236,210','214,232,255'];

/* Most stars are faint and small; brightness follows a steep power law, so only a few shine. */
function starField(width,height,{density=1/2600,seed=7}={}){
 const random=seededRandom(seed),count=Math.round(width*height*density),stars=[];
 for(let i=0;i<count;i++){
  const magnitude=Math.pow(random(),3.2);
  stars.push({x:random()*width,y:random()*height,r:0.35+magnitude*1.5,alpha:0.18+magnitude*0.8,
   tint:STAR_TINTS[Math.floor(random()*STAR_TINTS.length)],twinkle:magnitude>0.25&&random()<0.5,phase:random()*Math.PI*2});
 }
 return stars;
}

function drawStars(context,stars,time=0){
 for(const star of stars){
  const alpha=star.twinkle?star.alpha*(0.72+0.28*Math.sin(time/1400+star.phase)):star.alpha;
  if(star.r>1.25){
   const glow=context.createRadialGradient(star.x,star.y,0,star.x,star.y,star.r*4);
   glow.addColorStop(0,`rgba(${star.tint},${alpha*0.35})`);glow.addColorStop(1,`rgba(${star.tint},0)`);
   context.fillStyle=glow;context.beginPath();context.arc(star.x,star.y,star.r*4,0,Math.PI*2);context.fill();
  }
  context.fillStyle=`rgba(${star.tint},${alpha})`;context.beginPath();context.arc(star.x,star.y,star.r,0,Math.PI*2);context.fill();
 }
}

function startStarfield(canvas){
 const context=canvas.getContext('2d');if(!context)return;
 const still=window.matchMedia('(prefers-reduced-motion: reduce)');
 let stars=[],twinkling=[],frame=0,last=0;
 const paint=time=>{context.setTransform(1,0,0,1,0,0);context.clearRect(0,0,canvas.width,canvas.height);const ratio=canvas.width/window.innerWidth;context.setTransform(ratio,0,0,ratio,0,0);drawStars(context,stars,time);};
 const resize=()=>{
  const ratio=Math.min(window.devicePixelRatio||1,2);
  canvas.width=Math.round(window.innerWidth*ratio);canvas.height=Math.round(window.innerHeight*ratio);
  stars=starField(window.innerWidth,window.innerHeight);twinkling=stars.filter(star=>star.twinkle);paint(performance.now());
 };
 const loop=time=>{frame=requestAnimationFrame(loop);if(time-last<120||document.hidden)return;last=time;paint(time);};
 const motion=()=>{cancelAnimationFrame(frame);if(!still.matches&&twinkling.length)frame=requestAnimationFrame(loop);else paint(0);};
 let timer=0;window.addEventListener('resize',()=>{clearTimeout(timer);timer=setTimeout(resize,150);});
 still.addEventListener?.('change',motion);
 resize();motion();
}

if(typeof document!=='undefined')document.addEventListener('DOMContentLoaded',()=>{const canvas=document.getElementById('stars');if(canvas)startStarfield(canvas);});
if(typeof module!=='undefined')module.exports={seededRandom,starField};
