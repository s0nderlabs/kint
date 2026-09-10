/* kint docs: the theme square, copy buttons, the headings column that follows the reader, the chapters menu on
   narrow screens, and search over every section. No framework, nothing leaves the page. */
(function(){
  var root=document.documentElement;
  var BASE=document.body.getAttribute('data-base')||'/';

  /* theme: the same key and the same three states as the landing */
  function cur(){var a=root.getAttribute('data-theme');if(a==='dark'||a==='light')return a;try{if(matchMedia('(prefers-color-scheme: dark)').matches)return 'dark';}catch(e){}return 'light';}
  var tg=document.getElementById('themeToggle');
  if(tg)tg.addEventListener('click',function(){var t=cur()==='dark'?'light':'dark';root.setAttribute('data-theme',t);try{localStorage.setItem('kint-theme',t);}catch(e){}});

  /* copy: a command block copies its commands without the prompt or the output */
  Array.prototype.forEach.call(document.querySelectorAll('.copy'),function(b){
    b.addEventListener('click',function(){
      var pre=b.parentNode.querySelector('pre');var txt=pre.getAttribute('data-copy');
      if(txt===null)txt=pre.innerText;
      function ok(){b.classList.add('done');b.setAttribute('aria-label','Copied');setTimeout(function(){b.classList.remove('done');b.setAttribute('aria-label','Copy');},1400);}
      try{navigator.clipboard.writeText(txt).then(ok,function(){fallback(txt);ok();});}catch(e){fallback(txt);ok();}
    });
  });
  function fallback(t){try{var ta=document.createElement('textarea');ta.value=t;ta.style.position='fixed';ta.style.opacity='0';document.body.appendChild(ta);ta.select();document.execCommand('copy');document.body.removeChild(ta);}catch(e){}}

  /* the headings column marks the section being read */
  var links=Array.prototype.slice.call(document.querySelectorAll('.toc nav a'));
  if(links.length&&'IntersectionObserver' in window){
    var byId={};links.forEach(function(a){byId[decodeURIComponent(a.hash.slice(1))]=a;});
    var heads=Array.prototype.slice.call(document.querySelectorAll('.doc h2[id],.doc h3[id]')).filter(function(h){return byId[h.id];});
    function mark(){
      var y=(parseFloat(getComputedStyle(root).getPropertyValue('--top'))||64)+40,act=null;
      for(var i=0;i<heads.length;i++){if(heads[i].getBoundingClientRect().top<=y)act=heads[i];else break;}
      if(!act&&heads.length)act=heads[0];
      if(window.innerHeight+window.scrollY>=document.documentElement.scrollHeight-4&&heads.length)act=heads[heads.length-1];
      links.forEach(function(a){a.classList.toggle('on',act&&byId[act.id]===a);});
    }
    var raf=0;window.addEventListener('scroll',function(){if(!raf)raf=requestAnimationFrame(function(){raf=0;mark();});},{passive:true});
    window.addEventListener('resize',mark);mark();
  }

  /* chapters menu on narrow screens */
  var mn=document.getElementById('mnav');
  if(mn)mn.addEventListener('click',function(){var o=document.body.classList.toggle('menu');mn.setAttribute('aria-expanded',o?'true':'false');});

  /* search: one index of every section, fetched on first open */
  var sd=document.getElementById('sd'),sin=document.getElementById('sin'),sul=document.getElementById('sul'),sb=document.getElementById('sbtn');
  var IDX=null,loading=false,sel=0,hits=[],last=null;
  function load(){if(IDX||loading)return;loading=true;fetch(BASE+'docs/_/search.json').then(function(r){return r.json();}).then(function(j){IDX=j.map(function(e){e.lt=e.t.toLowerCase();e.lh=e.h.toLowerCase();e.lx=e.x.toLowerCase();return e;});run();}).catch(function(){loading=false;sul.innerHTML='<li class="none">Search needs the site to be served over http.</li>';});}
  function open(){if(!sd)return;last=document.activeElement;sd.classList.add('open');sd.setAttribute('aria-hidden','false');load();setTimeout(function(){sin.focus();sin.select();},10);run();}
  function close(){sd.classList.remove('open');sd.setAttribute('aria-hidden','true');if(last&&last.focus)last.focus();}
  function esc(s){return s.replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];});}
  function hl(s,terms){var o=esc(s);terms.forEach(function(t){if(!t)return;o=o.replace(new RegExp('('+t.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')+')','ig'),'<mark>$1</mark>');});return o;}
  function snip(e,terms){var x=e.x,lx=e.lx,i=-1;for(var k=0;k<terms.length&&i<0;k++)i=lx.indexOf(terms[k]);if(i<0)return x.slice(0,120);var s=Math.max(0,i-40);return (s?'\u2026':'')+x.slice(s,s+140);}
  function run(){
    if(!sul)return;var q=(sin.value||'').trim().toLowerCase();
    if(!IDX){sul.innerHTML='';return;}
    if(!q){hits=IDX.filter(function(e){return !e.a;}).slice(0,16);}
    else{var terms=q.split(/\s+/);hits=[];IDX.forEach(function(e){var sc=0;for(var i=0;i<terms.length;i++){var t=terms[i],s=0;if(e.lt.indexOf(t)>=0)s+=6;if(e.lh.indexOf(t)>=0)s+=4;if(e.lx.indexOf(t)>=0)s+=1;if(!s)return;sc+=s;}if(!e.a)sc+=.5;hits.push({e:e,s:sc});});hits.sort(function(a,b){return b.s-a.s;});hits=hits.slice(0,24).map(function(h){return h.e;});}
    var terms2=q?q.split(/\s+/):[];sel=0;
    if(!hits.length){sul.innerHTML='<li class="none">No section mentions that. Try a command, a tool name or a flag.</li>';return;}
    sul.innerHTML=hits.map(function(e,i){var head=e.a?(esc(e.t)+' \u203A '+hl(e.h,terms2)):hl(e.t,terms2);return '<li><a role="option" href="'+BASE+'docs/'+e.s+'/'+(e.a?'#'+e.a:'')+'" aria-selected="'+(i===0)+'"><span class="h">'+head+'</span><span class="w">'+hl(snip(e,terms2),terms2)+'</span></a></li>';}).join('');
  }
  function move(d){var as=sul.querySelectorAll('a');if(!as.length)return;as[sel].setAttribute('aria-selected','false');sel=(sel+d+as.length)%as.length;as[sel].setAttribute('aria-selected','true');as[sel].scrollIntoView({block:'nearest'});}
  if(sb)sb.addEventListener('click',open);
  if(sd){
    sd.addEventListener('click',function(e){if(e.target===sd)close();});
    document.getElementById('sesc').addEventListener('click',close);
    sin.addEventListener('input',run);
    sin.addEventListener('keydown',function(e){if(e.key==='ArrowDown'){e.preventDefault();move(1);}else if(e.key==='ArrowUp'){e.preventDefault();move(-1);}else if(e.key==='Enter'){var a=sul.querySelectorAll('a')[sel];if(a){location.href=a.href;close();}}else if(e.key==='Escape'){close();}});
    sul.addEventListener('click',function(e){if(e.target.closest('a'))close();});
  }
  document.addEventListener('keydown',function(e){
    var t=e.target,typing=t&&(t.tagName==='INPUT'||t.tagName==='TEXTAREA'||t.isContentEditable);
    if((e.key==='k'&&(e.metaKey||e.ctrlKey))||(e.key==='/'&&!typing)){e.preventDefault();open();}
    else if(e.key==='Escape'&&sd&&sd.classList.contains('open'))close();
  });
})();
