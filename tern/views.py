"""Read-side rules shared by the JSON API, the server-rendered pages and the weekly briefs.

Kept in one place so the SPA, the HTML a crawler sees and the brief always agree.
"""

import json
import re
from datetime import date, timedelta

from . import db

# Headline candidates, in order: structural shifts (the 2016-GPU shape) beat single-term spikes.
HEADLINE_KINDS = ["synchrony", "diffusion", "regime", "acceleration", "shift"]
# Feed order after the headline: structural signals, the user's theses, then term spikes and raw volume.
FEED_ORDER = HEADLINE_KINDS + ["deceleration", "thesis", "emerging", "volume"]
FEED_PER_KIND = 2

KIND_NAMES = {
    "acceleration": "加速", "deceleration": "回落", "synchrony": "跨领域同步", "diffusion": "渗透",
    "shift": "格局变化", "emerging": "新词", "volume": "投稿量", "regime": "整体态势", "thesis": "我的判断",
}


def front_page(items):
    """Insight scores are not comparable across kinds (term cards score high by construction),
    so the front page caps each kind and leads with the strongest structural signal."""
    hero = next((i for k in HEADLINE_KINDS for i in items if i["kind"] == k), items[0] if items else None)
    per, feed = {}, []
    for it in items:
        if hero is not None and it["id"] == hero["id"]:
            continue
        per[it["kind"]] = per.get(it["kind"], 0) + 1
        if per[it["kind"]] <= FEED_PER_KIND:
            feed.append(it)
    rank = {k: i for i, k in enumerate(FEED_ORDER)}
    feed.sort(key=lambda i: (rank.get(i["kind"], len(FEED_ORDER)), -i["score"]))
    return hero, feed


def slugify(text, limit=60):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:limit].strip("-")


def insight_path(it):
    slug = slugify(it["subject"])
    return f"/insight/{it['id']}-{slug}" if slug else f"/insight/{it['id']}"


def week_range(monday_iso):
    """'9月28日 – 10月4日' for the week starting on the given Monday."""
    start = date.fromisoformat(monday_iso)
    end = start + timedelta(days=6)
    tail = f"{end.month}月{end.day}日" if end.month != start.month else f"{end.day}日"
    return f"{start.month}月{start.day}日 – {tail}"


def insights(week=None, status="active", limit=300, ids=None):
    where, args = [], []
    if status == "active":
        where.append("status != 'dismissed'")
    elif status in ("new", "starred", "dismissed"):
        where.append("status=?"); args.append(status)
    if week:
        where.append("week=?"); args.append(week)
    if ids:
        where.append(f"id IN ({','.join('?' * len(ids))})"); args += list(ids)
    sql = "SELECT * FROM insights" + (" WHERE " + " AND ".join(where) if where else "")
    rows = db.q(sql + " ORDER BY week DESC, score DESC LIMIT ?", [*args, limit])
    for r in rows:
        r["evidence"] = json.loads(r["evidence"])
        r["path"] = insight_path(r)
    return rows


def brief_list():
    return db.q("SELECT week, title, summary, source, updated_at FROM briefs ORDER BY week DESC")


def brief(week):
    row = db.q1("SELECT * FROM briefs WHERE week=?", (week,))
    if row:
        row["body"] = json.loads(row["body"])
        weeks = [r["week"] for r in db.q("SELECT week FROM briefs ORDER BY week")]
        i = weeks.index(week)
        row["prev"] = weeks[i - 1] if i > 0 else None
        row["next"] = weeks[i + 1] if i + 1 < len(weeks) else None
    return row
