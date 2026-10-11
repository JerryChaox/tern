import json
import mimetypes
import re
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import config, db, jobs, memo, seo, signals, views
from .signals import now

KINDS = {"acceleration", "deceleration", "synchrony", "diffusion", "shift", "emerging", "volume", "regime", "thesis"}


def _slugify(name):
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return f"c-{s or 'signal'}"[:40]


class Handler(BaseHTTPRequestHandler):
    server_version = "tern/0.1"

    def log_message(self, fmt, *args):
        pass

    # ---- helpers ---------------------------------------------------------
    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _err(self, code, msg):
        self._json({"error": msg}, code)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def _blocked(self):
        ip = self.headers.get("Cf-Connecting-IP")
        if ip is None or not config.ALLOW_IPS or ip in config.ALLOW_IPS:
            return False
        print(f"blocked {ip} {self.command} {self.path}", flush=True)
        body = f"forbidden: {ip}\n".encode()
        self.send_response(403)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        return True

    def _readonly(self):
        if config.READONLY:
            self._err(403, "线上为只读副本，修改请在本地进行")
            return True
        return False

    def _route(self):
        u = urllib.parse.urlparse(self.path)
        return u.path, {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}

    # ---- GET -------------------------------------------------------------
    def do_GET(self):
        if self._blocked():
            return
        path, qs = self._route()
        try:
            if path == "/api/status":
                return self._json(status())
            if config.READONLY and path == "/__tern/version":
                return self._json({"etag": _loaded_etag()})
            if path == "/api/snapshot":
                return self._json(db.kv_get("snapshot", {"ready": False}))
            if path == "/api/insights":
                return self._json(list_insights(qs))
            if path == "/api/papers":
                return self._json(list_papers(qs))
            if path == "/api/memo":
                snap = db.kv_get("snapshot", {})
                week = qs.get("week") or snap.get("analysis_week")
                return self._json({"available": memo.available(), "memo": db.kv_get(f"memo:{week}"),
                                   "error": db.kv_get("memo_error")})
            if path == "/api/signal-preview":
                return self._json(preview(qs.get("pattern", "")))
            if path == "/api/frontpage":
                snap = db.kv_get("snapshot", {})
                hero, feed = views.front_page(views.insights(week=qs.get("week") or snap.get("analysis_week"), limit=40))
                return self._json({"hero": hero, "feed": feed})
            if path == "/api/briefs":
                return self._json(views.brief_list())
            m = re.fullmatch(r"/api/briefs/(\d{4}-\d{2}-\d{2})", path)
            if m:
                b = views.brief(m.group(1))
                return self._json(b) if b else self._err(404, "这一周没有周报")
            base = seo.base_url(self.headers.get("Host"))
            if path == "/robots.txt":
                return self._text(seo.robots(base), "text/plain")
            if path == "/sitemap.xml":
                return self._text(seo.sitemap(base), "application/xml")
            if path == "/briefs.xml":
                return self._text(seo.feed(base), "application/rss+xml")
            return self._static(path, qs, base)
        except Exception as e:
            return self._err(500, f"{type(e).__name__}: {e}")

    def _text(self, body, ctype, code=200):
        data = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _static(self, path, qs, base):
        f = (config.WEB_DIR / path.lstrip("/")).resolve()
        if path not in ("", "/") and config.WEB_DIR.resolve() in f.parents and f.is_file() and f.name != "index.html":
            return self._file(f)
        # App routes get the SPA shell with server-rendered content; anything else is a real 404.
        page = seo.route(path, qs) or seo.page_not_found()
        shell = (config.WEB_DIR / "index.html").read_text()
        return self._text(seo.render(page, shell, base), "text/html", page.status)

    def _file(self, f):
        data = f.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", (mimetypes.guess_type(f.name)[0] or "application/octet-stream") + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    # ---- POST / DELETE ---------------------------------------------------
    def do_PUT(self):
        """Read-only instance: receive a newly published database (sent by the edge Worker)."""
        path, _ = self._route()
        if not config.READONLY or path != "/__tern/load":
            return self._err(404, "not found")
        etag = self.headers.get("X-Etag", "")
        tmp = config.DATA_DIR / "incoming.db"
        with open(tmp, "wb") as f:
            for chunk in self._body_chunks():
                f.write(chunk)
        db.replace_with(tmp)
        (config.DATA_DIR / "etag").write_text(etag)
        return self._json({"ok": True, "etag": etag})

    def _body_chunks(self):
        if self.headers.get("Transfer-Encoding", "").lower() == "chunked":
            while True:
                size = int(self.rfile.readline().split(b";")[0], 16)
                if size == 0:
                    self.rfile.readline()
                    return
                yield self.rfile.read(size)
                self.rfile.readline()
        left = int(self.headers.get("Content-Length") or 0)
        while left > 0:
            chunk = self.rfile.read(min(left, 1 << 20))
            if not chunk:
                raise ConnectionError("body ended early")
            left -= len(chunk)
            yield chunk

    def do_POST(self):
        if self._blocked() or self._readonly():
            return
        path, _ = self._route()
        try:
            body = self._body()
            if path == "/api/run":
                kind = body.get("kind")
                if kind not in ("daily", "analyze", "backfill"):
                    return self._err(400, "kind must be daily | analyze | backfill")
                return self._json({"queued": jobs.enqueue(kind)})
            m = re.fullmatch(r"/api/insights/(\d+)", path)
            if m:
                st = body.get("status")
                if st not in ("new", "starred", "dismissed"):
                    return self._err(400, "bad status")
                with db.tx() as c:
                    c.execute("UPDATE insights SET status=? WHERE id=?", (st, int(m.group(1))))
                return self._json({"ok": True})
            if path == "/api/signals":
                name = (body.get("name") or "").strip()
                pattern = (body.get("pattern") or "").strip()
                if not name or not pattern:
                    return self._err(400, "name 和 pattern 必填")
                slug = body.get("slug") or _slugify(name)
                existing = db.q1("SELECT custom FROM signals WHERE slug=?", (slug,))
                if existing and not existing["custom"]:
                    return self._err(409, "内置信号不可覆盖")
                try:
                    tagged = signals.upsert_custom(slug, name, body.get("grp") or "我的信号", pattern,
                                                   body.get("description") or "")
                except re.error as e:
                    return self._err(400, f"正则无效：{e}")
                jobs.analyze_now()
                return self._json({"slug": slug, "tagged": tagged})
            if path == "/api/theses":
                text = (body.get("text") or "").strip()
                slugs = [s for s in body.get("slugs") or [] if db.q1("SELECT 1 FROM signals WHERE slug=?", (s,))]
                stance = body.get("stance")
                if not text or not slugs or stance not in ("up", "down"):
                    return self._err(400, "需要判断文本、至少一个信号、以及方向 up/down")
                with db.tx() as c:
                    tid = c.execute("INSERT INTO theses(text, slugs, stance, created_at) VALUES(?,?,?,?)",
                                    (text, json.dumps(slugs), stance, now())).lastrowid
                jobs.analyze_now()
                return self._json({"id": tid})
            return self._err(404, "not found")
        except json.JSONDecodeError:
            return self._err(400, "invalid JSON")
        except Exception as e:
            return self._err(500, f"{type(e).__name__}: {e}")

    def do_DELETE(self):
        if self._blocked() or self._readonly():
            return
        path, _ = self._route()
        m = re.fullmatch(r"/api/signals/([\w\-]+)", path)
        if m:
            if not signals.delete_custom(m.group(1)):
                return self._err(404, "只能删除自定义信号")
            jobs.analyze_now()
            return self._json({"ok": True})
        m = re.fullmatch(r"/api/theses/(\d+)", path)
        if m:
            with db.tx() as c:
                c.execute("DELETE FROM theses WHERE id=?", (int(m.group(1)),))
                c.execute("DELETE FROM insights WHERE kind='thesis' AND subject=?", (f"thesis-{m.group(1)}",))
            jobs.analyze_now()
            return self._json({"ok": True})
        return self._err(404, "not found")


def status():
    counts = db.q1("SELECT COUNT(*) papers, COUNT(DISTINCT week) weeks, MIN(week) first_week, MAX(week) last_week FROM papers")
    snap = db.kv_get("snapshot", {})
    return {
        **counts,
        "insights": db.q1("SELECT COUNT(*) n FROM insights")["n"],
        "job": jobs.state(),
        "last_daily": db.kv_get("last_daily"),
        "next_daily": jobs.next_daily_at().isoformat(timespec="minutes"),
        "runs": db.q("SELECT id, kind, started_at, finished_at, status, substr(detail, 1, 200) detail "
                     "FROM runs ORDER BY id DESC LIMIT 8"),
        "snapshot_at": snap.get("generated_at"),
        "analysis_week": snap.get("analysis_week"),
        "memo_available": memo.available(),
        "readonly": config.READONLY,
        "categories": [{"id": c, "name": n} for c, n in config.CATEGORIES],
    }


def _loaded_etag():
    f = config.DATA_DIR / "etag"
    return f.read_text() if f.exists() else None


def list_insights(qs):
    if qs.get("id"):
        return views.insights(status="all", ids=[int(qs["id"])], limit=1)
    where, args = [], []
    if qs.get("kind") in KINDS:
        where.append("kind=?"); args.append(qs["kind"])
    st = qs.get("status", "active")
    if st == "active":
        where.append("status != 'dismissed'")
    elif st in ("new", "starred", "dismissed"):
        where.append("status=?"); args.append(st)
    if qs.get("subject"):
        where.append("subject=?"); args.append(qs["subject"])
    if qs.get("week"):
        where.append("week=?"); args.append(qs["week"])
    sql = "SELECT * FROM insights" + (" WHERE " + " AND ".join(where) if where else "")
    sql += " ORDER BY week DESC, score DESC LIMIT ?"
    args.append(min(int(qs.get("limit", 60)), 300))
    rows = db.q(sql, args)
    for r in rows:
        r["evidence"] = json.loads(r["evidence"])
        r["path"] = views.insight_path(r)
    return rows


def list_papers(qs):
    where, args, join = [], [], ""
    if qs.get("signal"):
        join = "JOIN paper_signal ps ON ps.paper_id=p.id AND ps.slug=?"
        args.append(qs["signal"])
    if qs.get("q"):
        where.append("(p.title LIKE ? OR p.abstract LIKE ?)")
        args += [f"%{qs['q']}%"] * 2
    if qs.get("week"):
        where.append("p.week=?"); args.append(qs["week"])
    if qs.get("cat"):
        where.append("p.id IN (SELECT paper_id FROM fetched WHERE cat=?)"); args.append(qs["cat"])
    cond = " WHERE " + " AND ".join(where) if where else ""
    total = db.q1(f"SELECT COUNT(*) n FROM papers p {join}{cond}", args)["n"]
    limit = min(int(qs.get("limit", 30)), 100)
    offset = int(qs.get("offset", 0))
    rows = db.q(f"SELECT p.id, p.title, p.abstract, p.authors, p.categories, p.primary_cat, p.published, p.week "
                f"FROM papers p {join}{cond} ORDER BY p.published DESC LIMIT ? OFFSET ?", [*args, limit, offset])
    if rows:
        tags = db.q(f"SELECT paper_id, slug FROM paper_signal WHERE paper_id IN ({','.join('?' * len(rows))})",
                    [r["id"] for r in rows])
        by = {}
        for t in tags:
            by.setdefault(t["paper_id"], []).append(t["slug"])
        for r in rows:
            r["authors"] = json.loads(r["authors"])
            r["signals"] = by.get(r["id"], [])
    return {"total": total, "items": rows}


def preview(pattern):
    try:
        rx = signals.compile_pattern(pattern)
    except re.error as e:
        return {"error": str(e)}
    if not pattern:
        return {"matches": 0, "sample": 0, "examples": []}
    rows = db.q("SELECT id, title, abstract FROM papers ORDER BY published DESC LIMIT 3000")
    hits = [r for r in rows if rx.search(f"{r['title']} {r['abstract']}")]
    return {"matches": len(hits), "sample": len(rows),
            "examples": [{"id": r["id"], "title": r["title"]} for r in hits[:5]]}


def serve():
    httpd = ThreadingHTTPServer((config.HOST, config.PORT), Handler)
    print(f"Tern 已启动：http://{config.HOST}:{config.PORT}", flush=True)
    httpd.serve_forever()
