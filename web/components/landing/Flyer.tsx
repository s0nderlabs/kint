"use client";

/* The travelling leaf: one element, positioned in page space by the beat, transform only. The hidden #samp svg is
   where the beat samples both outlines by arc length. */
const FIRST_FRAME = `(function(){try{var h=document.getElementById('hero');if(!h)return;var r=h.getBoundingClientRect();var d=document.documentElement,t=d.getAttribute('data-theme');var dark=t==='dark'||(t!=='light'&&matchMedia('(prefers-color-scheme: dark)').matches);var bb=dark?[859,521,945,588]:[859,520,945,587],IW=1920,IH=1072;var k=Math.max(r.width/IW,r.height/IH),ox=(r.width-IW*k)/2,oy=(r.height-IH*k)/2;var st=d.style;st.setProperty('--fx',(r.left+(window.scrollX||0)+ox+bb[0]*k).toFixed(2)+'px');st.setProperty('--fy',(r.top+(window.scrollY||0)+oy+bb[1]*k).toFixed(2)+'px');st.setProperty('--fw',((bb[2]-bb[0])*k).toFixed(2)+'px');st.setProperty('--fh',((bb[3]-bb[1])*k).toFixed(2)+'px');}catch(e){}})();`;

export default function Flyer() {
  return (
    <>
      <div className="flyer" id="flyer" aria-hidden="true">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img className="ras day" src="/assets/leaf-day.png" alt="" />
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img className="ras night" src="/assets/leaf-night.png" alt="" />
        <div className="fgrain" aria-hidden="true"></div>
        <svg className="morph" id="morph" viewBox="0 0 86 67" aria-hidden="true">
          <defs><linearGradient id="lg" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="86" y2="0"><stop id="s0" offset="0" stopColor="#B59A7D" /><stop id="s1" offset="1" stopColor="#B99E80" /></linearGradient></defs>
          <path id="mpath" fill="url(#lg)" opacity="0" d="" />
          <path id="rib" fill="var(--page)" opacity="0" d="" />
        </svg>
      </div>
      <svg id="samp" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"></svg>
      {/* Before the beat hydrates, the leaf would be missing from the hero (both renders omit it). This runs at parse
          time and puts the raster in its cutout frame with the beat's own object-fit maths; the beat overrides it. */}
      <script dangerouslySetInnerHTML={{ __html: FIRST_FRAME }} />
    </>
  );
}
