import re
from datetime import datetime, timezone

from . import config, db


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def seed():
    with db.tx() as c:
        for grp, items in config.DEFAULT_SIGNALS.items():
            for slug, name, pattern, desc in items:
                c.execute(
                    "INSERT INTO signals(slug, name, grp, pattern, description, custom, created_at) "
                    "VALUES(?,?,?,?,?,0,?) ON CONFLICT(slug) DO UPDATE SET "
                    "name=excluded.name, grp=excluded.grp, pattern=excluded.pattern, description=excluded.description "
                    "WHERE signals.custom=0",
                    (slug, name, grp, pattern, desc, now()),
                )


def all_signals():
    return db.q("SELECT * FROM signals ORDER BY custom, rowid")


def compile_pattern(pattern):
    return re.compile(pattern, re.IGNORECASE)


def _text(p):
    return f"{p['title']} {p['abstract']}"


def tag(papers, signals=None):
    """Tag paper dicts (needing id/title/abstract) against signals; writes paper_signal."""
    signals = signals if signals is not None else all_signals()
    compiled = [(s["slug"], compile_pattern(s["pattern"])) for s in signals]
    rows = []
    for p in papers:
        t = _text(p)
        rows.extend((p["id"], slug) for slug, rx in compiled if rx.search(t))
    with db.tx() as c:
        c.executemany("INSERT OR IGNORE INTO paper_signal(paper_id, slug) VALUES(?,?)", rows)
    return len(rows)


def retag(slug):
    sig = db.q1("SELECT * FROM signals WHERE slug=?", (slug,))
    with db.tx() as c:
        c.execute("DELETE FROM paper_signal WHERE slug=?", (slug,))
    papers = db.q("SELECT id, title, abstract FROM papers")
    return tag(papers, [sig])


def upsert_custom(slug, name, grp, pattern, description=""):
    compile_pattern(pattern)  # raises re.error on bad input
    with db.tx() as c:
        c.execute(
            "INSERT INTO signals(slug, name, grp, pattern, description, custom, created_at) VALUES(?,?,?,?,?,1,?) "
            "ON CONFLICT(slug) DO UPDATE SET name=excluded.name, grp=excluded.grp, pattern=excluded.pattern, "
            "description=excluded.description",
            (slug, name, grp, pattern, description, now()),
        )
    return retag(slug)


def delete_custom(slug):
    with db.tx() as c:
        n = c.execute("DELETE FROM signals WHERE slug=? AND custom=1", (slug,)).rowcount
        if n:
            c.execute("DELETE FROM paper_signal WHERE slug=?", (slug,))
    return n
