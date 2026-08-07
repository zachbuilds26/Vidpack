(async()=>{const R={};
 const vis=n=>n.offsetParent!==null;
 R.namelessControls=[...document.querySelectorAll('button,a,input,select,summary,[role=button]')]
  .filter(vis).filter(n=>!(n.innerText||'').trim() && !n.getAttribute('aria-label')
    && !n.getAttribute('title') && !n.getAttribute('aria-labelledby')).length;
 R.smallTargets=[...document.querySelectorAll('.btn,.nav-item,.tab,.rail-niche,.chip')]
  .filter(vis).map(n=>Math.round(n.getBoundingClientRect().height)).filter(h=>h>0&&h<32).length;
 R.imgsNoAlt=[...document.querySelectorAll('img')].filter(i=>!i.hasAttribute('alt')).length;
 R.svgUnhidden=[...document.querySelectorAll('svg.ic')].filter(s=>s.getAttribute('aria-hidden')!=='true').length;
 R.visibleH1=[...document.querySelectorAll('h1')].filter(vis).map(h=>h.innerText.trim().slice(0,34));
 R.liveRegions=[...document.querySelectorAll('[aria-live]')].map(n=>(n.id||n.tagName)+':'+n.getAttribute('aria-live'));
 R.skipLink=!!document.querySelector('.skip-link');
 R.lang=document.documentElement.lang;
 const f=document.querySelector('.nav-item')||document.querySelector('.btn');
 if(f){f.focus(); R.focusMoved=document.activeElement===f;}
 R.reducedMotionRule=[...document.styleSheets].some(ss=>{try{
   return [...ss.cssRules].some(r=>r.conditionText&&r.conditionText.includes('prefers-reduced-motion'))}catch(e){return false}});
 document.title=JSON.stringify(R);})()
