// ShouldISellYet — shared market rendering.
//
// The market half of a report: the four signal dials with their methodology
// disclosures, the Realtor.com cross-check, and the line charts. Read by BOTH
// report surfaces:
//
//   my-report.html — the real report, from the customer's own numbers
//   report.html    — the public sample, from the same committed data
//
// It lives here because it used to live in both. lineSVG was already copied
// into each file, and the sample's dials were a hand-typed snapshot that went
// stale the moment the data refreshed — by June 2026 it was showing a signal
// that no longer existed. One copy, one behaviour, no snapshot to forget.
//
// META is injected rather than read from a global: the two pages load their
// meta.json differently, and a module that reaches for someone else's global
// is a module that breaks when the other page changes.

const MARKET = (function () {
  // ————— FIGURES_KILL_SWITCH —————
  // Mirrors pipeline/figures_switch.FIGURES_OFF; the third of its three
  // copies, pinned to the other two by pipeline/test_figures_switch.py.
  //
  // This file is the renderer for BOTH report surfaces, so the switch has to
  // reach further here than on a ZIP page: the four dials AND their "What
  // goes in / Yours: …" disclosures, the deep-dive line charts, and the
  // national price percentile. What survives is what survives everywhere —
  // the reading word, the published danger lines, the methodology.
  //
  // NOT the Realtor.com cross-check: that is a different vendor under a
  // different switch (realtor_crosscheck.py). Only its direction-agreement
  // line is touched here, because that one is computed from OUR feed's
  // figures rather than theirs.
  const FIGURES_OFF = false;
  let META = null;
  const fmt = n => "$" + Math.round(n).toLocaleString("en-US");
  // renderCrossCheck writes straight into #xcheck, which both pages have.
  const $ = id => document.getElementById(id);

  const clampPct = x => Math.max(3, Math.min(97, x));
  const tcol = t => t==="r" ? "#d64545" : t==="a" ? "#c8891f" : t==="s" ? "#1f3a5f" : "#2e9e5b";

  // Strong seller's-market upgrade (mirrors pipeline/verdict.py): a clean green
  // (zero danger flags) with ≥3 strength signals renders as "strong". Danger
  // verdicts always win; signals the data doesn't provide are skipped.
  function strongSignals(m){
    let met = 0;
    if (m.mos != null && m.mos < 2.5) met++;
    if (m.spy != null && m.spy >= 0.05) met++;
    if (m.dom != null && m.domy != null){ const prior = m.dom - m.domy; if (prior > 0 && m.domy/prior <= -0.20) met++; }
    if (m.pd != null && m.pd < 0.20) met++;
    return met;
  }
  function applyStrong(d){
    if (!d || d.l !== "green" || (d.r||[]).length) return d;
    if (strongSignals(d.m||{}) >= 3) return Object.assign({}, d, {l:"strong"});
    return d;
  }

  // strong=true marks the strong-market thresholds on the same gauges.
  // Each row carries its own methodology (`how`) for the disclosure under the
  // dial: plain definition, the exact math in words, and why the danger line
  // sits where it does.
  //
  // The rationale used to end there because there was no backtest to cite.
  // There are now TWO, and both render rather than assert: backtestNote()
  // below appends the FHFA outcome rates from meta.national.backtest, and
  // /research/methodology.html carries recomputed case studies (Boise, Cape
  // Coral, and a market that crossed a line and recovered) built by
  // tools/backtest_cases.py from source under these exact thresholds. If you
  // add a performance claim here, back it from one of those — never type a
  // lead time or a hit rate into this file.
  function buildMetricRows(d, strong){
    // FIGURES_KILL_SWITCH: no rows means no dials AND no `how` disclosures,
    // which is the half that matters here — each one restates the ZIP's own
    // value twice ("What goes in: 105 homes listed…", "Yours: 57 days").
    if (FIGURES_OFF) return [];
    const m = d.m || {}, rows = [];
    if (m.mos != null){ const t = strong ? (m.mos<2.5?"s":"g") : (m.mos>6?"r":m.mos>4?"a":"g");
      rows.push({name:"MONTHS OF SUPPLY", val:m.mos.toFixed(1)+" mo", t, fill:clampPct(m.mos/8*100), th:strong?31.3:50,
        note:strong?(t==="s"?"past the strong line: 2.5 mo":"strong line: 2.5 mo"):(t==="g"?"line: 4.0 mo":"past the line"),
        how:{what:"If no new homes were listed, how long until everything currently for sale is sold.",
             goesin:(m.inv!=null&&m.sold!=null) ? m.inv.toLocaleString()+" homes listed for sale · "+m.sold.toLocaleString()+" sales in the latest month"
                   : "every home listed for sale, and the latest month of sales",
             math:"homes for sale ÷ homes sold per month", bt:"mos",
             why:strong?"Below 2.5 months, buyers are competing over too few homes — the classic seller's-market line.":"Markets that crossed 4.0 months of supply in past national downturns typically saw sellers lose pricing power, with price declines following.",
             yours:"Yours: "+m.mos.toFixed(1)+" mo"}}); }
    if (m.spy != null){ const t = strong ? (m.spy>=0.05?"s":"g") : (m.spy<-0.05?"r":m.spy<-0.02?"a":"g");
      rows.push({name:"PRICES VS. LAST YR", val:(m.spy>=0?"+":"−")+Math.abs(m.spy*100).toFixed(1)+"%", t, fill:clampPct((0.12-m.spy)/0.24*100), th:strong?29.2:58.3,
        note:strong?(t==="s"?"past the strong line: +5% y/y":"strong line: +5% y/y"):(t==="g"?"holding or rising":"line: −2% y/y"),
        how:{what:"What sellers are asking for the typical home now, compared with the same month a year ago. These are asking prices, not sale prices — asking prices run higher.",
             goesin:(m.inv!=null) ? "the asking prices of the "+m.inv.toLocaleString()+" homes currently listed, and of the homes listed the same month last year"
                   : "the asking price of every home currently listed, and of every home listed the same month last year",
             math:"this month's typical asking price ÷ the typical asking price 12 months ago, as a percent change", bt:"price",
             why:strong?"Prices rising 5%+ a year is faster than normal appreciation — a strength signal when supply is thin.":"A drop past −2% is bigger than month-to-month noise — the level that preceded wider price declines in past national downturns.",
             yours:"Yours: "+(m.spy>=0?"+":"−")+Math.abs(m.spy*100).toFixed(1)+"%"}}); }
    if (m.dom != null && m.domy != null){ const prior=m.dom-m.domy, p=prior>0?m.domy/prior:0;
      const t = strong ? (p<=-0.20?"s":"g") : (p>0.10?"a":"g");  // SPEC dom_shrink/dom_stretch
      // th must sit where the fill formula puts the danger value, so the dot
      // crosses the tick exactly when the color flips (axis audit 2026-08-28):
      // fill(p) = (p·100+50)/150 → +10% ⇒ 40, −20% ⇒ 20. The old 60/23.3
      // drew the tick at +40%/−15% — a dial could run amber left of its line.
      rows.push({name:"TIME ON MARKET", val:Math.round(m.dom)+" days", t, fill:clampPct((p*100+50)/150*100), th:strong?20:40,
        note:strong?(t==="s"?Math.round(-m.domy)+" days faster y/y":"strong line: −20% y/y"):(m.domy>0?"+"+Math.round(m.domy)+" days y/y":"as fast as last yr"),
        how:{what:"How long the homes currently for sale have been listed. This is time ON MARKET across unsold listings — not time-to-contract, and it runs longer.",
             goesin:(m.inv!=null) ? "days on market across the "+m.inv.toLocaleString()+" homes currently listed, and the same measure a year ago"
                   : "days on market across every home currently listed, and the same measure a year ago",
             math:"the middle (median) days on market among homes currently for sale, and how that compares with a year ago", bt:"dom",
             why:strong?"Listings turning over 20%+ faster than last year means buyers are moving quickly — a strength signal.":"Homes sitting 10% longer than a year ago is the earliest visible crack — it shows up months before prices actually move.",
             yours:"Yours: "+Math.round(m.dom)+" days"}}); }
    if (m.pd != null){ const t = strong ? (m.pd<0.20?"s":"g") : (m.pd>0.35?"a":"g");
      rows.push({name:"LISTINGS W/ PRICE CUTS", val:Math.round(m.pd*100)+"%", t, fill:clampPct(m.pd/0.7*100), th:strong?28.6:50,
        note:strong?(t==="s"?"below the strong line: 20%":"strong line: 20%"):(t==="g"?"line: 35%":"past the line"),
        how:{what:"The share of homes for sale that have already dropped their asking price at least once.",
             goesin:(m.inv!=null) ? "about "+Math.round(m.pd*m.inv).toLocaleString()+" of the "+m.inv.toLocaleString()+" homes for sale have cut their asking price"
                   : "every home currently for sale, counting those that have cut their asking price",
             math:"listings with a price cut ÷ all active listings", bt:"cuts",
             why:strong?"Under 20%, few sellers are having to negotiate down — pricing power sits with sellers.":"Past 35%, more than a third of sellers aimed too high and had to come down — that's competition building for the day you list.",
             yours:"Yours: "+Math.round(m.pd*100)+"%"}}); }
    if (m.invy != null){ const t=m.invy>0.30?"a":"g";
      // Same audit: fill(+30%) = (30+20)/120 = 41.7 — the tick goes there,
      // not at 58.3 (which was +50% y/y, past where the color flips).
      rows.push({name:"NEW SUPPLY VS. LAST YR", val:(m.invy>=0?"+":"−")+Math.abs(m.invy*100).toFixed(0)+"%", t, fill:clampPct((m.invy*100+20)/120*100), th:41.7, note:t==="g"?"line: +30% y/y":"surging",
        how:{what:"How many homes are coming up for sale, compared with a year ago.",
             goesin:(m.inv!=null) ? m.inv.toLocaleString()+" homes for sale now vs. about "+Math.round(m.inv/(1+m.invy)).toLocaleString()+" a year ago"
                   : "the count of homes for sale now, against the same month last year",
             math:"homes for sale this month ÷ homes for sale the same month last year", bt:"inv",
             why:"A jump past +30% is a wave of new supply — when listings outrun buyers, price pressure follows.",
             yours:"Yours: "+(m.invy>=0?"+":"−")+Math.abs(m.invy*100).toFixed(0)+"%"}}); }
    // The backtest measured the DANGER lines; strong-market mode explains
    // different thresholds, so its disclosures skip the backtest sentence.
    if (strong) rows.forEach(r => { if (r.how) delete r.how.bt; });
    return rows.slice(0,4);
  }
  // Measured backtest sentence for a dial's disclosure, when the pipeline has
  // shipped one (meta.national.backtest — Redfin year-end signals vs. FHFA's
  // official ZIP index the following year). Falls back to silence, never to a
  // made-up number.
  function backtestNote(key){
    const bt = META && META.national && META.national.backtest;
    if (!bt || !key || !bt.sig || !bt.sig[key]) return "";
    const s = bt.sig[key];
    return " In our backtest (" + bt.y0 + "–" + bt.y1 + " year-end signals vs. FHFA's official ZIP price indexes the following year), " +
      "markets past this line saw prices fall the next year " + s.x + "% of the time, vs. " + s.c + "% for markets inside it.";
  }

  // One-word state for the "Yours: …" restatement in each disclosure
  function stateWord(t){
    return t==="r" ? "past the danger line"
         : t==="a" ? "past the warning line"
         : t==="s" ? "past the strong-market line"
         : "well inside healthy";
  }
  function renderMetrics(rows, zip){
    const period = (META && META.period) ? META.period : "the latest release";
    return rows.map(r => {
      const how = r.how ? (
        '<details class="how"><summary>How this is measured</summary><div class="how-body">'+
          '<div>'+r.how.what+'</div>'+
          '<div><b>What goes in:</b> '+r.how.goesin+' — ZIP '+zip+', through '+period+'.</div>'+
          '<div><b>The math:</b> '+r.how.math+'.</div>'+
          '<div><b>Why the line is there:</b> '+r.how.why+backtestNote(r.how.bt)+'</div>'+
          '<div><b>'+r.how.yours+'</b> — '+stateWord(r.t)+'.</div>'+
        '</div></details>') : '';
      // .pf is the print/PDF fallback: browsers drop background-colored spans
      // by default when printing, so the pass/fail state and the line each
      // dial is judged against must also exist as TEXT. Hidden on screen
      // (the gauge says it), shown by the @media print rules.
      return '<div class="metric-block"><div class="metric"><span class="name">'+r.name+'</span>'+
      '<span class="val" style="color:'+tcol(r.t)+'">'+r.val+'</span>'+
      '<span class="track"><span class="fill" style="width:'+r.fill+'%;background:'+tcol(r.t)+'"></span><span class="th" style="left:'+r.th+'%"></span></span>'+
      '<span class="note">'+r.note+'</span>'+
      '<span class="pf">'+r.val+' — '+stateWord(r.t)+' ('+r.note+')</span></div>'+how+'</div>';
    }).join("");
  }


  // ————— Independent listing-feed cross-check (Realtor.com) —————
  // A second, independent read on the same market: fresher (listings move
  // before closings) and differently defined — so it corroborates direction,
  // it does NOT feed the verdict. Definitions differ enough (their days-on-
  // market counts listing days; their price-cut share uses their own listing
  // universe) that comparing exact levels across feeds would mislead.
  function renderCrossCheck(d){
    const x = d.x, m = d.m || {}, el = $("xcheck");
    // The kill switch is enforced server-side: when it is off, no cross-check
    // block is fetched, written, or shipped, so the client simply finds no
    // data. It used to answer that by vanishing the strip, which reads as a
    // rendering bug and quietly changes the page's shape. One quiet line
    // instead — vendor-neutral on purpose, because a surface that has stopped
    // showing a source should not still be naming it.
    if (!x){
      // NOTHING RENDERS (operator decision 2026-08-29). While the cross-check
      // is switched off, no record carries `x`, and a first-time visitor —
      // the only kind this site has — should not be told about a feature
      // they have never seen. The unavailable-line copy this replaces was
      // written for readers who remembered the strip; that audience never
      // existed. The x-present branch below stays intact for the day the
      // licence review lets the feed back on.
      if (el) { el.style.display = "none"; el.innerHTML = ""; }
      return;
    }
    const MON = ["January","February","March","April","May","June","July","August","September","October","November","December"];
    const label = x.p ? MON[+x.p.slice(5,7)-1] + " " + x.p.slice(0,4) : "";
    // ONE LINE (2026-08-28). The strip used to itemize the other feed's
    // counts; what a reader needs from a cross-check is only the agreement
    // verdict and the vintage. The detail rows crowded the dials above them.
    // Direction agreement — only judged on signals both feeds carry.
    const dir = (v, dead) => v == null ? null : v > dead ? 1 : v < -dead ? -1 : 0;
    const checks = [];
    // FIGURES_KILL_SWITCH. The cross-check's own numbers are the other
    // vendor's and are not this switch's business. This comparison is: it
    // reports whether OUR figures point the same way as theirs, which is a
    // statement about our figures and cannot be made without them.
    if (!FIGURES_OFF) {
      const rd = dir(m.domy, 1), xd = dir(x.domy, 0.03);      // our domy is DAYS; RDC's is a fraction
      if (rd != null && xd != null) checks.push(rd === xd);
      const ri = dir(m.invy, 0.03), xi = dir(x.invy, 0.03);
      if (ri != null && xi != null) checks.push(ri === xi);
    }
    let verdict;
    if (x.q) verdict = "year-over-year comparisons withheld this month (the feed flags this ZIP's comparability).";
    else if (!checks.length) verdict = "no overlapping signals to compare this month.";
    else verdict = checks.every(Boolean)
      ? "✓ both feeds read this market the same direction."
      : "◆ the two feeds read direction differently right now — often a timing gap between listings and closings.";
    el.innerHTML = '<span class="xk">INDEPENDENT CROSS-CHECK</span> · Realtor.com® listing feed' +
      (label ? " (" + label + ")" : "") + ": " + verdict;
    el.style.display = "block";
  }

  // ————— Deep-dive helpers —————
  const MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  const MONTHS_LONG = ["January","February","March","April","May","June","July","August","September","October","November","December"];
  function monthLabel(startYM, i){
    const y = +startYM.slice(0,4), m = +startYM.slice(5,7);
    const t = (y*12 + (m-1)) + i;
    return MONTHS[t%12] + " '" + String(Math.floor(t/12)).slice(2);
  }
  function lastIdx(arr){ for (let i=arr.length-1;i>=0;i--) if (arr[i]!=null) return i; return -1; }
  function atOrNear(arr, i){ // value at i, or nearest non-null within 2
    for (const j of [i, i-1, i+1, i-2, i+2]) if (j>=0 && j<arr.length && arr[j]!=null) return arr[j];
    return null;
  }
  // A fixed 640-unit viewBox scaled into a phone-width container shrinks every
  // label with it: measured at 375px the container is 285px, a scale of 0.445,
  // so the 10-unit axis text rendered at 4.45 REAL pixels — the paid report's
  // charts were unreadable on a phone. The fix is a narrower viewBox on narrow
  // screens (scale ~0.95 instead of 0.445), not bigger font units, because at
  // 640 wide the labels would then collide with each other. Gutters and tick
  // density scale with it: 640 units has room for a 58-unit y-gutter and a
  // tick every 6 months; 300 does not.
  const NARROW = typeof window !== "undefined" && window.innerWidth <= 640;
  function lineSVG(series, startYM, opts){
    // FIGURES_KILL_SWITCH. A chart is not a picture of the figures, it IS the
    // figures: this one draws every monthly observation as a point and then
    // labels four gridlines, the peak and the end value in plain text. "" is
    // the same thing it already returns for a series too short to plot, so
    // every caller's existing empty-chart handling covers this.
    if (FIGURES_OFF) return "";
    const o = Object.assign({w:NARROW?300:640,h:200,color:"#1f3a5f",fmt:v=>fmt(v),peak:true,area:true}, opts||{});
    const pts = series.map((v,i)=>[i,v]).filter(p=>p[1]!=null);
    if (pts.length < 6) return "";
    const xs = pts.map(p=>p[0]), ys = pts.map(p=>p[1]);
    const x0 = Math.min(...xs), x1 = Math.max(...xs);
    let y0 = Math.min(...ys), y1 = Math.max(...ys);
    if (y1===y0) y1 = y0*1.01+1;
    const pad = (y1-y0)*0.14; y0-=pad; y1+=pad;
    const L = NARROW?38:58, R = NARROW?44:64, T=14, B=30;
    const X = i => L + (i-x0)/(x1-x0)*(o.w-L-R);
    const Y = v => T + (1-(v-y0)/(y1-y0))*(o.h-T-B);
    // gridlines: 4 evenly spaced levels
    let grid = "";
    for (let g=0; g<4; g++){
      const gv = y0+pad + (g/3)*((y1-pad)-(y0+pad));
      grid += '<line x1="'+L+'" y1="'+Y(gv).toFixed(1)+'" x2="'+(o.w-R)+'" y2="'+Y(gv).toFixed(1)+'" stroke="#f0ebe0"/>'+
              '<text x="4" y="'+(Y(gv)+3.5).toFixed(1)+'" font-size="10" font-family="IBM Plex Mono,monospace" fill="#a49d8d">'+o.fmt(gv)+'</text>';
    }
    // x ticks every 6 months — every 12 on a narrow viewBox, where 6 would put
    // the month labels closer together than the labels are wide.
    const tickEvery = NARROW ? 12 : 6;
    let ticks = "";
    for (let i=x0; i<=x1; i++){
      if ((i-x0)%tickEvery===0 && i<=x1-2){
        ticks += '<line x1="'+X(i).toFixed(1)+'" y1="'+(o.h-B+2)+'" x2="'+X(i).toFixed(1)+'" y2="'+(o.h-B+6)+'" stroke="#d7d0c2"/>'+
                 '<text x="'+X(i).toFixed(1)+'" y="'+(o.h-8)+'" text-anchor="middle" font-size="9.5" font-family="IBM Plex Mono,monospace" fill="#a49d8d">'+monthLabel(startYM,i)+'</text>';
      }
    }
    // path + optional area
    let path = "", pen = false, area = "";
    series.forEach((v,i)=>{
      if (v==null){ pen=false; return; }
      path += (pen?"L":"M") + X(i).toFixed(1) + "," + Y(v).toFixed(1); pen=true;
    });
    if (o.area){
      let ap = "", apen = false, firstX=null, lastX=null;
      series.forEach((v,i)=>{
        if (v==null){ apen=false; return; }
        if (!apen && firstX===null) firstX = X(i);
        ap += (apen?"L":(ap?"M":"M")) + X(i).toFixed(1) + "," + Y(v).toFixed(1); apen=true;
        lastX = X(i);
      });
      if (firstX!==null) area = '<path d="'+ap+' L'+lastX.toFixed(1)+','+(o.h-B)+' L'+firstX.toFixed(1)+','+(o.h-B)+' Z" fill="'+o.color+'" opacity="0.06"/>';
    }
    // peak marker
    let peakSvg = "";
    if (o.peak){
      let pi=-1, pv=-Infinity;
      series.forEach((v,i)=>{ if(v!=null&&v>pv){pv=v;pi=i;} });
      if (pi>=0) peakSvg = '<line x1="'+X(pi).toFixed(1)+'" y1="'+Y(pv).toFixed(1)+'" x2="'+X(pi).toFixed(1)+'" y2="'+T+'" stroke="#c8891f" stroke-dasharray="2 3" opacity="0.6"/>'+
        '<circle cx="'+X(pi).toFixed(1)+'" cy="'+Y(pv).toFixed(1)+'" r="4" fill="#c8891f"/>'+
        '<text x="'+Math.min(Math.max(X(pi),L+38),o.w-R-40).toFixed(1)+'" y="'+(T-2+12)+'" text-anchor="middle" font-size="9.5" font-family="IBM Plex Mono,monospace" fill="#8a7a55">PEAK '+monthLabel(startYM,pi).toUpperCase()+' · '+o.fmt(pv)+'</text>';
    }
    // end-value tag
    const li = lastIdx(series);
    let endTag = "";
    if (li>=0){
      endTag = '<circle cx="'+X(li).toFixed(1)+'" cy="'+Y(series[li]).toFixed(1)+'" r="4.5" fill="'+o.color+'"/>'+
        '<text x="'+(o.w-4)+'" y="'+(Y(series[li])+3.5).toFixed(1)+'" text-anchor="end" font-size="10.5" font-weight="bold" font-family="IBM Plex Mono,monospace" fill="'+o.color+'">'+o.fmt(series[li])+'</text>';
    }
    return '<svg viewBox="0 0 '+o.w+' '+o.h+'" style="width:100%;height:auto;display:block">'+
      grid + ticks + area +
      '<path d="'+path+'" fill="none" stroke="'+o.color+'" stroke-width="2.4" stroke-linecap="round"/>'+
      peakSvg + endTag + '</svg>';
  }
  const pctf = x => (x>=0?"+":"−") + Math.abs(x*100).toFixed(1) + "%";

  // ————— "The bigger picture" boxes —————
  // Where this ZIP's price trend sits nationally, and what rates are doing to
  // the buyer pool. Pure function of the ZIP's metrics + meta, so the sample
  // and the real report cannot disagree about the national picture.
  // The live current-basis distribution (web/data/distribution.json) — rating
  // shares and per-signal quantiles across every ZIP with a live reading,
  // computed by provision_readings.py from the same records this page serves.
  // Set by the report page after it fetches the file; null until then, and
  // contextBoxes degrades to the financing backdrop alone.
  let DIST = null;
  function setDistribution(d) { DIST = d && d.n >= 20 ? d : null; }
  // Percentile of v within a 101-point quantile array: the share of live
  // markets whose value sits below v.
  function pctileIn(q, v) {
    if (!q || v == null) return null;
    let lo = 0; while (lo < 101 && q[lo] < v) lo++;
    return Math.max(1, Math.min(99, lo === 0 ? 1 : lo - 1));
  }

  function contextBoxes(m) {
    const nat = META && META.national;
    if (!nat) return "";
    const boxes = [];
    // The prior vendor's national sold-price deciles were withheld here from
    // the sunset (2026-08) until 2026-08-28 — interpolating a current-vendor
    // asking-price change against them compared two different measurements.
    // This box is the CLEAN-lineage replacement: every number in it comes
    // from the live current-basis readings, published by this same build.
    if (DIST && DIST.counts) {
      const c = DIST.counts, n = DIST.n;
      const pc = k => Math.round((c[k] || 0) / n * 100);
      const share = "Of the " + n.toLocaleString() + " ZIPs with a live reading" +
        (DIST.period ? " (data through " + DIST.period + ")" : "") + ": <b>" +
        pc("green") + "% read HOLD · " + pc("yellow") + "% WATCH · " + pc("red") + "% ACT</b>.";
      const bits = [];
      const pSpy = pctileIn(DIST.q && DIST.q.spy, m.spy);
      if (pSpy != null) bits.push("asking prices here are rising faster than about <b>" + pSpy + "%</b> of them");
      const stretch = (m.dom != null && m.domy != null && m.dom - m.domy > 0)
        ? m.domy / (m.dom - m.domy) : null;
      const pDom = pctileIn(DIST.q && DIST.q.domstretch, stretch);
      if (pDom != null) bits.push("time-on-market is stretching more than in about <b>" + pDom + "%</b>");
      boxes.push('<div class="ctx"><div class="ch">Your ZIP among the markets we score today</div><p>' +
        share + (bits.length ? " In this ZIP, " + bits.join("; ") + "." : "") + '</p></div>');
    }
    if (nat.mortgage) {
      const pay = r => { const i=r/100/12; return i*Math.pow(1+i,360)/(Math.pow(1+i,360)-1); };
      const power = pay(nat.mortgage.year_ago)/pay(nat.mortgage.now) - 1;
      boxes.push('<div class="ctx"><div class="ch">The financing backdrop</div><p>30-year rates: <b>'+nat.mortgage.now.toFixed(2)+'%</b> now vs. '+nat.mortgage.year_ago.toFixed(2)+'% a year ago — buyers of your home can afford about <b>'+pctf(power)+'</b> house for the same monthly payment. '+(power<-0.02?"Rising rates shrink your buyer pool — a headwind if you wait.":power>0.02?"Falling rates expand your buyer pool — a tailwind for sellers.":"Roughly neutral for your buyer pool right now.")+'</p></div>');
    }
    return boxes.join("");
  }

  return {
    setMeta(m) { META = m; },
    get meta() { return META; },
    // Exported so the two report pages can gate the figures they render
    // THEMSELVES — the paid report prints plenty this module never sees. A
    // fourth hand-typed copy of the flag is the thing to avoid; asking the
    // renderer costs nothing and cannot drift.
    showsFigures() { return !FIGURES_OFF; },
    clampPct, tcol, strongSignals, applyStrong,
    buildMetricRows, backtestNote, stateWord, renderMetrics, renderCrossCheck,
    MONTHS, MONTHS_LONG, monthLabel, lastIdx, atOrNear, lineSVG, pctf, fmt,
    contextBoxes, setDistribution,
  };
})();
