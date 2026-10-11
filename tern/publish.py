"""Publish a consistent copy of the database to R2 for the read-only online instance.

Uploads go through wrangler, so the local Cloudflare login is the only credential
needed; nothing is stored here.
"""

import shutil
import subprocess

from . import config, db
from .signals import now


def publish():
    out_dir = config.DATA_DIR / "publish"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / config.PUBLISH_KEY
    out.unlink(missing_ok=True)
    db.backup(out)
    npx = shutil.which("npx")
    if not npx:
        raise RuntimeError("npx not found; wrangler is needed to upload to R2")
    r = subprocess.run(
        [npx, "-y", "wrangler@4", "r2", "object", "put", f"{config.PUBLISH_R2}/{config.PUBLISH_KEY}",
         "--file", str(out), "--remote", "--content-type", "application/vnd.sqlite3"],
        capture_output=True, text=True, timeout=900, cwd=config.DATA_DIR,
    )
    if r.returncode != 0:
        raise RuntimeError(f"wrangler upload failed: {(r.stderr or r.stdout)[-400:]}")
    size_mb = out.stat().st_size / 1e6
    out.unlink()
    db.kv_set("last_publish", now())
    return f"已发布 {size_mb:.0f} MB 到 R2 {config.PUBLISH_R2}"
