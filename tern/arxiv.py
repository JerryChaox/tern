"""Minimal arXiv API client (Atom feed), throttled to arXiv's 1 req / 3 s policy."""

import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

from . import config

NS = {
    "a": "http://www.w3.org/2005/Atom",
    "os": "http://a9.com/-/spec/opensearch/1.1/",
    "arxiv": "http://arxiv.org/schemas/atom",
}
_UA = "tern-research-radar/0.1 (prototype; arXiv API polite client)"
_throttle = threading.Lock()
_last_call = 0.0


def _get(url, retries=7):
    """GET with arXiv etiquette: global min interval, and exponential backoff on 429/503."""
    global _last_call
    for attempt in range(retries):
        with _throttle:
            wait = config.ARXIV_MIN_INTERVAL - (time.monotonic() - _last_call)
            if wait > 0:
                time.sleep(wait)
            _last_call = time.monotonic()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": _UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504) or attempt == retries - 1:
                raise
            retry_after = e.headers.get("Retry-After") if e.headers else None
            delay = int(retry_after) if retry_after and retry_after.isdigit() else min(300, 20 * 2 ** attempt)
            with _throttle:  # hold the lock so no other thread hammers arXiv meanwhile
                time.sleep(delay)
                _last_call = time.monotonic()
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt == retries - 1:
                raise
            time.sleep(10 * (attempt + 1))


def _fmt(dt):
    return dt.strftime("%Y%m%d%H%M")


def monday(d):
    d = d.date() if isinstance(d, datetime) else d
    return (d - timedelta(days=d.weekday())).isoformat()


def search(cat, start_dt, end_dt, start=0, max_results=100, order="descending"):
    """Papers in `cat` submitted in [start_dt, end_dt). Returns (total, papers)."""
    query = f"cat:{cat} AND submittedDate:[{_fmt(start_dt)} TO {_fmt(end_dt)}]"
    params = urllib.parse.urlencode({
        "search_query": query,
        "start": start,
        "max_results": max_results,
        "sortBy": "submittedDate",
        "sortOrder": order,
    })
    raw = _get(f"{config.ARXIV_API}?{params}")
    root = ET.fromstring(raw)
    total_el = root.find("os:totalResults", NS)
    total = int(total_el.text) if total_el is not None else 0
    papers = []
    for e in root.findall("a:entry", NS):
        id_url = e.findtext("a:id", "", NS)
        m = re.search(r"abs/([^v]+)(v\d+)?$", id_url)
        if not m:
            continue
        published = e.findtext("a:published", "", NS)
        cats = [c.get("term") for c in e.findall("a:category", NS)]
        prim = e.find("arxiv:primary_category", NS)
        papers.append({
            "id": m.group(1),
            "title": " ".join(e.findtext("a:title", "", NS).split()),
            "abstract": " ".join(e.findtext("a:summary", "", NS).split()),
            "authors": [a.findtext("a:name", "", NS) for a in e.findall("a:author", NS)],
            "categories": cats,
            "primary_cat": prim.get("term") if prim is not None else (cats[0] if cats else cat),
            "published": published,
        })
    return total, papers
