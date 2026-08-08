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
    if (m.dom != null && m.domy != null){ const prior = m.dom - m.domy; if (prior > 0 && m.domy/prior <= -0.15) met++; }
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
  // sits where it does. Threshold rationale is deliberately general — we have
  // no proprietary backtest, so claims stay at "the level that preceded price
  // declines in past national downturns," which is the honest version.
  function buildMetricRows(d, strong){
    const m = d.m || {}, rows = [];
    if (m.mos != null){ const t = strong ? (m.mos<2.5?"s":"g") : (m.mos>6?"r":m.mos>4?"a":"g");
      rows.push({name:"MONTHS OF SUPPLY", val:m.mos.toFixed(1)+" mo", t, fill:clampPct(m.mos/8*100), th:strong?31.3:50,
        note:strong?(t==="s"?"past the strong line: 2.5 mo":"strong line: 2.5 mo"):(t==="g"?"line: 4.0 mo":"past the line"),
        how:{what:"If no new homes were listed, how long until everything currently for sale is sold.",
             goesin:(m.inv!=null&&m.sold!=null) ? m.inv.toLocaleString()+" homes listed for sale · "+m.sold.toLocaleString()+" homes sold in the latest month"
                   : "every home listed for sale, and every home sold in the latest month",
             math:"homes for sale ÷ homes sold per month", bt:"mos",
             why:strong?"Below 2.5 months, buyers are competing over too few homes — the classic seller's-market line.":"Markets that crossed 4.0 months of supply in past national downturns typically saw sellers lose pricing power, with price declines following.",
             yours:"Yours: "+m.mos.toFixed(1)+" mo"}}); }
    if (m.spy != null){ const t = strong ? (m.spy>=0.05?"s":"g") : (m.spy<-0.05?"r":m.spy<-0.02?"a":"g");
      rows.push({name:"PRICES VS. LAST YR", val:(m.spy>=0?"+":"−")+Math.abs(m.spy*100).toFixed(1)+"%", t, fill:clampPct((0.12-m.spy)/0.24*100), th:strong?29.2:58.3,
        note:strong?(t==="s"?"past the strong line: +5% y/y":"strong line: +5% y/y"):(t==="g"?"holding or rising":"line: −2% y/y"),
        how:{what:"What the typical home sells for now, compared with the same month a year ago.",
             goesin:(m.sold!=null) ? "the sale prices of the "+m.sold.toLocaleString()+" homes sold in the latest month, and of the homes sold the same month last year"
                   : "the sale price of every home sold in the latest month, and of every home sold the same month last year",
             math:"this month's typical sale price ÷ the typical price 12 months ago, as a percent change", bt:"price",
             why:strong?"Prices rising 5%+ a year is faster than normal appreciation — a strength signal when supply is thin.":"A drop past −2% is bigger than month-to-month noise — the level that preceded wider price declines in past national downturns.",
             yours:"Yours: "+(m.spy>=0?"+":"−")+Math.abs(m.spy*100).toFixed(1)+"%"}}); }
    if (m.dom != null && m.domy != null){ const prior=m.dom-m.domy, p=prior>0?m.domy/prior:0;
      const t = strong ? (p<=-0.15?"s":"g") : (p>0.4?"a":"g");
      rows.push({name:"TIME TO SELL", val:Math.round(m.dom)+" days", t, fill:clampPct((p*100+50)/150*100), th:strong?23.3:60,
        note:strong?(t==="s"?Math.round(-m.domy)+" days faster y/y":"strong line: −15% y/y"):(m.domy>0?"+"+Math.round(m.domy)+" days y/y":"as fast as last yr"),
        how:{what:"How many days the typical home sits on the market before a buyer commits.",
             goesin:(m.sold!=null) ? "days from listing to contract for the "+m.sold.toLocaleString()+" homes sold in the latest month, and for last year's sales"
                   : "days from listing to contract for every home sold in the latest month, and for last year's sales",
             math:"the middle (median) days-on-market among homes that sold, and how that compares with a year ago", bt:"dom",
             why:strong?"Homes selling 15%+ faster than last year means buyers are moving quickly — a strength signal.":"Homes sitting 40% longer than a year ago is the earliest visible crack — it shows up months before prices actually move.",
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
    if (m.invy != null){ const t=m.invy>0.5?"a":"g";
      rows.push({name:"NEW SUPPLY VS. LAST YR", val:(m.invy>=0?"+":"−")+Math.abs(m.invy*100).toFixed(0)+"%", t, fill:clampPct((m.invy*100+20)/120*100), th:58.3, note:t==="g"?"line: +50% y/y":"surging",
        how:{what:"How many homes are coming up for sale, compared with a year ago.",
             goesin:(m.inv!=null) ? m.inv.toLocaleString()+" homes for sale now vs. about "+Math.round(m.inv/(1+m.invy)).toLocaleString()+" a year ago"
                   : "the count of homes for sale now, against the same month last year",
             math:"homes for sale this month ÷ homes for sale the same month last year", bt:"inv",
             why:"A jump past +50% is a wave of new supply — when listings outrun buyers, price pressure follows.",
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
      return '<div class="metric-block"><div class="metric"><span class="name">'+r.name+'</span>'+
      '<span class="val" style="color:'+tcol(r.t)+'">'+r.val+'</span>'+
      '<span class="track"><span class="fill" style="width:'+r.fill+'%;background:'+tcol(r.t)+'"></span><span class="th" style="left:'+r.th+'%"></span></span>'+
      '<span class="note">'+r.note+'</span></div>'+how+'</div>';
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
    if (!x){ el.style.display = "none"; return; }
    const MON = ["January","February","March","April","May","June","July","August","September","October","November","December"];
    const label = x.p ? MON[+x.p.slice(5,7)-1] + " " + x.p.slice(0,4) : "";
    const newer = x.p && META && META.period && x.p > META.period;
    const pf = v => (v>=0?"+":"−") + Math.abs(v*100).toFixed(0) + "%";
    const bits = [];
    if (x.inv != null) bits.push("<b>" + x.inv.toLocaleString() + "</b> homes listed" + (x.invy != null ? " (" + pf(x.invy) + " vs. last year)" : ""));
    if (x.dom != null) bits.push("typical listing <b>" + x.dom + " days</b> on the market" + (x.domy != null ? " (" + pf(x.domy) + ")" : ""));
    if (x.pdn != null) bits.push("<b>" + x.pdn.toLocaleString() + "</b> price cuts" + (x.pd != null ? " (" + (x.pd*100).toFixed(0) + "% of listings it tracks)" : ""));
    // Direction agreement — only judged on signals both feeds carry.
    const dir = (v, dead) => v == null ? null : v > dead ? 1 : v < -dead ? -1 : 0;
    const checks = [];
    const rd = dir(m.domy, 1), xd = dir(x.domy, 0.03);        // Redfin domy is DAYS; RDC's is a fraction
    if (rd != null && xd != null) checks.push(rd === xd);
    const ri = dir(m.invy, 0.03), xi = dir(x.invy, 0.03);
    if (ri != null && xi != null) checks.push(ri === xi);
    let verdictLine = "";
    if (x.q){
      verdictLine = '<div style="margin-top:6px;color:var(--fainter);font-size:12px">Year-over-year comparisons withheld this month — the feed flags this ZIP\'s comparability.</div>';
    } else if (checks.length){
      verdictLine = checks.every(Boolean)
        ? '<div class="agree" style="margin-top:6px">✓ Both feeds read this market the same direction.</div>'
        : '<div class="differ" style="margin-top:6px">◆ The two feeds read direction differently right now — often a timing gap between listings and closings; worth watching next month.</div>';
    }
    el.innerHTML = '<div class="xk">INDEPENDENT CROSS-CHECK · REALTOR.COM® LISTING FEED · ' +
      (label ? label.toUpperCase() : "") + (newer ? " (ONE MONTH NEWER THAN THE SALES DATA ABOVE)" : "") + '</div>' +
      (bits.length ? bits.join(" · ") + "." : "") + verdictLine;
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
  function contextBoxes(m) {
    const nat = META && META.national;
    if (!nat) return "";
    const boxes = [];
    if (nat.spy_deciles && nat.spy_deciles.length === 11 && m.spy != null) {
      const dec = nat.spy_deciles;
      let k = 0; while (k < 10 && m.spy > dec[k+1]) k++;
      const frac = k*10 + (dec[k+1] > dec[k] ? (m.spy-dec[k])/(dec[k+1]-dec[k])*10 : 5);
      const pctile = Math.max(1, Math.min(99, Math.round(frac)));
      const pack = pctile>=85 ? "near the top of the pack" : pctile>=60 ? "ahead of most markets"
                 : pctile>40 ? "squarely mid-pack" : pctile>15 ? "behind most markets" : "near the bottom of the pack";
      boxes.push('<div class="ctx"><div class="ch">Your ZIP vs. the nation</div><p>Prices here are rising faster than about <b>'+pctile+'%</b> of U.S. ZIP codes — '+pack+'. Across the country right now: '+nat.counts.green.toLocaleString()+' ZIPs read HOLD · '+nat.counts.yellow.toLocaleString()+' WATCH · '+nat.counts.red.toLocaleString()+' ACT.</p></div>');
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
    clampPct, tcol, strongSignals, applyStrong,
    buildMetricRows, backtestNote, stateWord, renderMetrics, renderCrossCheck,
    MONTHS, MONTHS_LONG, monthLabel, lastIdx, atOrNear, lineSVG, pctf, fmt,
    contextBoxes,
  };
})();
