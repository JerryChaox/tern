"""Daily fetch and first-run backfill.

Backfill samples each (category, week): the first N/2 papers of the week and the
last N/2, plus the true weekly total. Shares are robust to sampling; totals come
from arXiv itself. Daily fetch pulls every paper of the last few days.
"""

import json
import math
from datetime import date, datetime, timedelta, timezone

from . import arxiv, config, db, signals


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def store(papers, cat):
    if not papers:
        return 0
    fetched_at = _now()
    rows, new_ids = [], []
    existing = {r["id"] for r in db.q(
        f"SELECT id FROM papers WHERE id IN ({','.join('?' * len(papers))})", [p["id"] for p in papers])}
    for p in papers:
        pub = datetime.fromisoformat(p["published"].replace("Z", "+00:00"))
        rows.append((p["id"], p["title"], p["abstract"], json.dumps(p["authors"][:30], ensure_ascii=False),
                     " ".join(p["categories"]), p["primary_cat"], p["published"], arxiv.monday(pub), fetched_at))
        if p["id"] not in existing:
            new_ids.append(p)
    with db.tx() as c:
        c.executemany("INSERT OR IGNORE INTO papers VALUES(?,?,?,?,?,?,?,?,?)", rows)
        c.executemany("INSERT OR IGNORE INTO fetched(paper_id, cat) VALUES(?,?)", [(p["id"], cat) for p in papers])
    signals.tag(new_ids)
    return len(new_ids)


def set_volume(cat, week, total, sampled):
    with db.tx() as c:
        c.execute(
            "INSERT INTO volume(cat, week, total, sampled, updated_at) VALUES(?,?,?,?,?) "
            "ON CONFLICT(cat, week) DO UPDATE SET total=excluded.total, "
            "sampled=MIN(volume.sampled, excluded.sampled), updated_at=excluded.updated_at",
            (cat, week, total, int(sampled), _now()),
        )


def week_bounds(monday_iso):
    start = datetime.fromisoformat(monday_iso)
    return start, start + timedelta(days=7)


def backfill_week(cat, monday_iso, per_week):
    start, end = week_bounds(monday_iso)
    half = per_week // 2
    total, newest = arxiv.search(cat, start, end, max_results=half, order="descending")
    new = store(newest, cat)
    if total > half:
        _, oldest = arxiv.search(cat, start, end, max_results=min(half, total - half), order="ascending")
        new += store(oldest, cat)
    set_volume(cat, monday_iso, total, sampled=total > per_week)
    return new


def backfill(weeks, per_week, progress=lambda done, total, msg: None):
    """Walk weeks newest→oldest so the dashboard fills from the present backward."""
    done_keys = set(db.kv_get("backfill_done", []))
    this_monday = date.fromisoformat(arxiv.monday(date.today()))
    mondays = [(this_monday - timedelta(weeks=i)).isoformat() for i in range(1, weeks + 1)]
    jobs = [(m, cat) for m in mondays for cat, _ in config.CATEGORIES]
    new_total = 0
    for i, (m, cat) in enumerate(jobs):
        key = f"{cat}|{m}|{per_week}"
        if key in done_keys:
            continue
        progress(i, len(jobs), f"回填 {cat} · {m} 当周")
        new_total += backfill_week(cat, m, per_week)
        done_keys.add(key)
        db.kv_set("backfill_done", sorted(done_keys))
        if (i + 1) % (len(config.CATEGORIES) * 4) == 0:
            yield "checkpoint"
    progress(len(jobs), len(jobs), "回填完成")
    yield new_total


def daily(progress=lambda done, total, msg: None):
    """Fetch every paper since the last successful daily run; refresh weekly totals for the weeks touched.

    The window starts where the previous run stopped (with a small overlap), so no
    day is skipped when runs are missed. The first run starts at this week's Monday,
    right where the backfill (completed weeks only) ends.
    """
    end = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=1)
    until = db.kv_get("daily_until")
    if until:
        start = datetime.fromisoformat(until) - timedelta(hours=6)
    else:
        start, _ = week_bounds(arxiv.monday(date.today()))
    start = min(start, end - timedelta(days=config.DAILY_LOOKBACK_DAYS))
    start = max(start, end - timedelta(days=config.DAILY_MAX_CATCHUP_DAYS))
    days = math.ceil((end - start) / timedelta(days=1))
    cap = config.DAILY_CAP_PER_CAT * math.ceil(days / config.DAILY_LOOKBACK_DAYS)
    mondays = []
    m = date.fromisoformat(arxiv.monday(start.date()))
    while m <= date.today():
        mondays.append(m.isoformat())
        m += timedelta(weeks=1)
    new_total = 0
    for i, (cat, _) in enumerate(config.CATEGORIES):
        progress(i, len(config.CATEGORIES), f"抓取 {cat}：{start:%m-%d} 起 {days} 天")
        offset, total = 0, None
        while total is None or offset < min(total, cap):
            total, batch = arxiv.search(cat, start, end, start=offset, max_results=500)
            if not batch:
                break
            new_total += store(batch, cat)
            offset += len(batch)
        for m in mondays:
            ws, we = week_bounds(m)
            wk_total, _ = arxiv.search(cat, ws, we, max_results=1)
            stored = db.q1("SELECT COUNT(*) n FROM fetched f JOIN papers p ON p.id=f.paper_id "
                           "WHERE f.cat=? AND p.week=?", (cat, m))["n"]
            set_volume(cat, m, wk_total, sampled=stored < wk_total * 0.9)
    db.kv_set("daily_until", end.isoformat())
    progress(len(config.CATEGORIES), len(config.CATEGORIES), "抓取完成")
    return new_total
