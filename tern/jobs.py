"""Background jobs: first-run backfill, the daily fetch, and re-analysis.

One worker thread runs jobs serially; the scheduler thread enqueues the daily
fetch once per day at DAILY_HOUR (and on startup if the last one is stale).
"""

import queue
import threading
import time
import traceback
from datetime import datetime, timedelta, timezone

from . import analysis, briefs, config, db, ingest, memo, publish

_q = queue.Queue()
_pending = set()
_state = {"job": None, "message": "空闲", "done": 0, "total": 0, "started_at": None}
_state_lock = threading.Lock()


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def state():
    with _state_lock:
        return dict(_state, queued=sorted(_pending))


def _progress(done, total, msg):
    with _state_lock:
        _state.update(done=done, total=total, message=msg)


def enqueue(kind, **kw):
    with _state_lock:
        if kind in _pending or _state["job"] == kind:
            return False
        _pending.add(kind)
    _q.put((kind, kw))
    return True


def _record(kind):
    with db.tx() as c:
        return c.execute("INSERT INTO runs(kind, started_at, status) VALUES(?,?,'running')", (kind, _now())).lastrowid


def _finish(run_id, status, detail):
    with db.tx() as c:
        c.execute("UPDATE runs SET finished_at=?, status=?, detail=? WHERE id=?", (_now(), status, detail[:2000], run_id))


_analysis_lock = threading.Lock()


# Set when local data changed and the online copy is behind; the scheduler publishes it.
_dirty = threading.Event()


def analyze_now():
    """Synchronous re-analysis for user edits; never waits behind a long fetch job."""
    with _analysis_lock:
        snap = analysis.run()
    if config.PUBLISH_R2:
        _dirty.set()
    return snap


def _analyze():
    _progress(0, 1, "分析时间序列与生成洞察")
    snap = analyze_now()
    if snap.get("ready") and memo.available() and not db.kv_get(f"memo:{snap['analysis_week']}"):
        try:
            _progress(0, 1, "Claude 撰写本周备忘录")
            memo.generate(snap)
        except Exception as e:  # memo is optional; never fail the run over it
            db.kv_set("memo_error", f"{type(e).__name__}: {e}"[:400])
        else:
            briefs.update_all(snap["timeline"])  # fold the new memo into this week's brief
    return snap


def _run(kind, kw):
    if kind == "backfill":
        weeks = kw.get("weeks", config.BACKFILL_WEEKS)
        per = kw.get("per_week", config.BACKFILL_PER_WEEK)
        new = 0
        for step in ingest.backfill(weeks, per, _progress):
            if step == "checkpoint":
                analyze_now()
            else:
                new = step
        _analyze()
        return f"回填 {weeks} 周，新增 {new} 篇"
    if kind == "daily":
        new = ingest.daily(_progress)
        db.kv_set("last_daily", _now())
        _analyze()
        return f"新增 {new} 篇"
    if kind == "analyze":
        _analyze()
        return "ok"
    if kind == "publish":
        _dirty.clear()
        _progress(0, 1, "发布数据到线上")
        return publish.publish()
    raise ValueError(kind)


def _worker():
    while True:
        kind, kw = _q.get()
        with _state_lock:
            _pending.discard(kind)
            _state.update(job=kind, message="开始", done=0, total=0, started_at=_now())
        run_id = _record(kind)
        try:
            _finish(run_id, "ok", _run(kind, kw))
        except Exception as e:
            _finish(run_id, "error", f"{type(e).__name__}: {e}\n{traceback.format_exc()}")
        finally:
            with _state_lock:
                _state.update(job=None, message="空闲", done=0, total=0, started_at=None)
        # A fetch or analysis job publishes right away; edits wait for the scheduler tick.
        if kind != "publish" and _dirty.is_set():
            enqueue("publish")


def next_daily_at(now=None):
    now = now or datetime.now()
    at = now.replace(hour=config.DAILY_HOUR, minute=0, second=0, microsecond=0)
    return at if at > now else at + timedelta(days=1)


def _scheduler():
    """Every 10 minutes: resume a failed backfill, and run the daily fetch once it is due."""
    while True:
        if db.kv_get("backfill_started"):
            last_bf = db.q1("SELECT status, finished_at FROM runs WHERE kind='backfill' ORDER BY id DESC LIMIT 1")
            if last_bf and last_bf["status"] == "error":
                enqueue("backfill")
            last = db.kv_get("last_daily")
            due = not last or datetime.now(timezone.utc) - datetime.fromisoformat(last) > timedelta(hours=22)
            if due and datetime.now().hour >= config.DAILY_HOUR or not last:
                enqueue("daily")
        if _dirty.is_set():
            enqueue("publish")
        time.sleep(600)


def start():
    # Runs left 'running' by a killed process are marked so the history stays truthful.
    with db.tx() as c:
        c.execute("UPDATE runs SET status='error', detail='interrupted (process exited)', finished_at=? "
                  "WHERE status='running'", (_now(),))
    threading.Thread(target=_worker, daemon=True, name="tern-worker").start()
    if not db.kv_get("backfill_started"):
        db.kv_set("backfill_started", _now())
        enqueue("backfill")
    else:
        # Resume an interrupted backfill (finished keys are skipped).
        last_backfill = db.q1("SELECT status FROM runs WHERE kind='backfill' ORDER BY id DESC LIMIT 1")
        if last_backfill and last_backfill["status"] != "ok":
            enqueue("backfill")
    threading.Thread(target=_scheduler, daemon=True, name="tern-scheduler").start()
