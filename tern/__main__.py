"""Usage:
  python3 -m tern              # start web app + daily scheduler (first run backfills)
  python3 -m tern fetch        # one daily fetch + analysis, then exit
  python3 -m tern backfill [weeks] [per_week]
  python3 -m tern analyze
"""

import sys

from . import analysis, config, db, ingest, jobs, server, signals


def main(argv):
    db.conn()
    cmd = argv[0] if argv else "serve"
    if cmd == "serve" and config.READONLY:
        server.serve()  # the published copy is pushed in by the edge Worker
        return
    signals.seed()
    if cmd == "serve":
        jobs.start()
        server.serve()
    elif cmd == "fetch":
        print("新增", ingest.daily(lambda d, t, m: print(f"[{d}/{t}] {m}", flush=True)), "篇")
        jobs._analyze()
    elif cmd == "backfill":
        weeks = int(argv[1]) if len(argv) > 1 else config.BACKFILL_WEEKS
        per = int(argv[2]) if len(argv) > 2 else config.BACKFILL_PER_WEEK
        db.kv_set("backfill_started", db.kv_get("backfill_started") or "cli")
        for step in ingest.backfill(weeks, per, lambda d, t, m: print(f"[{d}/{t}] {m}", flush=True)):
            if step != "checkpoint":
                print("新增", step, "篇")
        jobs._analyze()
    elif cmd == "analyze":
        snap = analysis.run()
        print("ready" if snap.get("ready") else "数据不足（需要 ≥3 个完整周）")
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
