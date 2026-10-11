(function () {
  const $view = document.getElementById("view");
  const $ops = document.getElementById("ops");
  const S = { snap: null, status: null, lastJob: null };
  const COLORS = ["var(--s1)", "var(--s2)", "var(--s3)", "var(--s4)", "var(--s5)", "var(--s6)"];
  const KIND = {
    acceleration: "加速", deceleration: "回落", synchrony: "跨领域同步", diffusion: "渗透",
    shift: "格局变化", emerging: "新词", volume: "投稿量", regime: "整体态势", thesis: "我的判断",
  };
  const TERM_STATUS = { new: "全新", revival: "回潮", rising: "升温" };
  // Headline candidates, in order: structural shifts (the 2016-GPU shape) beat single-term spikes.
  const HEADLINE_KINDS = ["synchrony", "diffusion", "regime", "acceleration", "shift"];
  const FEED_PER_KIND = 2;
  // Feed order: structural signals, then the user's theses, then term spikes and raw volume.
  const FEED_ORDER = [...HEADLINE_KINDS, "deceleration", "thesis", "emerging", "volume"];

  // Insight scores are not comparable across kinds (term cards score high by construction),
  // so the front page caps each kind and leads with the strongest structural signal.
  function frontPage(items) {
    const hero = HEADLINE_KINDS.map(k => items.find(i => i.kind === k)).find(Boolean) || items[0] || null;
    const per = {}, feed = [];
    for (const it of items) {
      if (it === hero || (per[it.kind] = (per[it.kind] || 0) + 1) > FEED_PER_KIND) continue;
      feed.push(it);
    }
    const rank = k => (FEED_ORDER.indexOf(k) + FEED_ORDER.length + 1) % (FEED_ORDER.length + 1);
    feed.sort((x, y) => rank(x.kind) - rank(y.kind) || y.score - x.score);
    return { hero, feed };
  }

  // Curve wall order: groups holding the user's own signals first; within a group, biggest change first.
  function wallGroups(signals, stats) {
    const groups = new Map();
    for (const s of signals) {
      if (!groups.has(s.grp)) groups.set(s.grp, []);
      groups.get(s.grp).push(s);
    }
    const key = s => { const st = stats[s.slug]; return st.new ? Infinity : st.lift ?? -Infinity; };
    for (const list of groups.values()) list.sort((a, b) => key(b) - key(a));
    return [...groups.entries()].sort(([, a], [, b]) => b.some(s => s.custom) - a.some(s => s.custom));
  }

  // ---- utils -------------------------------------------------------------
  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const pct = (x, d = 1) => x == null ? "—" : (x * 100).toFixed(d) + "%";
  const fmtShare = v => (v * 100).toFixed(v < 0.01 ? 2 : 1) + "%";
  const api = async (path, opts) => {
    const r = await fetch(path, opts && { method: opts.method || "POST", headers: { "Content-Type": "application/json" }, body: opts.body && JSON.stringify(opts.body) });
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || r.statusText);
    return j;
  };
  const sigBy = slug => S.snap?.signals.find(s => s.slug === slug);
  const catColor = cat => COLORS[S.snap.categories.findIndex(c => c.id === cat)] || "var(--muted)";
  const catName = cat => S.snap?.categories.find(c => c.id === cat)?.name || cat;
  const arxiv = id => `https://arxiv.org/abs/${id}`;
  const rel = iso => {
    if (!iso) return "从未";
    const m = (Date.now() - new Date(iso)) / 60000;
    if (m < 1) return "刚刚"; if (m < 60) return `${Math.round(m)} 分钟前`;
    if (m < 1440) return `${Math.round(m / 60)} 小时前`; return `${Math.round(m / 1440)} 天前`;
  };

  function liftBadge(st) {
    if (!st) return "";
    if (st.new) return `<span class="lift up">新出现</span>`;
    if (st.lift == null) return `<span class="lift flat">—</span>`;
    const cls = st.lift >= 1.1 ? "up" : st.lift <= 0.9 ? "down" : "flat";
    const arrow = cls === "up" ? "↑" : cls === "down" ? "↓" : "→";
    return `<span class="lift ${cls}" title="近期占比 / 基线占比">${arrow} ${st.lift.toFixed(2)}×</span>`;
  }

  function recentFrom() { return S.snap.weeks.length - S.snap.windows.recent; }

  function sparkFor(svg, slug) {
    const ser = S.snap.series[slug];
    if (!ser) return;
    Charts.sparkline(svg, ser.share, { labels: S.snap.weeks, recentFrom: recentFrom(), name: sigBy(slug)?.name, fmt: fmtShare });
  }

  function hydrateSparks(root) {
    root.querySelectorAll("svg[data-spark]").forEach(svg => sparkFor(svg, svg.dataset.spark));
    root.querySelectorAll("svg[data-vol]").forEach(svg => {
      Charts.sparkline(svg, S.snap.volume[svg.dataset.vol], { labels: S.snap.weeks, recentFrom: recentFrom(), name: "周投稿", fmt: v => v.toFixed(0), color: catColor(svg.dataset.vol) });
    });
  }

  function insightCard(it, { compact = false, actions = true } = {}) {
    const ev = it.evidence || {};
    let spark = "";
    if (!compact && ev.slug && S.snap?.series[ev.slug]) spark = `<svg data-spark="${esc(ev.slug)}"></svg>`;
    else if (!compact && ev.cat && S.snap?.volume[ev.cat]) spark = `<svg data-vol="${esc(ev.cat)}"></svg>`;
    const papers = !compact && ev.papers?.length
      ? `<ul class="i-papers">${ev.papers.slice(0, 3).map(p => `<li><a href="${arxiv(p.id)}" target="_blank" rel="noopener">${esc(p.title)}</a></li>`).join("")}</ul>` : "";
    const link = ev.slug ? `#/signal/${ev.slug}` : ev.term ? `#/papers?q=${encodeURIComponent(ev.term)}` : null;
    return `<article class="card insight ${compact ? "compact" : ""} ${it.status}" data-id="${it.id}">
      <div class="i-meta"><span class="kind ${it.kind}"><i></i>${KIND[it.kind] || it.kind}</span>
        <span>${Charts.weekRange(it.week)}</span>
        ${actions ? `<span class="i-actions rw">
          <button class="btn ghost" data-act="star" title="${it.status === "starred" ? "取消收藏" : "收藏"}">${it.status === "starred" ? "★" : "☆"}</button>
          <button class="btn ghost" data-act="dismiss" title="${it.status === "dismissed" ? "恢复" : "忽略"}">${it.status === "dismissed" ? "↺" : "×"}</button></span>` : ""}
      </div>
      <h3>${link ? `<a href="${link}">${esc(it.title)}</a>` : esc(it.title)}</h3>
      <p>${esc(it.body)}</p>
      ${spark || papers ? `<div class="i-ev">${spark}<div style="flex:1;min-width:0">${papers}</div></div>` : ""}
    </article>`;
  }

  function bindInsightActions(root, onChange) {
    root.addEventListener("click", async e => {
      const b = e.target.closest("button[data-act]"); if (!b) return;
      const card = b.closest(".insight"); const id = card.dataset.id;
      const cur = card.classList.contains("starred") ? "starred" : card.classList.contains("dismissed") ? "dismissed" : "new";
      const next = b.dataset.act === "star" ? (cur === "starred" ? "new" : "starred") : (cur === "dismissed" ? "new" : "dismissed");
      await api(`/api/insights/${id}`, { body: { status: next } });
      onChange && onChange();
    });
  }

  function notReady() {
    const j = S.status?.job;
    const prog = j?.total ? `${j.done} / ${j.total}` : "";
    $view.innerHTML = `<div class="card empty">
      <h3>正在建立第一批时间序列</h3>
      <p>Tern 正在从 arXiv 回填过去 ${S.status?.weeks ? "" : "若干"}周的论文样本（arXiv 限速 3 秒一次请求）。至少需要 3 个完整周才能画出曲线。</p>
      <p class="num">${esc(j?.message || "")} ${prog}</p>
      <p class="muted small">已入库 ${S.status?.papers ?? 0} 篇 · 页面会自动刷新</p></div>`;
  }

  // ---- ops bar -----------------------------------------------------------
  function renderOps() {
    const st = S.status; if (!st) return;
    const j = st.job;
    const busy = !!j.job;
    const pctDone = j.total ? Math.round((j.done / j.total) * 100) : 8;
    // Online copy: data is fetched and edited locally, so every write control is hidden (.rw).
    document.body.classList.toggle("readonly", !!st.readonly);
    if (st.readonly) {
      $ops.innerHTML = `<span class="job"><span class="dot"></span><span>数据更新于 ${rel(st.last_daily)} · 只读</span></span>`;
      return;
    }
    $ops.innerHTML = busy
      ? `<span class="job"><span class="dot live"></span><span>${esc(j.message)}</span><span class="progress"><i style="width:${pctDone}%"></i></span></span>`
      : `<span class="job"><span class="dot"></span><span>上次抓取 ${rel(st.last_daily)} · 下次 ${st.next_daily.slice(5).replace("T", " ")}</span></span>
         <button class="btn" id="run-daily">立即抓取</button>`;
    const b = document.getElementById("run-daily");
    if (b) b.onclick = async () => { b.disabled = true; await api("/api/run", { body: { kind: "daily" } }); poll(); };
  }

  let pollTimer;
  async function poll() {
    clearTimeout(pollTimer);
    try {
      S.status = await api("/api/status");
      renderOps();
      const job = S.status.job.job;
      const finished = S.lastJob && !job;
      const snapChanged = S.status.snapshot_at && S.snap && S.status.snapshot_at !== S.snap.generated_at;
      if (finished || snapChanged || (!S.snap?.ready && S.status.snapshot_at)) {
        await loadSnap();
        const r = route();
        if (!["theses", "signals-new"].includes(r.name)) render();
      }
      S.lastJob = job;
    } catch (e) { /* server restarting */ }
    pollTimer = setTimeout(poll, S.status?.job?.job ? 3000 : 30000);
  }

  async function loadSnap() { S.snap = await api("/api/snapshot"); }

  // ---- router ------------------------------------------------------------
  function route() {
    const h = location.hash.replace(/^#\/?/, "");
    const [path, query] = h.split("?");
    const parts = path.split("/").filter(Boolean);
    const qs = Object.fromEntries(new URLSearchParams(query || ""));
    if (parts[0] === "signal" && parts[1]) return { name: "signal", slug: decodeURIComponent(parts[1]), qs };
    if (parts[0] === "signals" && parts[1] === "new") return { name: "signals-new", qs };
    return { name: parts[0] || "radar", qs };
  }

  function render() {
    const r = route();
    document.querySelectorAll("#tabs a").forEach(a => {
      const t = a.dataset.tab;
      a.classList.toggle("on", t === r.name || (t === "signals" && (r.name === "signal" || r.name === "signals-new")));
    });
    if (!S.snap?.ready && r.name !== "papers") return notReady();
    const views = { radar, timeline, insights, signals: signalsView, signal: signalsView, "signals-new": signalsView, theses, papers };
    (views[r.name] || radar)(r);
    window.scrollTo({ top: 0 });
  }
  window.addEventListener("hashchange", render);

  // ---- radar -------------------------------------------------------------
  async function radar() {
    const snap = S.snap;
    const items = await api(`/api/insights?week=${snap.analysis_week}&limit=40`);
    const memoRes = await api("/api/memo");
    const { hero: top, feed } = frontPage(items);
    const accel = Object.values(snap.stats).filter(s => s.new || (s.lift && s.lift >= 1.25) ).length;
    const totalPapers = S.status?.papers ?? 0;
    const groups = wallGroups(snap.signals, snap.stats);

    $view.innerHTML = `
      <div class="page-head"><div>
        <div class="eyebrow">研究简报 · ${Charts.weekRange(snap.analysis_week)} · 近 ${snap.windows.recent} 周 vs 此前 ${snap.windows.base} 周</div>
        <h1>${top ? esc(top.title) : "本周没有显著变化"}</h1>
        ${top ? `<p>${esc(top.body)}</p>` : ""}
      </div></div>
      <div class="stats">
        <div class="card stat"><div class="label">已读论文</div><div class="value num">${totalPapers.toLocaleString()}</div><div class="hint">${snap.categories.length} 个 arXiv 分类</div></div>
        <div class="card stat"><div class="label">时间序列长度</div><div class="value num">${snap.weeks.length} 周</div><div class="hint">${Charts.shortDate(snap.weeks[0])} 起</div></div>
        <div class="card stat"><div class="label">本周洞察</div><div class="value num">${items.length}</div><div class="hint">累计 ${S.status?.insights ?? "—"} 条</div></div>
        <div class="card stat"><div class="label">加速中的信号</div><div class="value num">${accel} / ${snap.signals.length}</div><div class="hint">占比提升 ≥ 1.25×</div></div>
      </div>
      ${memoRes.memo ? `<section class="card lead"><div class="kicker">研究员备忘录 · ${esc(memoRes.memo.model)}</div><div class="memo">${md(memoRes.memo.text)}</div></section>` : ""}
      <div class="grid-2" style="margin-top:8px">
        <section>
          <h2 class="section">曲线墙</h2>
          <p class="section-sub">每条曲线 = 每周提及该主题的论文占比。蓝色底纹是"近期"窗口，与左侧基线比较得出倍数；组内按倍数从高到低排列。点进任意一条看分领域拆解。</p>
          ${groups.map(([g, list]) => `
            <div class="wall-group"><h4>${esc(g)}</h4><div class="wall">
              ${list.map(s => {
                const st = snap.stats[s.slug];
                return `<a class="card tile" href="#/signal/${s.slug}">
                  <div class="t-head"><span class="t-name">${esc(s.name)}</span>${liftBadge(st)}</div>
                  <div class="t-val num">${pct(st.recent_share, st.recent_share < 0.01 ? 2 : 1)} <span class="muted">· ${st.recent_count} 篇</span></div>
                  <svg data-spark="${s.slug}"></svg></a>`;
              }).join("")}
            </div></div>`).join("")}
        </section>
        <aside>
          <h2 class="section">本周洞察</h2>
          <p class="section-sub">每次抓取后自动重算；每种类型最多显示 ${FEED_PER_KIND} 条，新词的完整列表见下方新词雷达。</p>
          <div class="feed" id="feed">${feed.slice(0, 8).map(it => insightCard(it, { compact: true, actions: false })).join("") || `<p class="muted">暂无</p>`}</div>
          <p style="margin-top:12px"><a href="#/insights">查看全部洞察 →</a></p>
          ${snap.emerging.length ? `<h2 class="section">新词雷达</h2><p class="section-sub">近期相对频率飙升的术语；全新 = 有数据以来首次出现，回潮 = 基线期没有、更早出现过</p>
            <div class="card" style="padding:6px 14px"><table class="data"><thead><tr><th>术语</th><th>类型</th><th>近期</th><th>基线</th><th>倍数</th></tr></thead><tbody>
            ${snap.emerging.slice(0, 10).map(t => `<tr><td><a class="term" href="#/papers?q=${encodeURIComponent(t.term)}">${esc(t.term)}</a></td><td class="muted nowrap" title="${t.first_week ? `最早 ${t.first_week} 周` : ""}">${TERM_STATUS[t.status] || ""}</td><td class="num">${t.recent}</td><td class="num">${t.base}</td><td class="num">${t.lift.toFixed(1)}×</td></tr>`).join("")}
            </tbody></table></div>` : ""}
        </aside>
      </div>
      ${methodNote()}`;
    hydrateSparks($view);
  }

  function methodNote() {
    return `<section class="card method"><h4>方法：Jack Clark 在 2016 年做的事，自动化</h4>
      <ol>
        <li><b>每天抓取</b>：从 arXiv 拉取 ${S.snap.categories.map(c => c.id).join(" / ")} 的新论文；首次运行回填过去若干周的样本（每类每周取首尾各一半），并记录 arXiv 给出的真实周投稿量。</li>
        <li><b>整理成时间序列</b>：把"零散阅读"变成"每周占比"——每个信号是一条可编辑的正则，占比按各分类投稿量加权。</li>
        <li><b>持续提出洞察</b>：加速 / 回落、跨领域同步上升、渗透到更多领域、基座模型格局变化、新术语浮现、投稿量迁移；同时用数据给你自己的判断打分。</li>
      </ol>
      <p class="small muted" style="margin:8px 0 0">局限：基于标题与摘要的关键词匹配，不读全文；回填周为样本，近几周为全量。倍数是线索，不是结论——点进论文核对。</p></section>`;
  }

  function md(text) {
    // Minimal markdown: headings, bullets, bold, paragraphs.
    const lines = esc(text).split("\n"); let out = "", inList = false;
    for (const raw of lines) {
      const l = raw.replace(/\*\*(.+?)\*\*/g, "<b>$1</b>");
      if (/^\s*[-*]\s+/.test(l)) { if (!inList) { out += "<ul>"; inList = true; } out += `<li>${l.replace(/^\s*[-*]\s+/, "")}</li>`; continue; }
      if (/^\s*\d+\.\s+/.test(l)) { if (!inList) { out += "<ul>"; inList = true; } out += `<li>${l.replace(/^\s*/, "")}</li>`; continue; }
      if (inList) { out += "</ul>"; inList = false; }
      if (/^#{1,3}\s/.test(l)) out += `<h3>${l.replace(/^#+\s/, "")}</h3>`;
      else if (l.trim()) out += `<p>${l}</p>`;
    }
    return out + (inList ? "</ul>" : "");
  }

  // ---- timeline ----------------------------------------------------------
  async function timeline() {
    const snap = S.snap;
    const all = await api("/api/insights?limit=300&status=all");
    const byWeek = {};
    all.forEach(i => (byWeek[i.week] = byWeek[i.week] || []).push(i));
    const tl = [...snap.timeline].reverse();
    $view.innerHTML = `
      <div class="page-head"><div>
        <h1>时间线</h1>
        <p>把每周发生的事按时间排好：哪些曲线比自己过去 8 周跳得最高、哪些新词第一次成规模出现、当周最"踩在趋势上"的论文，以及那一周 Tern 生成的洞察。</p>
      </div></div>
      <section class="card chart-card">
        <div class="chart-tools"><div><h3>各领域周投稿量</h3><div class="sub">arXiv 官方计数（含交叉投稿）。投稿量是人力流向的代理变量。</div></div>
          <div class="seg" id="vol-mode"><button class="on" data-m="chart">图表</button><button data-m="table">表格</button></div></div>
        <div class="chart" id="vol-chart"></div>
      </section>
      <h2 class="section">逐周记录</h2><p class="section-sub">蓝点 = 当周产生了洞察。最新的在上。</p>
      <div class="tl">
        ${tl.map(w => {
          const ins = (byWeek[w.week] || []).sort((a, b) => b.score - a.score);
          return `<div class="tl-week ${ins.length ? "has-insight" : ""}">
            <div class="tl-date"><b>${Charts.weekRange(w.week)}</b><span class="num">${w.volume.toLocaleString()} 篇投稿</span>${w.sampled ? `<span class="sample-badge" title="该周为样本：${w.papers} 篇">样本</span>` : ""}</div>
            <div class="card tl-body">
              ${w.risers.length ? `<div class="tl-row"><span class="lbl">跳升</span><span class="vals">${w.risers.filter(r => r.lift > 1.05).slice(0, 4).map(r => `<a class="tag" href="#/signal/${r.slug}">${esc(r.name)} <span class="lift up">${r.lift.toFixed(2)}×</span></a>`).join("") || `<span class="muted small">无明显跳升</span>`}</span></div>` : ""}
              ${w.terms.length ? `<div class="tl-row"><span class="lbl">新词</span><span class="vals">${w.terms.map(t => `<a class="term" href="#/papers?q=${encodeURIComponent(t.term)}&week=${w.week}" title="${t.count} 篇 · ${t.lift.toFixed(1)}×">${esc(t.term)}</a>`).join("")}</span></div>` : ""}
              ${w.notable.length ? `<div class="tl-row"><span class="lbl">代表论文</span><span class="vals" style="display:block"><ul class="tl-papers">${w.notable.map(p => `<li><a href="${arxiv(p.id)}" target="_blank" rel="noopener">${esc(p.title)}</a><span class="sigs">${esc(p.signals.join(" · "))}</span></li>`).join("")}</ul></span></div>` : ""}
              ${ins.length ? `<div class="tl-ins">${ins.slice(0, 5).map(i => `<div><span class="kind ${i.kind}"><i></i>${KIND[i.kind]}</span> ${esc(i.title)}</div>`).join("")}${ins.length > 5 ? `<div class="small muted">另有 ${ins.length - 5} 条 · <a href="#/insights">查看</a></div>` : ""}</div>` : ""}
            </div></div>`;
        }).join("")}
      </div>`;
    const volChart = document.getElementById("vol-chart");
    const drawVol = mode => {
      if (mode === "table") {
        volChart.innerHTML = `<div class="table-wrap"><table class="data"><thead><tr><th>周</th>${snap.categories.map(c => `<th>${c.id}</th>`).join("")}</tr></thead><tbody>
          ${[...snap.weeks].map((w, i) => `<tr><td>${Charts.weekRange(w)}</td>${snap.categories.map(c => `<td class="num">${snap.volume[c.id][i] ?? "—"}</td>`).join("")}</tr>`).reverse().join("")}</tbody></table></div>`;
      } else {
        Charts.lineChart(volChart, {
          labels: snap.weeks, height: 260, yFmt: v => v >= 1000 ? (v / 1000).toFixed(1) + "k" : v.toFixed(0),
          series: snap.categories.map(c => ({ name: `${c.name} ${c.id}`, values: snap.volume[c.id], color: catColor(c.id) })),
          directLabels: false, aria: "各领域周投稿量折线图",
        });
      }
    };
    drawVol("chart");
    segToggle("vol-mode", drawVol);
  }

  function segToggle(id, fn) {
    const seg = document.getElementById(id);
    seg.addEventListener("click", e => {
      const b = e.target.closest("button"); if (!b) return;
      seg.querySelectorAll("button").forEach(x => x.classList.toggle("on", x === b));
      fn(b.dataset.m);
    });
  }

  // ---- insights ----------------------------------------------------------
  async function insights(r) {
    const kind = r.qs.kind || "";
    const status = r.qs.status || "active";
    const all = await api(`/api/insights?limit=300&status=${status}`);
    const counts = {};
    all.forEach(i => counts[i.kind] = (counts[i.kind] || 0) + 1);
    const list = kind ? all.filter(i => i.kind === kind) : all;
    const q = (k, s) => `#/insights?${new URLSearchParams({ ...(k ? { kind: k } : {}), ...(s && s !== "active" ? { status: s } : {}) })}`;
    $view.innerHTML = `
      <div class="page-head"><div>
        <h1>洞察</h1>
        <p>每次抓取后，七个探测器在全部时间序列上重跑一遍。卡片按周归档——它是一份自动写成的研究日志。收藏你相信的，忽略噪声。</p>
      </div>
      <div class="seg"><a class="btn ${status === "active" ? "primary" : ""}" href="${q(kind, "active")}">进行中</a> <a class="btn ${status === "starred" ? "primary" : ""}" href="${q(kind, "starred")}">已收藏</a> <a class="btn ${status === "dismissed" ? "primary" : ""}" href="${q(kind, "dismissed")}">已忽略</a></div></div>
      <div class="chips">
        <a class="chip ${!kind ? "on" : ""}" href="${q("", status)}">全部<span class="c">${all.length}</span></a>
        ${Object.keys(KIND).filter(k => counts[k]).map(k => `<a class="chip ${kind === k ? "on" : ""}" href="${q(k, status)}">${KIND[k]}<span class="c">${counts[k]}</span></a>`).join("")}
      </div>
      <div class="feed" id="feed">${list.map(it => insightCard(it)).join("") || `<div class="card empty"><p>这里还没有洞察。</p></div>`}</div>`;
    hydrateSparks($view);
    bindInsightActions(document.getElementById("feed"), () => insights(route()));
  }

  // ---- signals -----------------------------------------------------------
  async function signalsView(r) {
    const snap = S.snap;
    let slug = r.slug;
    if (r.name === "signals") {
      slug = Object.entries(snap.stats).sort((a, b) => (b[1].lift || 0) - (a[1].lift || 0))[0][0];
    }
    const groups = {};
    snap.signals.forEach(s => (groups[s.grp] = groups[s.grp] || []).push(s));
    $view.innerHTML = `<div class="sig-layout">
      <nav class="card sig-list">
        <a href="#/signals/new" class="rw ${r.name === "signals-new" ? "on" : ""}"><b>＋ 新建信号</b></a>
        ${Object.entries(groups).map(([g, list]) => `<h5>${esc(g)}</h5>${list.map(s => `<a href="#/signal/${s.slug}" class="${s.slug === slug && r.name !== "signals-new" ? "on" : ""}"><span>${esc(s.name)}</span>${liftBadge(snap.stats[s.slug])}</a>`).join("")}`).join("")}
      </nav>
      <div id="sig-detail"></div></div>`;
    const box = document.getElementById("sig-detail");
    if (r.name === "signals-new") return newSignalForm(box);
    const sig = sigBy(slug);
    if (!sig) { box.innerHTML = `<div class="card empty">信号不存在</div>`; return; }
    const st = snap.stats[slug], ser = snap.series[slug];
    const [papers, ins] = await Promise.all([api(`/api/papers?signal=${slug}&limit=12`), api(`/api/insights?subject=${slug}&status=all&limit=20`)]);
    const catRows = snap.categories.map(c => ({ c, v: st.cat_lift[c.id] }));
    box.innerHTML = `
      <div class="sig-head">
        <div class="eyebrow">${esc(sig.grp)}${sig.custom ? " · 自定义" : ""}</div>
        <h1>${esc(sig.name)}</h1>
        <p class="muted" style="margin:4px 0 0">${esc(sig.description)}</p>
        <div class="pattern">/${esc(sig.pattern)}/i</div>
      </div>
      <div class="kpis">
        <div class="k"><div class="l">近 ${snap.windows.recent} 周占比</div><div class="v num">${pct(st.recent_share, 2)}</div></div>
        <div class="k"><div class="l">此前 ${snap.windows.base} 周</div><div class="v num">${pct(st.base_share, 2)}</div></div>
        <div class="k"><div class="l">变化</div><div class="v">${liftBadge(st)}</div></div>
        <div class="k"><div class="l">翻倍时间</div><div class="v num">${st.doubling_weeks && st.doubling_weeks < 104 ? st.doubling_weeks.toFixed(0) + " 周" : "—"}</div></div>
        <div class="k"><div class="l">渗透领域</div><div class="v num">${st.penetration} / ${snap.categories.length}</div></div>
      </div>
      <div class="stack">
        <section class="card chart-card"><h3>每周提及占比（全部领域，按投稿量加权）</h3>
          <div class="sub">悬停查看每周数值与篇数。底纹为近期窗口。</div>
          <div class="chart" id="c-all"></div></section>
        <section class="card chart-card">
          <div class="chart-tools"><div><h3>分领域拆解</h3><div class="sub">多个独立领域同时上升，比单一领域的热点更说明问题。</div></div>
          <div class="seg" id="cat-mode"><button class="on" data-m="chart">图表</button><button data-m="table">表格</button></div></div>
          <div class="chart" id="c-cat"></div></section>
        <section class="card chart-card"><h3>各领域近期 vs 基线</h3>
          <div class="table-wrap"><table class="data"><thead><tr><th>领域</th><th>近期占比</th><th>基线占比</th><th>倍数</th><th>近期篇数</th></tr></thead><tbody>
          ${catRows.map(({ c, v }) => `<tr><td>${c.name} <span class="muted">${c.id}</span></td><td class="num">${pct(v.recent, 2)}</td><td class="num">${pct(v.base, 2)}</td><td>${v.lift ? liftBadge({ lift: v.lift }) : "—"}</td><td class="num">${v.count}</td></tr>`).join("")}
          </tbody></table></div></section>
        ${ins.length ? `<section><h2 class="section" style="margin-top:8px">关于它的洞察</h2><div class="feed">${ins.map(i => insightCard(i, { compact: true, actions: false })).join("")}</div></section>` : ""}
        <section><h2 class="section" style="margin-top:8px">最新论文 <span class="muted small">共 ${papers.total.toLocaleString()} 篇 · <a href="#/papers?signal=${slug}">全部</a></span></h2>
          <div>${papers.items.map(paperRow).join("")}</div></section>
        ${sig.custom ? `<p class="rw"><button class="btn" id="del-sig">删除这个自定义信号</button></p>` : ""}
      </div>`;
    Charts.lineChart(document.getElementById("c-all"), {
      labels: snap.weeks, height: 240, area: true, yFmt: fmtShare,
      series: [{ name: sig.name, values: ser.share, color: "var(--s1)" }],
      window: { from: recentFrom(), label: "近期" }, aria: `${sig.name} 每周占比`,
      tipExtra: i => `<div class="tt-r"><span class="muted">命中篇数</span><b>${ser.count[i]}</b></div>`,
    });
    const catBox = document.getElementById("c-cat");
    const drawCat = mode => {
      if (mode === "table") {
        catBox.innerHTML = `<div class="table-wrap"><table class="data"><thead><tr><th>周</th>${snap.categories.map(c => `<th>${c.id}</th>`).join("")}</tr></thead><tbody>
          ${snap.weeks.map((w, i) => `<tr><td>${Charts.weekRange(w)}</td>${snap.categories.map(c => `<td class="num">${ser.by_cat[c.id][i] == null ? "—" : fmtShare(ser.by_cat[c.id][i])}</td>`).join("")}</tr>`).reverse().join("")}</tbody></table></div>`;
      } else {
        Charts.lineChart(catBox, {
          labels: snap.weeks, height: 260, yFmt: fmtShare, directLabels: false,
          series: snap.categories.map(c => ({ name: `${c.name} ${c.id}`, values: ser.by_cat[c.id], color: catColor(c.id) })),
          window: { from: recentFrom() }, aria: `${sig.name} 分领域占比`,
        });
      }
    };
    drawCat("chart");
    segToggle("cat-mode", drawCat);
    const del = document.getElementById("del-sig");
    if (del) del.onclick = async () => { await api(`/api/signals/${slug}`, { method: "DELETE" }); await waitAnalysis(); location.hash = "#/signals"; };
  }

  // Edits re-analyze synchronously on the server, so a fresh snapshot is ready on return.
  async function waitAnalysis() { await loadSnap(); }

  function newSignalForm(box) {
    box.innerHTML = `
      <div class="sig-head"><div class="eyebrow">自定义</div><h1>新建信号</h1>
      <p class="muted" style="margin:4px 0 0">写下你想追踪的东西——一条对标题和摘要生效的正则（不区分大小写）。保存后会对全部历史论文重新打标，生成完整时间序列。</p></div>
      <form class="card form" id="sig-form" style="margin-top:16px">
        <div class="row">
          <label>名称<input type="text" name="name" required placeholder="例如：Speculative decoding"></label>
          <label>分组<input type="text" name="grp" value="我的信号"></label>
        </div>
        <label>正则表达式<input type="text" name="pattern" required placeholder="speculative decoding|draft model" style="font-family:var(--mono)"></label>
        <div class="preview" id="pv">输入正则后，这里会显示最近 3000 篇论文中的命中情况。</div>
        <label>说明<input type="text" name="description" placeholder="为什么值得追踪？"></label>
        <div><button class="btn primary" type="submit">保存并回算历史</button> <span class="err" id="sig-err"></span></div>
      </form>`;
    const f = document.getElementById("sig-form"), pv = document.getElementById("pv");
    let t;
    f.pattern.addEventListener("input", () => {
      clearTimeout(t);
      t = setTimeout(async () => {
        const p = f.pattern.value.trim(); if (!p) return;
        const res = await api(`/api/signal-preview?pattern=${encodeURIComponent(p)}`);
        pv.innerHTML = res.error ? `<span class="err">正则无效：${esc(res.error)}</span>`
          : `最近 ${res.sample} 篇中命中 <b class="num">${res.matches}</b> 篇（${pct(res.matches / Math.max(1, res.sample), 2)}）${res.examples.length ? `<ul>${res.examples.map(e => `<li>${esc(e.title)}</li>`).join("")}</ul>` : ""}`;
      }, 300);
    });
    f.addEventListener("submit", async e => {
      e.preventDefault();
      const btn = f.querySelector("button"); btn.disabled = true; btn.textContent = "回算中…";
      try {
        const res = await api("/api/signals", { body: Object.fromEntries(new FormData(f)) });
        await waitAnalysis();
        location.hash = `#/signal/${res.slug}`;
      } catch (err) {
        document.getElementById("sig-err").textContent = err.message; btn.disabled = false; btn.textContent = "保存并回算历史";
      }
    });
  }

  // ---- theses ------------------------------------------------------------
  function theses() {
    const snap = S.snap;
    const list = snap.theses || [];
    $view.innerHTML = `
      <div class="page-head"><div>
        <h1>我的判断</h1>
        <p>Jack Clark 最难的一步不是画图，而是<b>相信自己的研究结论</b>。把你的判断写下来，绑定到信号上，Tern 每次抓取后都会用数据重新给它打分——支持、相反、或尚无变化。</p>
      </div></div>
      <div class="stack">
        ${list.map(t => {
          const cls = t.verdict === "证据支持" ? "ok" : t.verdict === "证据相反" ? "bad" : "flat";
          return `<div class="card thesis-card">
            <div><blockquote>“${esc(t.text)}”</blockquote>
              <div class="meta">预期${t.stance === "up" ? "上升" : "下降"} · ${t.slugs.map(s => `<a href="#/signal/${s}">${esc(sigBy(s)?.name || s)}</a>`).join("、")} · 写于 ${t.created_at.slice(0, 10)}
                <span class="rw">· <a href="#" data-del="${t.id}">删除</a></span></div>
              <div style="margin-top:8px"><span class="verdict ${cls}">${cls === "ok" ? "✓" : cls === "bad" ? "✕" : "○"} ${t.verdict}</span>
                <span class="muted small">${t.lift ? `关联信号 ${t.lift.toFixed(2)}×` : ""}</span></div></div>
            <svg data-spark="${t.slugs[0]}" style="width:100%;height:54px"></svg></div>`;
        }).join("") || ""}
        <form class="card form rw" id="th-form">
          <h3 style="margin:0;font-size:15px">写下一个新判断</h3>
          <label>判断<textarea name="text" rows="2" required placeholder="例如：未来一年，智能体会从语言领域扩散到机器人与视觉，成为跨领域的默认范式。"></textarea></label>
          <label>证据信号（可多选）<div class="checks">${snap.signals.map(s => `<label><input type="checkbox" name="slugs" value="${s.slug}">${esc(s.name)}</label>`).join("")}</div></label>
          <div class="seg" id="stance"><button type="button" class="on" data-m="up">我预期上升</button><button type="button" data-m="down">我预期下降</button></div>
          <div><button class="btn primary" type="submit">记录并评分</button> <span class="err" id="th-err"></span></div>
        </form>
      </div>`;
    hydrateSparks($view);
    let stance = "up";
    segToggle("stance", m => stance = m);
    const f = document.getElementById("th-form");
    f.addEventListener("submit", async e => {
      e.preventDefault();
      const slugs = [...f.querySelectorAll("input[name=slugs]:checked")].map(i => i.value);
      try {
        await api("/api/theses", { body: { text: f.text.value, slugs, stance } });
        await waitAnalysis(); theses();
      } catch (err) { document.getElementById("th-err").textContent = err.message; }
    });
    $view.querySelectorAll("[data-del]").forEach(a => a.onclick = async e => {
      e.preventDefault(); await api(`/api/theses/${a.dataset.del}`, { method: "DELETE" }); await waitAnalysis(); theses();
    });
  }

  // ---- papers ------------------------------------------------------------
  function paperRow(p) {
    const authors = p.authors.slice(0, 4).join(", ") + (p.authors.length > 4 ? " 等" : "");
    return `<article class="paper">
      <h3><a href="${arxiv(p.id)}" target="_blank" rel="noopener">${esc(p.title)}</a></h3>
      <div class="meta">${esc(authors)} · <span class="num">${p.id}</span> · ${p.primary_cat} · ${p.published.slice(0, 10)}</div>
      <p>${esc(p.abstract)}</p>
      ${p.signals.length ? `<div class="sig-tags">${p.signals.map(s => `<a href="#/signal/${s}">${esc(sigBy(s)?.name || s)}</a>`).join("")}</div>` : ""}
    </article>`;
  }

  async function papers(r) {
    const qs = r.qs;
    const sigs = S.snap?.signals || [];
    const cats = S.snap?.categories || S.status?.categories || [];
    $view.innerHTML = `
      <div class="page-head"><div><h1>论文</h1><p>原始材料。所有曲线和洞察都能追溯到这里的具体论文。</p></div></div>
      <form class="search" id="pf">
        <input type="search" name="q" placeholder="搜索标题或摘要…" value="${esc(qs.q || "")}">
        <select name="signal"><option value="">全部信号</option>${sigs.map(s => `<option value="${s.slug}" ${qs.signal === s.slug ? "selected" : ""}>${esc(s.name)}</option>`).join("")}</select>
        <select name="cat"><option value="">全部领域</option>${cats.map(c => `<option value="${c.id}" ${qs.cat === c.id ? "selected" : ""}>${c.name} ${c.id}</option>`).join("")}</select>
        ${qs.week ? `<input type="hidden" name="week" value="${esc(qs.week)}">` : ""}
      </form>
      <div class="muted small" id="pcount"></div><div id="plist"></div>
      <p><button class="btn" id="more" hidden>加载更多</button></p>`;
    const f = document.getElementById("pf");
    let offset = 0;
    const load = async (reset) => {
      if (reset) offset = 0;
      const params = new URLSearchParams(Object.entries(Object.fromEntries(new FormData(f))).filter(([, v]) => v));
      params.set("offset", offset); params.set("limit", 30);
      const res = await api(`/api/papers?${params}`);
      const list = document.getElementById("plist");
      if (reset) list.innerHTML = "";
      list.insertAdjacentHTML("beforeend", res.items.map(paperRow).join(""));
      offset += res.items.length;
      document.getElementById("pcount").textContent = `共 ${res.total.toLocaleString()} 篇${qs.week && f.week ? ` · ${Charts.weekRange(qs.week)} 当周` : ""}`;
      document.getElementById("more").hidden = offset >= res.total;
    };
    let t;
    f.addEventListener("input", () => { clearTimeout(t); t = setTimeout(() => load(true), 250); });
    f.addEventListener("submit", e => { e.preventDefault(); load(true); });
    document.getElementById("more").onclick = () => load(false);
    load(true);
  }

  // ---- boot --------------------------------------------------------------
  (async () => {
    try { S.status = await api("/api/status"); S.lastJob = S.status.job.job; renderOps(); } catch (e) { }
    await loadSnap();
    render();
    poll();
  })();
})();
