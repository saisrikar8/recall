import { useEffect } from 'react';
export function useProductAnimation(sceneRef){useEffect(()=>{
const disposers=[];
function on(target,event,handler,options){target.addEventListener(event,handler,options);disposers.push(()=>target.removeEventListener(event,handler,options));}
const reducedMotion=window.matchMedia('(prefers-reduced-motion: reduce)');
const scene=sceneRef.current;
const mac=scene.querySelector('.macbook');


const lid=scene.querySelector('.lid');
const screenQuery=scene.querySelector('#screen-query');

const searchText='notes about eigenvalues';
const clamp=value=>Math.max(0,Math.min(1,value));
let ticking=false;let updateFrame=0;
function renderSearch(p){
 const typed=clamp((p-.06)/.3);
 screenQuery.textContent=searchText.slice(0,Math.floor(typed*searchText.length));
 scene.classList.toggle('has-results',p>=.38);
 scene.classList.toggle('has-selection',p>=.52);
 scene.classList.toggle('has-preview',p>=.62);
 scene.classList.toggle('has-typed',p>=.36);
 const closing=clamp((p-.76)/.16);
 lid.style.transform=`rotateX(${-closing*38}deg)`;
 mac.style.transform=`translateY(${-closing*15}px) rotateY(${-3*(1-p)}deg) scale(.94)`;
 scene.style.setProperty('--scene-progress',String(p));
 // Stable, irregular waypoints keep reverse scrolling smooth and repeatable.
 const cursorPath=[
  [0,72,72],[.35,72,72],[.44,49,53],
  [.50,23,34],[.52,24,35],[1,24,35]
 ];
 let point=cursorPath.length-2;
 for(let i=0;i<cursorPath.length-1;i++){if(p<=cursorPath[i+1][0]){point=i;break;}}
 const from=cursorPath[point],to=cursorPath[point+1];
 const t=clamp((p-from[0])/(to[0]-from[0]));
 const eased=t*t*(3-2*t);
 scene.style.setProperty('--cursor-x',`${from[1]+(to[1]-from[1])*eased}%`);
 scene.style.setProperty('--cursor-y',`${from[2]+(to[2]-from[2])*eased}%`);

}
function updateScene(){ticking=false;if(reducedMotion.matches){renderSearch(.7);return;}const rect=scene.getBoundingClientRect();const travel=scene.offsetHeight-window.innerHeight;const p=clamp(-rect.top/Math.max(1,travel));renderSearch(p);}
function requestUpdate(){if(!ticking){ticking=true;updateFrame=requestAnimationFrame(updateScene);}}
on(window,'scroll',requestUpdate,{passive:true});on(window,'resize',requestUpdate);on(reducedMotion,'change',()=>{if(reducedMotion.matches){renderSearch(.7);}else requestUpdate();});updateScene();
// Limit movement only across the product sequence; no queued scroll backlog.
let pendingSceneScroll=0;
let scrollFrame=0;
let lastScrollFrame=0;
const sceneBounds=()=>{const top=scene.getBoundingClientRect().top+window.scrollY;return {start:top,end:top+Math.max(0,scene.offsetHeight-window.innerHeight)};};
function overlapsScene(delta){const {start,end}=sceneBounds();const next=window.scrollY+delta;return end>start&&Math.max(window.scrollY,next)>=start&&Math.min(window.scrollY,next)<=end;}
function advanceScene(time){const dt=Math.min((time-lastScrollFrame||16)/1000,.04);lastScrollFrame=time;const {start,end}=sceneBounds();const rate=Math.max(100,Math.min(280,(end-start)/4.5));const amount=Math.sign(pendingSceneScroll)*Math.min(Math.abs(pendingSceneScroll),rate*dt);window.scrollBy({top:amount,behavior:'instant'});pendingSceneScroll-=amount;if(Math.abs(pendingSceneScroll)>.3){scrollFrame=requestAnimationFrame(advanceScene);}else{pendingSceneScroll=0;scrollFrame=0;lastScrollFrame=0;}}
function queueSceneScroll(delta){const {start,end}=sceneBounds();if(window.scrollY<start&&delta>0)window.scrollTo({top:start,behavior:'instant'});else if(window.scrollY>end&&delta<0)window.scrollTo({top:end,behavior:'instant'});const maxQueue=90;if(Math.sign(delta)!==Math.sign(pendingSceneScroll))pendingSceneScroll=0;pendingSceneScroll=Math.max(-maxQueue,Math.min(maxQueue,pendingSceneScroll+delta));if(!scrollFrame)scrollFrame=requestAnimationFrame(advanceScene);}
on(window,'wheel',event=>{if(reducedMotion.matches||event.ctrlKey||event.metaKey||Math.abs(event.deltaX)>Math.abs(event.deltaY))return;const delta=event.deltaY*(event.deltaMode===1?16:event.deltaMode===2?innerHeight:1);if(overlapsScene(delta)){event.preventDefault();queueSceneScroll(delta);}},{passive:false});
let lastTouchY=null;
on(window,'touchstart',event=>{lastTouchY=event.touches.length===1?event.touches[0].clientY:null;pendingSceneScroll=0;},{passive:true});
on(window,'touchmove',event=>{if(reducedMotion.matches||lastTouchY===null||event.touches.length!==1)return;const y=event.touches[0].clientY;const delta=lastTouchY-y;lastTouchY=y;if(overlapsScene(delta)){event.preventDefault();queueSceneScroll(delta);}},{passive:false});
on(window,'touchend',()=>{lastTouchY=null;},{passive:true});
on(window,'keydown',event=>{if(reducedMotion.matches||event.ctrlKey||event.metaKey||event.altKey||event.target.closest('input,textarea,select,button,a,[contenteditable="true"]'))return;let delta=0;if(event.key==='PageDown'||event.key===' ')delta=event.shiftKey?-innerHeight:innerHeight;else if(event.key==='PageUp')delta=-innerHeight;else if(event.key==='ArrowDown')delta=60;else if(event.key==='ArrowUp')delta=-60;if(delta&&overlapsScene(delta)){event.preventDefault();queueSceneScroll(delta);}});

// Native momentum can continue after touchend or contain non-cancelable wheel
// events. Constrain actual movement too, on every entry in either direction.
let acceptedY=window.scrollY;
let acceptedAt=performance.now();
let correctingScroll=false;
on(window,'scroll',()=>{
 const now=performance.now();
 const current=window.scrollY;
 if(correctingScroll){correctingScroll=false;acceptedY=current;acceptedAt=now;return;}
 const {start,end}=sceneBounds();
 const delta=current-acceptedY;
 const crosses=end>start&&Math.max(current,acceptedY)>start&&Math.min(current,acceptedY)<end;
 if(!reducedMotion.matches&&crosses&&Math.abs(delta)>0){
  const rate=Math.max(100,Math.min(280,(end-start)/4.5));
  const allowance=Math.max(8,rate*Math.min(.05,Math.max(.016,(now-acceptedAt)/1000)));
  const origin=delta>0?Math.max(acceptedY,start):Math.min(acceptedY,end);
  const limited=delta>0?Math.min(current,origin+allowance):Math.max(current,origin-allowance);
  if(Math.abs(current-limited)>1){correctingScroll=true;window.scrollTo({top:limited,behavior:'instant'});acceptedY=limited;acceptedAt=now;requestUpdate();return;}
 }
 acceptedY=current;acceptedAt=now;
},{passive:true});
on(window,'pageshow',()=>{acceptedY=window.scrollY;acceptedAt=performance.now();pendingSceneScroll=0;});

return ()=>{disposers.forEach(dispose=>dispose());cancelAnimationFrame(scrollFrame);cancelAnimationFrame(updateFrame);};
},[sceneRef]);}
