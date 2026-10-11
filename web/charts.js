/* Tiny SVG chart kit: line charts with crosshair tooltips, and sparklines.
   Colors come from CSS tokens (--s1..--s6) so light/dark are selected, not flipped. */
(function () {
  const NS = "http://www.w3.org/2000/svg";
  const tip = () => document.getElementById("tooltip");

  function el(tag, attrs, parent) {
    const e = document.createElementNS(NS, tag);
    for (const k in attrs || {}) e.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(e);
    return e;
  }
  function niceMax(v) {
    if (!(v > 0)) return 1;
    const p = Math.pow(10, Math.floor(Math.log10(v)));
    for (const m of [1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10]) if (m * p >= v) return m * p;
    return 10 * p;
  }
  function shortDate(w) { const [, m, d] = w.split("-"); return `${+m}/${+d}`; }
  function weekRange(w) {
    const s = new Date(w + "T00:00:00"); const e = new Date(s); e.setDate(e.getDate() + 6);
    return `${s.getMonth() + 1}/${s.getDate()} – ${e.getMonth() + 1}/${e.getDate()}`;
  }

  function showTip(x, y, html) {
    const t = tip(); t.innerHTML = html; t.hidden = false;
    const r = t.getBoundingClientRect();
    let left = x + 14, top = y + 14;
    if (left + r.width > window.innerWidth - 8) left = x - r.width - 14;
    if (top + r.height > window.innerHeight - 8) top = y - r.height - 14;
    t.style.left = Math.max(8, left) + "px"; t.style.top = Math.max(8, top) + "px";
  }
  function hideTip() { tip().hidden = true; }

  /* opts: { labels, series:[{name, values, color}], height, yFmt, window:{from,label}, area, directLabels, legend } */
  function lineChart(container, opts) {
    const draw = () => {
      container.innerHTML = "";
      const W = Math.max(280, container.clientWidth);
      const H = opts.height || 240;
      const n = opts.labels.length;
      const series = opts.series;
      const direct = opts.directLabels ?? series.length <= 4;
      const m = { t: 14, r: direct && series.length > 1 ? 96 : 16, b: 26, l: 46 };
      const iw = W - m.l - m.r, ih = H - m.t - m.b;
      const all = series.flatMap(s => s.values.filter(v => v != null));
      const ymax = niceMax(Math.max(...all, 0) * 1.08);
      const x = i => m.l + (n <= 1 ? iw / 2 : (i / (n - 1)) * iw);
      const y = v => m.t + ih - (v / ymax) * ih;
      const fmt = opts.yFmt || (v => v.toFixed(1));

      const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, height: H, role: "img", "aria-label": opts.aria || "折线图" }, container);
      if (opts.window && opts.window.from < n) {
        const x0 = x(Math.max(0, opts.window.from - 0.5)), x1 = x(n - 1) + (n > 1 ? iw / (n - 1) / 2 : 0);
        el("rect", { class: "win", x: x0, y: m.t, width: Math.min(x1, m.l + iw) - x0, height: ih }, svg);
        if (opts.window.label) el("text", { class: "win-label", x: x0 + 6, y: m.t + 12 }, svg).textContent = opts.window.label;
      }
      for (let k = 0; k <= 4; k++) {
        const v = (ymax / 4) * k, yy = y(v);
        el("line", { class: k ? "gridline" : "baseline", x1: m.l, x2: m.l + iw, y1: yy, y2: yy }, svg);
        el("text", { x: m.l - 8, y: yy + 4, "text-anchor": "end" }, svg).textContent = fmt(v);
      }
      const step = Math.max(1, Math.ceil(n / Math.max(2, Math.floor(iw / 70))));
      for (let i = 0; i < n; i += step) {
        el("text", { x: x(i), y: H - 6, "text-anchor": "middle" }, svg).textContent = shortDate(opts.labels[i]);
      }

      const pathFor = vals => {
        let d = "", pen = false;
        vals.forEach((v, i) => {
          if (v == null) { pen = false; return; }
          d += (pen ? "L" : "M") + x(i).toFixed(1) + "," + y(v).toFixed(1); pen = true;
        });
        return d;
      };
      series.forEach(s => {
        if (opts.area && series.length === 1) {
          const pts = s.values.map((v, i) => v == null ? null : [x(i), y(v)]).filter(Boolean);
          if (pts.length > 1) {
            const d = `M${pts[0][0]},${y(0)} ` + pts.map(p => `L${p[0]},${p[1]}`).join(" ") + ` L${pts[pts.length - 1][0]},${y(0)} Z`;
            el("path", { d, class: "area", fill: s.color }, svg);
          }
        }
        el("path", { d: pathFor(s.values), class: "line", stroke: s.color }, svg);
      });

      if (direct && series.length > 1) {
        const ends = series.map(s => {
          let i = s.values.length - 1; while (i >= 0 && s.values[i] == null) i--;
          return { s, yy: i >= 0 ? y(s.values[i]) : m.t + ih };
        }).sort((a, b) => a.yy - b.yy);
        for (let i = 1; i < ends.length; i++) if (ends[i].yy - ends[i - 1].yy < 14) ends[i].yy = ends[i - 1].yy + 14;
        ends.forEach(e => {
          el("text", { class: "dlabel", x: m.l + iw + 8, y: e.yy + 4 }, svg).textContent = e.s.name;
        });
      }

      const xh = el("line", { class: "xhair", y1: m.t, y2: m.t + ih, visibility: "hidden" }, svg);
      const dots = series.map(s => el("circle", { r: 4, fill: s.color, class: "dot-ring", visibility: "hidden" }, svg));
      const hit = el("rect", { x: m.l - 10, y: 0, width: iw + 20, height: H, fill: "transparent" }, svg);
      hit.addEventListener("pointermove", ev => {
        const r = svg.getBoundingClientRect();
        const px = (ev.clientX - r.left) * (W / r.width);
        const i = Math.max(0, Math.min(n - 1, Math.round(((px - m.l) / iw) * (n - 1))));
        xh.setAttribute("x1", x(i)); xh.setAttribute("x2", x(i)); xh.setAttribute("visibility", "visible");
        const rows = [];
        series.forEach((s, k) => {
          const v = s.values[i];
          if (v == null) { dots[k].setAttribute("visibility", "hidden"); return; }
          dots[k].setAttribute("cx", x(i)); dots[k].setAttribute("cy", y(v)); dots[k].setAttribute("visibility", "visible");
          rows.push({ s, v });
        });
        rows.sort((a, b) => b.v - a.v);
        const extra = opts.tipExtra ? opts.tipExtra(i) : "";
        showTip(ev.clientX, ev.clientY,
          `<div class="tt-h">${weekRange(opts.labels[i])}</div>` +
          rows.map(r => `<div class="tt-r"><span><i style="background:${r.s.color}"></i>${r.s.name}</span><b>${fmt(r.v)}</b></div>`).join("") + extra);
      });
      hit.addEventListener("pointerleave", () => {
        xh.setAttribute("visibility", "hidden"); dots.forEach(d => d.setAttribute("visibility", "hidden")); hideTip();
      });

      if ((opts.legend ?? series.length >= 2)) {
        const lg = document.createElement("div"); lg.className = "legend";
        lg.innerHTML = series.map(s => `<span><i style="background:${s.color}"></i>${s.name}</span>`).join("");
        container.appendChild(lg);
      }
    };
    draw();
    if (window.ResizeObserver) {
      let w = container.clientWidth;
      new ResizeObserver(() => { if (Math.abs(container.clientWidth - w) > 4) { w = container.clientWidth; draw(); } }).observe(container);
    }
  }

  /* Sparkline into an existing <svg>. opts: { labels, recentFrom, color, fmt } */
  function sparkline(svg, values, opts) {
    svg.innerHTML = "";
    const W = 200, H = 54, pad = 4;
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    svg.setAttribute("preserveAspectRatio", "none");
    const n = values.length;
    const vmax = Math.max(...values.filter(v => v != null), 0) || 1;
    const x = i => pad + (n <= 1 ? 0 : (i / (n - 1)) * (W - 2 * pad));
    const y = v => H - pad - (v / vmax) * (H - 2 * pad);
    const color = opts.color || "var(--s1)";
    if (opts.recentFrom != null && opts.recentFrom < n) {
      el("rect", { x: x(opts.recentFrom) - 2, y: 0, width: W - x(opts.recentFrom) + 2, height: H, fill: "var(--window)" }, svg);
    }
    el("line", { x1: 0, x2: W, y1: H - pad, y2: H - pad, stroke: "var(--axis)", "stroke-width": 1, "vector-effect": "non-scaling-stroke" }, svg);
    const pts = values.map((v, i) => v == null ? null : [x(i), y(v)]).filter(Boolean);
    if (pts.length > 1) {
      el("path", { d: `M${pts[0][0]},${H - pad} ` + pts.map(p => `L${p[0]},${p[1]}`).join(" ") + ` L${pts[pts.length - 1][0]},${H - pad} Z`, fill: color, opacity: 0.1 }, svg);
      el("path", { d: "M" + pts.map(p => p.join(",")).join(" L"), fill: "none", stroke: color, "stroke-width": 2, "stroke-linejoin": "round", "vector-effect": "non-scaling-stroke" }, svg);
    }
    if (opts.labels) {
      const fmt = opts.fmt || (v => v.toFixed(2));
      svg.addEventListener("pointermove", ev => {
        const r = svg.getBoundingClientRect();
        const i = Math.max(0, Math.min(n - 1, Math.round(((ev.clientX - r.left) / r.width) * (n - 1))));
        const v = values[i];
        showTip(ev.clientX, ev.clientY, `<div class="tt-h">${weekRange(opts.labels[i])}</div><div class="tt-r"><span>${opts.name || ""}</span><b>${v == null ? "—" : fmt(v)}</b></div>`);
      });
      svg.addEventListener("pointerleave", hideTip);
    }
  }

  window.Charts = { lineChart, sparkline, weekRange, shortDate };
})();
