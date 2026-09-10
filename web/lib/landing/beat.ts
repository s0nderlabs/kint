// @ts-nocheck
/* kint SCROLL BEAT, Sep 10 2026, rebuilt 18:xx. Ported verbatim from design/mocks/index.html; the studio panel,
   its option buttons and the kintProbe / kintSearch probes are gone, the tuned defaults they used to set are baked in.
   The chosen hero (layout under, no sky, day/night by theme) with the BOTTOM leaf lifted out of the image onto its
   own layer. As the reader scrolls, that leaf lifts off, grows and lands centred in the section below as the cobalt
   logo leaf. Three stages on one scrubbed progress:
     0.00 to 0.30  the raster leaf flies and grows (still the picture, up to about 2.6x)
     0.30 to 0.40  handoff: the raster crossfades into a potrace trace of the SAME silhouette, so the swap is unseen
     0.40 to 0.85  the vector grows on, crisp; its fill drifts from the leaf's own sand to cobalt (0.55 to 0.80)
     0.85 to 1.00  the outline morphs into the logo leaf while the leaf settles into the slot; the rib fades in last
   Transform, opacity, fill and path only. Reduced motion shows it already landed. */
import Lenis from 'lenis';
import gsap from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import { CUT } from './cut';

gsap.registerPlugin(ScrollTrigger);

export function initLanding() {
  var NS='http://www.w3.org/2000/svg', N=600;
  var root=document.documentElement, hero=document.getElementById('hero'), flyer=document.getElementById('flyer'), slot=document.getElementById('slot');
  var ras=flyer.querySelectorAll('.ras'), fgr=flyer.querySelector('.fgrain');
  var msvg=document.getElementById('morph'), mpath=document.getElementById('mpath'), rib=document.getElementById('rib'), lg=document.getElementById('lg'), s0=document.getElementById('s0'), s1=document.getElementById('s1'), samp=document.getElementById('samp');
  var LOGO=document.getElementById('leafm').querySelector('path').getAttribute('d'), LP=LOGO.split(/Z(?=M)/), LOGO_OUT=LP[0]+'Z', LOGO_RIB=LP[1]||'';
  var OVER=false;
  var dead=false;
  /* measured Sep 10 2026 (kintSearch, 1920 x 1050): this arc never touches h1, lede, cta or install, and keeps the last 15 percent mostly vertical */
  var ARC={c1x:0.48,c2x:0.20,c1y:-0.12,c2y:-0.30,n1:22,n2:22,nhold:0.50};
  var TEXT='haze'; document.body.setAttribute('data-text',TEXT);
  /* smooth scrolling: Lenis interpolates the wheel so the beat scrubs without steps; off under reduced motion; touch stays native */
  var lenis=null, reduce=false, tick=null; try{reduce=matchMedia('(prefers-reduced-motion: reduce)').matches;}catch(e){}
  try{ if(!reduce&&Lenis){ lenis=new Lenis({lerp:0.09,smoothWheel:true});
    if(gsap){ tick=function(t){lenis.raf(t*1000);}; gsap.ticker.add(tick); gsap.ticker.lagSmoothing(0); } else { (function raf(t){lenis.raf(t);requestAnimationFrame(raf);})(0); } } }catch(e){lenis=null;}
  var STACK=true;
  function jump(y){ if(lenis)lenis.scrollTo(y,{immediate:true,force:true}); else window.scrollTo(0,y); }
  /* theme */
  function cur(){var a=root.getAttribute('data-theme');if(a==='dark'||a==='light')return a;try{if(matchMedia('(prefers-color-scheme: dark)').matches)return 'dark';}catch(e){}return 'light';}
  function setTheme(t){ if(t==='system')root.removeAttribute('data-theme'); else root.setAttribute('data-theme',t); try{localStorage.setItem('kint-theme',t);}catch(e){} layout(); render(); }
  function onToggle(){ setTheme(cur()==='dark'?'light':'dark'); }
  var themeToggle=document.getElementById('themeToggle');
  if(themeToggle)themeToggle.addEventListener('click',onToggle);
  /* the sandpaper tile */
  function prng(seed){return function(){seed=seed+0x6D2B79F5|0;var t=Math.imul(seed^seed>>>15,1|seed);t=t+Math.imul(t^t>>>7,61|t)^t;return ((t^t>>>14)>>>0)/4294967296;};}
  try{var S=128,cv=document.createElement('canvas');cv.width=S;cv.height=S;var ctx=cv.getContext('2d'),id=ctx.createImageData(S,S),d=id.data,r=prng(0x7df5378a);for(var i=0;i<d.length;i+=4){var v=96+Math.floor(r()*96);d[i]=d[i+1]=d[i+2]=v;d[i+3]=255;}ctx.putImageData(id,0,0);root.style.setProperty('--grain-tile','url('+cv.toDataURL('image/png')+')');}catch(e){}

  /* ---- colour: OKLab mix so sand to cobalt does not pass through mud ---- */
  function hex2rgb(h){h=h.replace('#','');if(h.length===3)h=h.split('').map(function(c){return c+c;}).join('');var n=parseInt(h,16);return [(n>>16)&255,(n>>8)&255,n&255];}
  function s2l(c){c/=255;return c<=0.04045?c/12.92:Math.pow((c+0.055)/1.055,2.4);}
  function l2s(c){c=c<=0.0031308?12.92*c:1.055*Math.pow(c,1/2.4)-0.055;return Math.max(0,Math.min(255,Math.round(c*255)));}
  function lab(rgb){var r=s2l(rgb[0]),g=s2l(rgb[1]),b=s2l(rgb[2]);var l=Math.cbrt(0.4122214708*r+0.5363325363*g+0.0514459929*b),m=Math.cbrt(0.2119034982*r+0.6806995451*g+0.1073969566*b),s=Math.cbrt(0.0883024619*r+0.2817188376*g+0.6299787005*b);return [0.2104542553*l+0.7936177850*m-0.0040720468*s,1.9779984951*l-2.4285922050*m+0.4505937099*s,0.0259040371*l+0.7827717662*m-0.8086757660*s];}
  function rgb(L){var l_=L[0]+0.3963377774*L[1]+0.2158037573*L[2],m_=L[0]-0.1055613458*L[1]-0.0638541728*L[2],s_=L[0]-0.0894841775*L[1]-1.2914855480*L[2];var l=l_*l_*l_,m=m_*m_*m_,s=s_*s_*s_;return [l2s(4.0767416621*l-3.3077115913*m+0.2309699292*s),l2s(-1.2684380046*l+2.6097574011*m-0.3413193965*s),l2s(-0.0041960863*l-0.7034186147*m+1.7076147010*s)];}
  function mix(h1,h2,t){var a=lab(hex2rgb(h1)),b=lab(hex2rgb(h2));var c=rgb([a[0]+(b[0]-a[0])*t,a[1]+(b[1]-a[1])*t,a[2]+(b[2]-a[2])*t]);return 'rgb('+c[0]+','+c[1]+','+c[2]+')';}

  /* ---- the morph: both outlines sampled to N points by arc length, the logo ring pre-placed in the cutout's frame,
     start point and direction chosen by least squared distance (what a morph plugin's shapeIndex does) ---- */
  function ring(d){ var p=document.createElementNS(NS,'path'); p.setAttribute('d',d); samp.appendChild(p); var L=p.getTotalLength(), out=[]; for(var i=0;i<N;i++){var q=p.getPointAtLength(L*i/N); out.push([q.x,q.y]);} samp.removeChild(p); return out; }
  function firstRing(d){ var i=d.indexOf('M',1); return i>0?d.slice(0,i):d; }
  function align(A,B){
    var best=Infinity,bk=0,brev=false;
    [false,true].forEach(function(rev){ var Bb=rev?B.slice().reverse():B;
      for(var k=0;k<N;k++){ var s=0; for(var i=0;i<N;i+=4){ var b=Bb[(i+k)%N], dx=A[i][0]-b[0], dy=A[i][1]-b[1]; s+=dx*dx+dy*dy; if(s>best)break; } if(s<best){best=s;bk=k;brev=rev;} } });
    var Bb=brev?B.slice().reverse():B, out=[]; for(var i=0;i<N;i++)out.push(Bb[(i+bk)%N]); return out;
  }
  function tween(A,B,t){ var u=1-t, s='M'; for(var i=0;i<N;i++){ s+=(u*A[i][0]+t*B[i][0]).toFixed(2)+' '+(u*A[i][1]+t*B[i][1]).toFixed(2)+(i<N-1?'L':''); } return s+'Z'; }

  /* geometry: where the leaf sits inside the hero (object-fit cover math), and where the slot is */
  var A={x:0,y:0,w:0,h:0}, B={x:0,y:0,w:0,h:0}, startY=0, endY=1, G=null;
  function prepare(){
    var key=cur()==='dark'?'night':'day', R=CUT[key], V=CUT.vec, bb=R.bbox, bw=bb[2]-bb[0], bh=bb[3]-bb[1];
    if(G&&G.key===key){ G.accent=getComputedStyle(root).getPropertyValue('--kint-accent').trim(); return; }
    msvg.setAttribute('viewBox','0 0 '+bw+' '+bh);
    var ROT=V.angle-R.angle, cxc=R.cx*bw, cyc=R.cy*bh, s=(R.ext*bw)/(V.ext*100);
    rib.setAttribute('d',LOGO_RIB); rib.setAttribute('transform','translate('+cxc+' '+cyc+') rotate('+(-ROT)+') scale('+s+') translate('+(-V.cx*100)+' '+(-V.cy*100)+')');
    var Ar=ring(firstRing(R.path)), Bl=ring(LOGO_OUT), c=Math.cos(-ROT*Math.PI/180), sn=Math.sin(-ROT*Math.PI/180);
    var Br=Bl.map(function(q){ var x=(q[0]-V.cx*100)*s, y=(q[1]-V.cy*100)*s; return [cxc+x*c-y*sn, cyc+x*sn+y*c]; });
    Br=align(Ar,Br);
    var ang=R.angle*Math.PI/180, ex=R.ext*bw/2;
    lg.setAttribute('x1',(cxc-Math.cos(ang)*ex).toFixed(2)); lg.setAttribute('y1',(cyc-Math.sin(ang)*ex).toFixed(2)); lg.setAttribute('x2',(cxc+Math.cos(ang)*ex).toFixed(2)); lg.setAttribute('y2',(cyc+Math.sin(ang)*ex).toFixed(2));
    /* the grain is masked by the traced outline, not the feathered raster: a 3 px feather is a 15 px halo at 5x */
    flyer.style.setProperty('--leaf-mask','url("data:image/svg+xml;utf8,'+encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 '+bw+' '+bh+'"><path d="'+firstRing(R.path)+'" fill="#000"/></svg>')+'")');
    G={key:key,R:R,V:V,bw:bw,bh:bh,Ar:Ar,Br:Br,ROT:ROT,path:firstRing(R.path),accent:getComputedStyle(root).getPropertyValue('--kint-accent').trim()};
  }
  function layout(){
    if(dead)return;
    prepare();
    var key=G.key, bb=G.R.bbox, IW=G.R.image[0], IH=G.R.image[1];
    var img=hero.querySelector('.scene.'+key), r=img.getBoundingClientRect(), sx=window.scrollX||0, sy=window.scrollY||0;
    var cw=r.width, ch=r.height, k=Math.max(cw/IW, ch/IH), dw=IW*k, dh=IH*k, ox=(cw-dw)/2, oy=(ch-dh)/2;
    A={x:r.left+sx+ox+bb[0]*k, y:r.top+sy+oy+bb[1]*k, w:(bb[2]-bb[0])*k, h:(bb[3]-bb[1])*k};
    var s=slot.getBoundingClientRect();
    B={x:s.left+sx, y:s.top+sy, w:s.width, h:s.height};
    var hr=hero.getBoundingClientRect(); var heroH=hr.height;
    startY=Math.max(0, (window.innerWidth<=760?0.02:0.08)*heroH);
    endY=Math.max(startY+260, B.y+B.h/2-0.50*window.innerHeight);
    /* the flight must be reachable: never past what the page can scroll */
    var maxScroll=Math.max(0, document.documentElement.scrollHeight-window.innerHeight-24);
    if(endY>maxScroll){ endY=maxScroll; if(startY>endY-200) startY=Math.max(0,endY-200); }
  }
  var P=null; /* null = follow the scroll; a number = scrubbed */
  function progress(){ if(reduce)return 1; if(P!==null)return P; var y=window.scrollY||0; var p=Math.min(1,Math.max(0,(y-startY)/(endY-startY))); return p>=0.995?1:p; }  /* a phone cannot always scroll to the exact end */
  function ease(t){return 1-Math.pow(1-t,3);}
  function clamp(t){return Math.min(1,Math.max(0,t));}
  function smooth(t){return t*t*(3-2*t);}
  var lastD='';
  function render(){
    if(dead)return;
    if(!G)return;
    var R=G.R, V=G.V, p=progress(), e=ease(p);
    /* the landing: the vector leaf at the stage's own size, so the flying copy and the slot's copy coincide at p = 1 */
    var Sv=B.w, tx=B.x+V.cx*Sv, ty=B.y+V.cy*Sv;
    var cx=A.x+R.cx*A.w, cy=A.y+R.cy*A.h;                      /* the raster leaf's centroid in the scene */
    var vw0=window.innerWidth, vh0=window.innerHeight, narrow=vw0<=760;
    /* the arc swings out to the right of the headline and lede and comes back in to land; ARC holds the control points as fractions */
    var c1x=narrow?vw0-ARC.n1:Math.min(vw0-140, cx+ARC.c1x*vw0), c1y=narrow?cy+0.10*vh0:cy+ARC.c1y*vh0;
    var c2x=narrow?vw0-ARC.n2:tx+ARC.c2x*vw0, c2y=narrow?ty-0.30*vh0:ty+ARC.c2y*vh0;
    var u=1-p, x=u*u*u*cx+3*u*u*p*c1x+3*u*p*p*c2x+p*p*p*tx, y=u*u*u*cy+3*u*u*p*c1y+3*u*p*p*c2y+p*p*p*ty;
    /* size: smoothstep growth until the long axes match at the stage; the overshoot variant peaks at 1.10 around p = 0.8 */
    var g=smooth(narrow?clamp((p-ARC.nhold)/(1-ARC.nhold)):p); if(OVER){ g+=0.10*Math.sin(clamp((p-0.6)/0.4)*Math.PI); }
    var wLand=V.ext*Sv/R.ext, w=A.w+(wLand-A.w)*g, h=w*(A.h/A.w);
    /* rotation: the raster's tip turns from its own heading to the logo's, about its centroid */
    var ROT=G.ROT, rot=ROT*e, sway=Math.sin(p*Math.PI*2)*5*(1-p);
    flyer.style.width=w+'px'; flyer.style.height=h+'px';
    flyer.style.transformOrigin=(R.cx*100)+'% '+(R.cy*100)+'%';
    flyer.style.transform='translate3d('+(x-R.cx*w)+'px,'+(y-R.cy*h)+'px,0) rotate('+(rot+sway)+'deg)';
    /* the stages */
    var hand=clamp((p-0.30)/0.10), col=clamp((p-0.55)/0.25), gr=1-clamp((p-0.70)/0.15), mo=clamp((p-0.85)/0.15), rb=clamp((p-0.93)/0.07);
    for(var i=0;i<ras.length;i++)ras[i].style.opacity=String(1-hand);
    mpath.setAttribute('opacity',String(hand));
    fgr.style.opacity=String(0.55*gr);
    s0.setAttribute('stop-color',mix(R.base,G.accent,smooth(col))); s1.setAttribute('stop-color',mix(R.tip,G.accent,smooth(col)));
    var d=mo>0?tween(G.Ar,G.Br,smooth(mo)):G.path; if(d!==lastD){mpath.setAttribute('d',d);lastD=d;}
    rib.setAttribute('opacity',String(rb));
    document.body.classList.toggle('landed', p>=1);
    flyer.style.visibility=(p>=1)?'hidden':'visible';
    var stage=p<0.30?'raster':p<0.40?'handoff':p<0.55?'vector':p<0.80?'colour':p<0.85?'held':p<1?'morph':'landed';
    var rd=document.getElementById('read'); if(rd)rd.textContent='p '+p.toFixed(3)+' · '+stage+' · '+Math.round(w)+' px ('+(w/A.w).toFixed(1)+'x) · scroll '+Math.round(window.scrollY)+' · flight '+Math.round(startY)+' to '+Math.round(endY)+' · turn '+Math.round(ROT)+' deg';
  }
  var ticking=false; function onScroll(){ if(ticking)return; ticking=true; requestAnimationFrame(function(){ticking=false; render();}); }
  function onResize(){ layout(); render(); }
  function onImgLoad(){ layout(); render(); }
  addEventListener('scroll', onScroll, {passive:true}); addEventListener('resize', onResize);
  hero.querySelectorAll('.scene').forEach(function(im){ im.addEventListener('load', onImgLoad); });
  document.fonts.ready.then(function(){ if(dead)return; layout(); render(); if(ScrollTrigger&&stacked)ScrollTrigger.refresh();});
  layout(); render();
  /* the stack: full-height cards, scrubbed enter, drift while pinned, settle-back exit. Desktop and motion only,
     and it follows the breakpoint live so a resize across 760 px never leaves sticky cards on a phone layout. */
  var stacked=false, stackTweens=[];
  function buildStack(){
    if(stacked||!(STACK&&!reduce&&window.innerWidth>760&&gsap&&ScrollTrigger))return;
    stacked=true; document.body.classList.add('stacked'); gsap.registerPlugin(ScrollTrigger);
    if(lenis&&!buildStack.hooked){ lenis.on('scroll',ScrollTrigger.update); buildStack.hooked=true; }
    var secs=[].slice.call(document.querySelectorAll('.deck .section'));
    function top(el){ var y=0; while(el){ y+=el.offsetTop; el=el.offsetParent; } return y; }  /* layout position: sticky never moves it */
    secs.forEach(function(sec,i){
      var wrap=sec.querySelector('.wrap'), cells=sec.querySelectorAll('.bx'), nxt=secs[i+1];
      var vh=function(){return window.innerHeight;};
      stackTweens.push(gsap.fromTo(wrap,{y:72,opacity:0},{y:0,opacity:1,ease:'none',scrollTrigger:{start:function(){return top(sec)-vh()*0.94;},end:function(){return top(sec)-vh()*0.24;},scrub:true}}));
      stackTweens.push(gsap.fromTo(cells,{y:function(k){return 48+(k%3)*32;}},{y:0,ease:'none',scrollTrigger:{start:function(){return top(sec)-vh()*0.96;},end:function(){return top(sec)-vh()*0.18;},scrub:true}}));
      stackTweens.push(gsap.fromTo(cells,{yPercent:0},{yPercent:function(k){return -(3+(k%3)*2.2);},ease:'none',scrollTrigger:{start:function(){return top(sec);},end:function(){return top(sec)+sec.offsetHeight;},scrub:true}}));
      if(nxt) stackTweens.push(gsap.fromTo(sec,{scale:1,'--dim':0},{scale:.955,'--dim':.6,ease:'none',scrollTrigger:{start:function(){return top(nxt)-vh();},end:function(){return top(nxt);},scrub:true}}));
    });
    ScrollTrigger.refresh();
  }
  function killStack(){
    if(!stacked)return; stacked=false; document.body.classList.remove('stacked');
    stackTweens.forEach(function(t){ if(t.scrollTrigger)t.scrollTrigger.kill(); t.kill(); }); stackTweens=[];
    gsap.set(document.querySelectorAll('.deck .section, .deck .wrap, .deck .bx'),{clearProps:'all'});
    layout(); render();
  }
  buildStack();
  function onLoad(){ if(stacked)ScrollTrigger.refresh(); }
  function onResizeStack(){ var want=STACK&&!reduce&&window.innerWidth>760; if(want&&!stacked)buildStack(); if(!want&&stacked)killStack(); if(stacked)ScrollTrigger.refresh(); }
  addEventListener('load',onLoad);
  addEventListener('resize',onResizeStack);
  /* anchor links glide through Lenis (the deck's layout tops are what sticky pins to, so a section lands at the top) */
  function onAnchorClick(e){ var a=e.target.closest&&e.target.closest('a[href^="#"]'); if(!a)return; var id=a.getAttribute('href').slice(1); if(!id)return; var el=document.getElementById(id); if(!el)return; e.preventDefault();
    var y=0, n=el; while(n){y+=n.offsetTop; n=n.offsetParent;} if(id==='hero')y=0;
    if(lenis)lenis.scrollTo(y,{duration:1.25,easing:function(t){return 1-Math.pow(1-t,3);}}); else window.scrollTo({top:y,behavior:'smooth'});
    try{history.replaceState(null,'','#'+id);}catch(x){} }
  document.addEventListener('click',onAnchorClick);
  var ft=document.querySelector('.ftoggle'); if(ft)ft.addEventListener('click',onToggle);
  /* reveal once, on entry */
  var io=null;
  try{ io=new IntersectionObserver(function(es){es.forEach(function(e){if(e.isIntersecting){e.target.classList.add('in');io.unobserve(e.target);}});},{threshold:0.12,rootMargin:'0px 0px -6% 0px'}); document.querySelectorAll('.rv').forEach(function(el){io.observe(el);}); }catch(e){document.querySelectorAll('.rv').forEach(function(el){el.classList.add('in');});}
  /* the terminal: real commands from the README, response lines in the CLI's own wording, placeholders where a value is the user's */
  var SESSION=[
    {cmd:'uv tool install git+https://github.com/s0nderlabs/kint@v0.3.0', out:['Resolved 64 packages in 3.85s','Installed 64 packages in 77ms',' + kint==0.3.0 (from git+https://github.com/s0nderlabs/kint@v0.3.0)','Installed 2 executables: kint, kint-server']},
    {cmd:'kint join --owner 0xd3390EDAC3d0EB41248C132792B0DcC5f0b0D4E3 --base-account --tenant kint-demo', out:['vault passphrase: ','join: owner 0xd3390EDAC3d0EB41248C132792B0DcC5f0b0D4E3','      tenant kint-demo (from --tenant), space bd2a3b5b8f3fb4c8','      contract 0xa22E03f7a4145Bf4909a83595C90a38E14d79600, store ~/.sibyl-memory/memory.db','      this command writes nothing to the chain','session key: 0xB6A4F6Bd61cd9BedfB91c73976679DFb252D4116 (created; it signs epochs for this machine and can never decrypt)','vault: head epoch 1 at block 51082012','connected: key tag 14e3812b, data key from chain head header','pull: cold start, both RPCs agree: head seq 1, digest b64dcde033b03249, block 51082012','pull: applied epoch 1 (5 rows, 0 deletions) from block 51082012','restore: restored 1 epoch(s), 5 rows; head seq 1 at block 51082012; store root matches the anchored root','claude: registered kint (user scope)','codex: wrote [mcp_servers.kint] to ~/.codex/config.toml','hermes: registered kint','openclaw: saved MCP server kint (openclaw mcp set)','writes: off until the session key is funded and authorized by the owner; reads work now','next: put a few cents of ETH on 0xB6A4F6Bd61cd9BedfB91c73976679DFb252D4116 (Base), then kint authorize page']},
    {cmd:'kint authorize page', out:['open this page in the browser where your Base Account is logged in (owner 0xd3390EDAC3d0EB41248C132792B0DcC5f0b0D4E3):','  http://127.0.0.1:51749/…','page reported 0x81c362b1…; polling the chain for canWrite(0xd3390EDAC3d0EB41248C132792B0DcC5f0b0D4E3, 0xB6A4F6Bd61cd9BedfB91c73976679DFb252D4116)','authorized: 0xB6A4F6Bd61cd9BedfB91c73976679DFb252D4116 may push under 0xd3390EDAC3d0EB41248C132792B0DcC5f0b0D4E3 until 2026-10-09']}
  ];
  var tty=document.getElementById('tty'), term=document.getElementById('term'), replay=document.getElementById('replay'), run=0;
  function esc(t){return t.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
  function cmdLine(i,t,cur){ return '<span class="ln cmd" data-i="'+i+'"><span class="c">❯</span> '+esc(t)+(cur?'<span class="cur"></span>':'')+'</span>'; }
  function outLine(t){ return '<span class="ln out">'+esc(t)+'</span>'; }
  function renderAll(){ tty.innerHTML=SESSION.map(function(st,i){ return cmdLine(i,st.cmd)+st.out.map(outLine).join(''); }).join(''); }
  /* the card's height is the finished session's, measured before the first keystroke, so typing never grows it */
  function fit(){ if(!tty)return; var keep=tty.innerHTML, was=tty.style.minHeight; tty.style.minHeight=''; renderAll(); tty.innerHTML+='<span class="ln"><span class="cur"></span></span>'; var h=tty.offsetHeight; tty.innerHTML=keep; tty.style.minHeight=(h>0?h:parseFloat(was)||0)+'px'; }
  function play(from){
    var id=++run, html='', k=from||0;
    if(reduce){renderAll();return;}
    for(var i=0;i<k;i++){ html+=cmdLine(i,SESSION[i].cmd)+SESSION[i].out.map(outLine).join(''); }
    function step(){
      if(id!==run)return;
      if(k>=SESSION.length){ tty.innerHTML=html; return; }
      var st=SESSION[k], n=0;
      function tick(){
        if(id!==run)return;
        if(n<=st.cmd.length){ tty.innerHTML=html+cmdLine(k,st.cmd.slice(0,n),true); n++; setTimeout(tick, 14+Math.random()*26); return; }
        setTimeout(function(){ if(id!==run)return; var m=0; html+=cmdLine(k,st.cmd);
          (function outs(){ if(id!==run)return; if(m<st.out.length){ html+=outLine(st.out[m]); m++; tty.innerHTML=html+'<span class="ln"><span class="cur"></span></span>'; setTimeout(outs,110); return; } k++; tty.innerHTML=html+'<span class="ln"><span class="cur"></span></span>'; setTimeout(step, 420); })();
        }, 260);
      }
      tick();
    }
    step();
  }
  var tio=null;
  function onReplay(){ play(0); }
  function onTtyClick(e){ var c=e.target.closest&&e.target.closest('.cmd'); if(c)play(parseInt(c.getAttribute('data-i'),10)); }
  function onTermResize(){ fit(); }
  if(tty){ fit(); addEventListener('resize',onTermResize); replay.addEventListener('click',onReplay); tty.addEventListener('click',onTtyClick);
    try{ tio=new IntersectionObserver(function(es){ es.forEach(function(e){ if(e.isIntersecting){ tio.disconnect(); setTimeout(function(){ if(dead)return; play(0);},250); } }); },{threshold:0.35}); tio.observe(term); }catch(e){renderAll();} }
  window.kintTerm={play:play,all:renderAll};
  window.kintBeat=function(o){ if(o&&typeof o.p==='number'){P=o.p; render();} if(o&&o.p===null){P=null; render();} if(o&&o.scrollTo!==undefined){P=null; jump(o.scrollTo); layout(); render();} if(o&&o.theme){setTheme(o.theme);} if(o&&o.arc){for(var k in o.arc)ARC[k]=o.arc[k]; render();} return {arc:ARC,text:TEXT,lenis:!!lenis,stacked:stacked,p:progress(),A:A,B:B,startY:startY,endY:endY,over:OVER,key:G&&G.key}; };

  /* React owns the mount: leave nothing behind on unmount or a strict-mode second pass */
  return function cleanup(){
    run++;
    removeEventListener('scroll', onScroll);
    removeEventListener('resize', onResize);
    removeEventListener('resize', onResizeStack);
    removeEventListener('resize', onTermResize);
    removeEventListener('load', onLoad);
    document.removeEventListener('click', onAnchorClick);
    if(themeToggle)themeToggle.removeEventListener('click',onToggle);
    if(ft)ft.removeEventListener('click',onToggle);
    if(tty){ tty.removeEventListener('click',onTtyClick); if(replay)replay.removeEventListener('click',onReplay); }
    hero.querySelectorAll('.scene').forEach(function(im){ im.removeEventListener('load', onImgLoad); });
    if(io)io.disconnect();
    if(tio)tio.disconnect();
    killStack();
    dead=true;
    try{ ScrollTrigger.getAll().forEach(function(t){t.kill();}); }catch(e){}
    try{ gsap.killTweensOf(document.querySelectorAll('.deck .section, .deck .wrap, .deck .bx')); }catch(e){}
    if(tick){ try{ gsap.ticker.remove(tick); gsap.ticker.lagSmoothing(500,33); }catch(e){} }
    if(lenis){ try{ lenis.destroy(); }catch(e){} lenis=null; }
    document.body.classList.remove('landed');
    document.body.classList.remove('stacked');
    document.body.removeAttribute('data-text');
    root.style.removeProperty('--grain-tile');
    try{ delete window.kintBeat; delete window.kintTerm; }catch(e){}
  };
}

export default initLanding;
