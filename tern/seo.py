"""Server-rendered pages for crawlers and first paint, plus robots.txt and sitemap.xml.

Every SPA route has a real path. The server returns the same HTML shell the SPA uses,
with per-page <head> tags and readable content inside <main id="view">; the SPA then
takes over and re-renders that element with the interactive view.
"""

import html
import json
import re
from urllib.parse import quote, urlencode

from . import config, db, views

SITE = "Tern"
TAGLINE = "从所有人都能看到的论文里，找出还没被意识到的重要性"
ARXIV_ABS = "https://arxiv.org/abs/"
e = html.escape


class Page:
    def __init__(self, title, description, body, canonical=None, status=200, noindex=False, kind="website", ld=None):
        self.title, self.description, self.body = title, description, body
        self.canonical, self.status, self.noindex, self.kind, self.ld = canonical, status, noindex, kind, ld


def base_url(host):
    if config.PUBLIC_URL:
        return config.PUBLIC_URL.rstrip("/")
    host = host or f"127.0.0.1:{config.PORT}"
    local = re.match(r"^(localhost|127\.|0\.0\.0\.0|\[::1\])", host)
    return f"{'http' if local else 'https'}://{host}"


# ---- small HTML helpers ----------------------------------------------------
def _pct(x):
    return "—" if x is None else (f"{x * 100:.2f}%" if x < 0.01 else f"{x * 100:.1f}%")


def _lift(st):
    if st.get("new"):
        return "新出现"
    return "—" if st.get("lift") is None else f"{st['lift']:.2f}×"


def _head(eyebrow, h1, lead=""):
    return (f'<div class="page-head"><div>{f"<div class=eyebrow>{e(eyebrow)}</div>" if eyebrow else ""}'
            f"<h1>{e(h1)}</h1>{f'<p>{e(lead)}</p>' if lead else ''}</div></div>")


def _insight_item(it):
    return (f'<article class="card insight compact"><div class="i-meta"><span class="kind {e(it["kind"])}"><i></i>'
            f'{e(views.KIND_NAMES.get(it["kind"], it["kind"]))}</span><span>{e(views.week_range(it["week"]))}</span></div>'
            f'<h3><a href="{e(it["path"])}">{e(it["title"])}</a></h3><p>{e(it["body"])}</p></article>')


def _paper_li(p):
    return (f'<li><a href="{ARXIV_ABS}{e(p["id"])}" rel="noopener">{e(p["title"])}</a> '
            f'<span class="muted small">{e(p.get("primary_cat") or "")} · {e((p.get("published") or "")[:10])}</span></li>')


def _sections(sections):
    out = []
    for s in sections:
        out.append(f'<h2 class="section">{e(s["h"])}</h2>')
        for p in s.get("p", []):
            out.append(f"<p>{e(p)}</p>")
        if s.get("items"):
            out.append('<ul class="brief-list">' + "".join(
                f'<li><a href="{e(i["href"])}"{" rel=noopener" if i.get("external") else ""}>{e(i["text"])}</a>'
                f'{_note(i.get("note"))}</li>'
                for i in s["items"]) + "</ul>")
        if s.get("md"):
            out.append("".join(f"<p>{e(line)}</p>" for line in s["md"].split("\n") if line.strip()))
    return "".join(out)


def _note(text):
    return f'<div class="muted">{e(text)}</div>' if text else ""


def _x(v):
    return "—" if v is None else f"{v:.2f}×"


def _snap():
    return db.kv_get("snapshot", {"ready": False})


# ---- pages -------------------------------------------------------------------
def page_radar(qs):
    snap = _snap()
    if not snap.get("ready"):
        return Page(f"{SITE} · AI 研究趋势雷达", TAGLINE, _head("", "数据准备中", TAGLINE))
    items = views.insights(week=snap["analysis_week"], limit=40)
    hero, feed = views.front_page(items)
    rng = views.week_range(snap["analysis_week"])
    h1 = hero["title"] if hero else "本周没有显著变化"
    body = [_head(f"研究简报 · {rng}", h1, hero["body"] if hero else TAGLINE)]
    body.append(f'<p><a href="/brief/{snap["analysis_week"]}">阅读本周周报 →</a></p>')
    if feed:
        body.append('<h2 class="section">本周洞察</h2><div class="feed">' + "".join(_insight_item(i) for i in feed[:8]) + "</div>")
    body.append('<h2 class="section">信号</h2><ul class="brief-list">' + "".join(
        f'<li><a href="/signal/{e(s["slug"])}">{e(s["name"])}</a> <span class="muted">'
        f'{_pct(snap["stats"][s["slug"]]["recent_share"])} · {_lift(snap["stats"][s["slug"]])}</span></li>'
        for s in snap["signals"]) + "</ul>")
    if snap.get("emerging"):
        body.append('<h2 class="section">新词雷达</h2><ul class="brief-list">' + "".join(
            f'<li><a href="/papers?q={quote(t["term"])}">{e(t["term"])}</a> <span class="muted">近期 {t["recent"]} 篇 · {t["lift"]:.1f}×</span></li>'
            for t in snap["emerging"][:10]) + "</ul>")
    desc = f"{rng} AI 研究趋势：{h1}。基于 arXiv 六个 AI 分类每天的新论文，自动追踪信号占比与跨领域变化。"
    return Page(f"{SITE} · AI 研究趋势雷达 · {rng}", desc, "".join(body), canonical="/")


def page_timeline(qs):
    snap = _snap()
    briefs = {b["week"]: b for b in views.brief_list()}
    weeks = list(reversed(snap.get("timeline", [])))
    body = [_head("", "时间线", "每周发生的事按时间排好：哪些曲线比自己过去 8 周跳得最高、哪些新词第一次成规模出现，以及代表论文。")]
    body.append('<ul class="brief-list">' + "".join(
        f'<li><a href="/brief/{w["week"]}">{e(briefs[w["week"]]["title"] if w["week"] in briefs else views.week_range(w["week"]))}</a>'
        f' <span class="muted">{w["volume"]:,} 篇投稿</span></li>' for w in weeks) + "</ul>")
    return Page(f"AI 研究时间线 · {SITE}", "逐周记录 arXiv AI 论文里跳升的方向、新出现的说法和代表论文。", "".join(body), canonical="/timeline")


def page_briefs(qs):
    rows = views.brief_list()
    body = [_head("", "研究周报", "每周一篇，基于当周 arXiv 论文数据自动写成：跳升最快的方向、新出现的说法、值得读的论文。")]
    body += ['<div class="feed">'] + [f'<article class="card insight"><h3><a href="/brief/{r["week"]}">{e(r["title"])}</a></h3><p>{e(r["summary"])}</p></article>' for r in rows] + ["</div>"]
    return Page(f"AI 研究周报 · {SITE}", "每周一篇 AI 研究趋势简报，基于 arXiv 论文数据。", "".join(body), canonical="/briefs")


def page_brief(week):
    b = views.brief(week)
    if not b:
        return None
    nav = []
    if b["prev"]:
        nav.append(f'<a href="/brief/{b["prev"]}">← 上一周</a>')
    if b["next"]:
        nav.append(f'<a href="/brief/{b["next"]}">下一周 →</a>')
    body = (f'<article class="brief">{_head("研究周报 · " + views.week_range(week), b["title"].split("：", 1)[-1], b["summary"])}'
            f'{_sections(b["body"]["sections"])}<p class="brief-nav">{" · ".join(nav)}</p></article>')
    ld = {"@context": "https://schema.org", "@type": "Article", "headline": b["title"], "description": b["summary"],
          "datePublished": b["generated_at"], "dateModified": b["updated_at"], "inLanguage": "zh-CN",
          "author": {"@type": "Organization", "name": SITE}}
    return Page(b["title"], b["summary"], body, canonical=f"/brief/{week}", kind="article", ld=ld)


def page_insights(qs):
    items = views.insights(limit=100)
    body = [_head("", "洞察", "每次抓取后，七个探测器在全部时间序列上重跑一遍，生成按周归档的洞察卡片。")]
    body.append('<div class="feed">' + "".join(_insight_item(i) for i in items) + "</div>")
    filtered = any(qs.get(k) for k in ("kind", "status"))
    return Page(f"AI 研究洞察 · {SITE}", "加速、回落、跨领域同步、渗透、新词：从 arXiv 论文时间序列自动生成的研究洞察。",
                "".join(body), canonical="/insights", noindex=filtered)


def page_insight(id_):
    rows = views.insights(status="all", ids=[id_], limit=1)
    if not rows:
        return None
    it = rows[0]
    ev = it["evidence"]
    body = [_head(f"{views.KIND_NAMES.get(it['kind'], it['kind'])} · {views.week_range(it['week'])}", it["title"], it["body"])]
    if ev.get("slug") or ev.get("slugs"):
        slugs = [ev["slug"]] if ev.get("slug") else ev["slugs"]
        body.append('<h2 class="section">相关信号</h2><ul class="brief-list">' + "".join(
            f'<li><a href="/signal/{e(s)}">{e(s)}</a></li>' for s in slugs) + "</ul>")
    if ev.get("term"):
        body.append(f'<p><a href="/papers?q={quote(ev["term"])}">查看使用“{e(ev["term"])}”的论文 →</a></p>')
    if ev.get("papers"):
        body.append('<h2 class="section">代表论文</h2><ul class="brief-list">' + "".join(_paper_li(p) for p in ev["papers"]) + "</ul>")
    others = [o for o in views.insights(limit=50) if o["subject"] == it["subject"] and o["id"] != it["id"]]
    if others:
        body.append('<h2 class="section">同一主题的其他洞察</h2><div class="feed">' + "".join(_insight_item(o) for o in others) + "</div>")
    body.append(f'<p><a href="/brief/{it["week"]}">这一周的研究周报 →</a></p>')
    return Page(f"{it['title']} · {SITE}", it["body"][:155], "".join(body), canonical=it["path"], kind="article",
                noindex=it["status"] == "dismissed")


def page_signals(qs):
    snap = _snap()
    groups = {}
    for s in snap.get("signals", []):
        groups.setdefault(s["grp"], []).append(s)
    body = [_head("", "信号", "每个信号是一条作用于论文标题和摘要的规则，它的每周论文占比就是一条时间序列。")]
    for g, lst in groups.items():
        body.append(f'<h2 class="section">{e(g)}</h2><ul class="brief-list">' + "".join(
            f'<li><a href="/signal/{e(s["slug"])}">{e(s["name"])}</a> <span class="muted">{e(s["description"])} · '
            f'{_pct(snap["stats"][s["slug"]]["recent_share"])} · {_lift(snap["stats"][s["slug"]])}</span></li>' for s in lst) + "</ul>")
    return Page(f"AI 研究信号 · {SITE}", "Nvidia GPU、智能体、推理、扩散模型、基座模型等研究信号在 arXiv 论文中的占比走势。",
                "".join(body), canonical="/signals")


def page_signal(slug):
    snap = _snap()
    sig = next((s for s in snap.get("signals", []) if s["slug"] == slug), None)
    if not sig:
        return None
    st = snap["stats"][slug]
    cats = dict((c["id"], c["name"]) for c in snap["categories"])
    lead = (f"{sig['description']}。近 {snap['windows']['recent']} 周占全部论文的 {_pct(st['recent_share'])}，"
            f"此前 {snap['windows']['base']} 周为 {_pct(st['base_share'])}（{_lift(st)}）"
            + (f"，按近 12 周斜率约每 {st['doubling_weeks']:.0f} 周翻一番" if st.get("doubling_weeks") and st["doubling_weeks"] > 0 else "") + "。")
    body = [_head(sig["grp"], sig["name"], lead)]
    body.append('<h2 class="section">分领域</h2><ul class="brief-list">' + "".join(
        f'<li>{e(cats.get(c, c))}（{e(c)}）<span class="muted"> 近期 {_pct(v["recent"])} · 基线 {_pct(v["base"])} · '
        f'{_x(v.get("lift"))}</span></li>'
        for c, v in st["cat_lift"].items()) + "</ul>")
    papers = db.q("SELECT p.id, p.title, p.primary_cat, p.published FROM papers p JOIN paper_signal ps ON ps.paper_id=p.id "
                  "WHERE ps.slug=? ORDER BY p.published DESC LIMIT 12", (slug,))
    if papers:
        body.append('<h2 class="section">最新论文</h2><ul class="brief-list">' + "".join(_paper_li(p) for p in papers) + "</ul>")
    related = [i for i in views.insights(limit=200) if i["subject"] == slug]
    if related:
        body.append('<h2 class="section">相关洞察</h2><div class="feed">' + "".join(_insight_item(i) for i in related) + "</div>")
    return Page(f"{sig['name']} 在 AI 论文中的占比走势 · {SITE}", lead[:155], "".join(body), canonical=f"/signal/{slug}")


def page_theses(qs):
    snap = _snap()
    body = [_head("", "我的判断", "把判断写下来，绑定到信号上，每次抓取后用数据重新打分。")]
    body.append('<ul class="brief-list">' + "".join(
        f'<li>“{e(t["text"])}” <span class="muted">{e(t.get("verdict") or "")}'
        f'{" · 关联信号 " + _x(t["lift"]) if t.get("lift") else ""}</span></li>'
        for t in snap.get("theses", [])) + "</ul>")
    return Page(f"研究判断 · {SITE}", "用 arXiv 论文数据持续检验的研究判断。", "".join(body), canonical="/theses")


def page_papers(qs):
    papers = db.q("SELECT id, title, primary_cat, published FROM papers ORDER BY published DESC LIMIT 30")
    body = [_head("", "论文", "原始材料：所有曲线和洞察都能追溯到这里的具体论文。"),
            '<ul class="brief-list">' + "".join(_paper_li(p) for p in papers) + "</ul>"]
    return Page(f"最新 AI 论文 · {SITE}", "Tern 收录的最新 arXiv AI 论文。", "".join(body), canonical="/papers",
                noindex=bool(qs))


def page_not_found():
    return Page(f"页面不存在 · {SITE}", TAGLINE, _head("", "页面不存在", "这个地址没有内容。"), status=404, noindex=True)


def route(path, qs):
    """Return a Page for an app route, or None when the path is not an app route."""
    path = path.rstrip("/") or "/"
    if path in ("/", "/radar"):
        return page_radar(qs)
    simple = {"/timeline": page_timeline, "/briefs": page_briefs, "/insights": page_insights,
              "/signals": page_signals, "/theses": page_theses, "/papers": page_papers}
    if path in simple:
        return simple[path](qs)
    if path == "/signals/new":
        return Page(f"新建信号 · {SITE}", TAGLINE, _head("", "新建信号"), noindex=True)
    m = re.fullmatch(r"/brief/(\d{4}-\d{2}-\d{2})", path)
    if m:
        return page_brief(m.group(1)) or page_not_found()
    m = re.fullmatch(r"/insight/(\d+)(?:-[a-z0-9-]*)?", path)
    if m:
        return page_insight(int(m.group(1))) or page_not_found()
    m = re.fullmatch(r"/signal/([\w\-]+)", path)
    if m:
        return page_signal(m.group(1)) or page_not_found()
    return None


def render(page, shell, base):
    """Fill the SPA shell with this page's head tags and server-rendered content."""
    canon = base + (page.canonical or "/")
    head = [f"<title>{e(page.title)}</title>",
            f'<meta name="description" content="{e(page.description)}">',
            f'<link rel="canonical" href="{e(canon)}">',
            f'<meta property="og:site_name" content="{SITE}">',
            f'<meta property="og:type" content="{page.kind}">',
            f'<meta property="og:title" content="{e(page.title)}">',
            f'<meta property="og:description" content="{e(page.description)}">',
            f'<meta property="og:url" content="{e(canon)}">',
            '<meta name="twitter:card" content="summary">',
            '<link rel="alternate" type="application/rss+xml" title="Tern 研究周报" href="/briefs.xml">']
    if page.noindex:
        head.append('<meta name="robots" content="noindex">')
    if page.ld:
        head.append(f'<script type="application/ld+json">{json.dumps(page.ld, ensure_ascii=False).replace("</", "<\\/")}</script>')
    out = re.sub(r"<title>.*?</title>", lambda _: "\n".join(head), shell, count=1, flags=re.S)
    return out.replace('<main id="view" class="view"></main>', f'<main id="view" class="view">{page.body}</main>', 1)


# ---- robots / sitemap / feed ---------------------------------------------------
def robots(base):
    return (f"User-agent: *\nAllow: /\nDisallow: /api/\nDisallow: /signals/new\n\nSitemap: {base}/sitemap.xml\n")


def sitemap(base):
    snap = _snap()
    gen = (snap.get("generated_at") or "")[:10]
    urls = [("/", gen), ("/briefs", gen), ("/timeline", gen), ("/insights", gen), ("/signals", gen), ("/theses", gen), ("/papers", gen)]
    urls += [(f"/brief/{b['week']}", b["updated_at"][:10]) for b in views.brief_list()]
    urls += [(f"/signal/{s['slug']}", gen) for s in snap.get("signals", [])]
    urls += [(i["path"], i["updated_at"][:10]) for i in views.insights(limit=1000)]
    body = "".join(f"<url><loc>{e(base + u)}</loc>{f'<lastmod>{d}</lastmod>' if d else ''}</url>" for u, d in urls)
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</urlset>\n'


def feed(base):
    items = "".join(
        f"<item><title>{e(b['title'])}</title><link>{e(base)}/brief/{b['week']}</link><guid>{e(base)}/brief/{b['week']}</guid>"
        f"<description>{e(b['summary'])}</description></item>" for b in views.brief_list()[:20])
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0"><channel><title>Tern 研究周报</title>'
            f"<link>{e(base)}/briefs</link><description>{e(TAGLINE)}</description>{items}</channel></rss>\n")
