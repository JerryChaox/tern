"""Weekly research briefs: one readable article per completed week, stored in SQLite.

Built from the same weekly timeline the UI shows (risers vs the trailing 8 weeks,
new phrases, notable papers), plus that week's insight cards and, when present, the
Claude memo. A row is rewritten only when its content changes, so `updated_at`
(used as the sitemap's lastmod) moves only on real edits.
"""

import json
from urllib.parse import quote

from . import db, views
from .signals import now

ARXIV_ABS = "https://arxiv.org/abs/"


def _pct(x):
    return f"{x * 100:.2f}%" if x < 0.01 else f"{x * 100:.1f}%"


def build(entry, prev_entry, week_insights, memo):
    w = entry["week"]
    rng = views.week_range(w)
    risers = [r for r in entry["risers"] if r["lift"] > 1.05][:5]
    terms = entry["terms"][:6]
    if not (risers or terms or entry["notable"] or week_insights):
        return None  # early weeks without a trailing baseline have nothing to report
    hero, _ = views.front_page(week_insights)

    if hero:
        headline = hero["title"]
    elif risers:
        headline = f"{risers[0]['name']} 占比跳升 {risers[0]['lift']:.1f}×"
    else:
        headline = "各方向平稳"
    title = f"AI 研究周报 · {rng}：{headline}"

    overview = [f"{rng}，Tern 跟踪的 6 个 arXiv AI 分类共有 {entry['volume']:,} 篇投稿"
                + (f"（比上周{'增加' if entry['volume'] >= prev_entry['volume'] else '减少'} "
                   f"{abs(entry['volume'] / prev_entry['volume'] - 1) * 100:.0f}%）" if prev_entry and prev_entry["volume"] else "")
                + f"，其中 {entry['papers']:,} 篇进入了分析"
                + ("（这一周是抽样数据，占比可靠，绝对数以 arXiv 官方计数为准）。" if entry["sampled"] else "。")]
    if risers:
        overview.append("相对各自过去 8 周的平均水平，涨得最快的是 "
                        + "、".join(f"{r['name']}（{r['lift']:.1f}×）" for r in risers[:3]) + "。")
    if terms:
        overview.append("这一周成规模出现的新说法有：" + "、".join(f"“{t['term']}”" for t in terms[:4]) + "。")

    sections = [{"h": "本周概况", "p": overview}]
    if risers:
        sections.append({"h": "跳升最快的方向", "items": [
            {"text": r["name"], "href": f"/signal/{r['slug']}",
             "note": f"占当周论文 {_pct(r['share'])}，过去 8 周平均 {_pct(r['prev'])}（{r['lift']:.1f}×）"}
            for r in risers]})
    if terms:
        sections.append({"h": "新出现的说法", "items": [
            {"text": t["term"], "href": f"/papers?q={quote(t['term'])}&week={w}",
             "note": f"{t['count']} 篇论文使用，相对过去 8 周 {t['lift']:.1f}×"} for t in terms]})
    if entry["notable"]:
        sections.append({"h": "值得读的论文", "items": [
            {"text": p["title"], "href": ARXIV_ABS + p["id"], "external": True,
             "note": " · ".join(p.get("signals") or [])} for p in entry["notable"]]})
    if week_insights:
        sections.append({"h": "本周洞察", "items": [
            {"text": i["title"], "href": i["path"], "note": i["body"]}
            for i in sorted(week_insights, key=lambda i: -i["score"])[:8]]})
    if memo and memo.get("text"):
        sections.append({"h": "研究员备忘录", "md": memo["text"], "note": memo.get("model")})

    summary = f"{rng}，{entry['volume']:,} 篇 AI 论文投稿。"
    if risers:
        summary += "涨得最快：" + "、".join(f"{r['name']}（{r['lift']:.1f}×）" for r in risers[:3]) + "。"
    if terms:
        summary += "新说法：" + "、".join(t["term"] for t in terms[:3]) + "。"
    return {
        "title": title,
        "summary": summary[:155],
        "body": {"sections": sections},
        "source": "template+claude" if memo and memo.get("text") else "template",
    }


def update_all(timeline):
    """Upsert a brief for every completed week in the timeline; untouched weeks keep their timestamps."""
    by_week = {}
    for it in views.insights(status="active", limit=2000):
        by_week.setdefault(it["week"], []).append(it)
    existing = {r["week"]: r for r in db.q("SELECT week, title, summary, body, source FROM briefs")}
    ts = now()
    changed = 0
    with db.tx() as c:
        for i, entry in enumerate(timeline):
            prev = timeline[i - 1] if i else None
            b = build(entry, prev, by_week.get(entry["week"], []), db.kv_get(f"memo:{entry['week']}"))
            if b is None:
                continue
            body = json.dumps(b["body"], ensure_ascii=False)
            old = existing.get(entry["week"])
            if old and (old["title"], old["summary"], old["body"], old["source"]) == (b["title"], b["summary"], body, b["source"]):
                continue
            c.execute(
                "INSERT INTO briefs(week, title, summary, body, source, generated_at, updated_at) VALUES(?,?,?,?,?,?,?) "
                "ON CONFLICT(week) DO UPDATE SET title=excluded.title, summary=excluded.summary, body=excluded.body, "
                "source=excluded.source, updated_at=excluded.updated_at",
                (entry["week"], b["title"], b["summary"], body, b["source"], ts, ts))
            changed += 1
    return changed
