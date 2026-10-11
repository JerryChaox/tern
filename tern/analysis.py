"""Turn papers into time series, a weekly timeline, and insight cards.

Every number shown in the UI comes from one snapshot built here, so the
dashboard, the timeline and the insight feed always agree.
"""

import json
import math
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone

from . import arxiv, config, db

STOP = set("""
a about above after again against all also although among an and any are as at be because been before being
below between both but by can could did do does doing down during each few for from further had has have having
he her here hers him his how however i if in into is it its itself just less made make makes many may me might
more most much must my new no nor not now of off often on once one only or other our ours out over own per
present propose proposed provide provides rather same several she should show shows significant significantly so
some such than that the their theirs them then there these they this those through thus to too two under until
up upon us use used uses using various very via was we well were what when where whether which while who whom
why will with within without would yet you your based approach approaches method methods results result paper
work framework model models task tasks data performance existing study achieve achieves state art first however
across further novel demonstrate demonstrates effectively effective improve improves improved improving evaluate
large small high low different specific key like three four set number allows enabling enable enables address
problem problems recent recently while significant challenge challenges ability able including include includes
compared compare outperforms outperform experiments experimental extensive available code https github com
require requires requiring required neither either additional scalable support supports supported ablations
ablation remains remain toward towards across whereas leading lead leads yield yields yielding achieving
substantially substantial consistently consistent strong stronger often typically limited without need needs
""".split())
WORD = re.compile(r"\b[a-z][a-z0-9\-]{2,}\b")
ACRONYM = re.compile(r"\b[A-Z][A-Za-z]*[A-Z][A-Za-z0-9\-]*\b")
GENERIC_ACRONYMS = set("LLM LLMs AI ML NLP CNN RNN GPU GPUs API SOTA LLMS RL VLM VLMs MLLM MLLMs QA IoT US UK EU".split())

MAX_WEEKS = 52


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def completed_mondays():
    """Mondays of weeks that have fully elapsed, newest last."""
    this_monday = date.fromisoformat(arxiv.monday(date.today()))
    rows = db.q("SELECT DISTINCT week FROM volume WHERE week < ? ORDER BY week", (this_monday.isoformat(),))
    weeks = [r["week"] for r in rows]
    return weeks[-MAX_WEEKS:]


def _windows(n):
    recent = max(2, min(4, n // 4))
    base = min(12, n - recent)
    return recent, base


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else 0.0


def _slope_log(ys):
    """Least-squares slope of log(share) per week; None if too few non-zero points."""
    pts = [(i, math.log(y)) for i, y in enumerate(ys) if y and y > 0]
    if len(pts) < 4:
        return None
    n = len(pts)
    mx = sum(p[0] for p in pts) / n
    my = sum(p[1] for p in pts) / n
    den = sum((p[0] - mx) ** 2 for p in pts)
    return sum((p[0] - mx) * (p[1] - my) for p in pts) / den if den else None


def ztest(k1, n1, k2, n2):
    """Two-proportion z statistic (recent vs base); 0 when undefined."""
    if not n1 or not n2:
        return 0.0
    p = (k1 + k2) / (n1 + n2)
    se = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2)) if 0 < p < 1 else 0
    return ((k1 / n1) - (k2 / n2)) / se if se else 0.0


def pct(x, digits=1):
    return f"{x * 100:.{digits}f}%"


def build_series(weeks, cats, sigs):
    widx = {w: i for i, w in enumerate(weeks)}
    W = len(weeks)
    n = {c: [0] * W for c in cats}
    for r in db.q("SELECT f.cat, p.week, COUNT(*) n FROM fetched f JOIN papers p ON p.id=f.paper_id GROUP BY f.cat, p.week"):
        if r["cat"] in n and r["week"] in widx:
            n[r["cat"]][widx[r["week"]]] = r["n"]
    vol = {c: [None] * W for c in cats}  # None = no count recorded yet
    sampled = [0] * W
    for r in db.q("SELECT cat, week, total, sampled FROM volume"):
        if r["cat"] in vol and r["week"] in widx:
            vol[r["cat"]][widx[r["week"]]] = r["total"]
            sampled[widx[r["week"]]] |= r["sampled"]
    k = {s["slug"]: {c: [0] * W for c in cats} for s in sigs}
    for r in db.q("SELECT ps.slug, f.cat, p.week, COUNT(*) n FROM paper_signal ps JOIN papers p ON p.id=ps.paper_id "
                  "JOIN fetched f ON f.paper_id=p.id GROUP BY ps.slug, f.cat, p.week"):
        if r["slug"] in k and r["cat"] in n and r["week"] in widx:
            k[r["slug"]][r["cat"]][widx[r["week"]]] = r["n"]

    series = {}
    for s in sigs:
        slug = s["slug"]
        by_cat = {}
        for c in cats:
            by_cat[c] = [(k[slug][c][i] / n[c][i]) if n[c][i] else None for i in range(W)]
        share, count = [], []
        for i in range(W):
            num = den = 0.0
            cnt = 0
            for c in cats:
                if n[c][i]:
                    weight = vol[c][i] or n[c][i]
                    num += k[slug][c][i] / n[c][i] * weight
                    den += weight
                    cnt += k[slug][c][i]
            share.append(num / den if den else None)
            count.append(cnt)
        series[slug] = {"share": share, "count": count, "by_cat": by_cat}
    return series, n, vol, sampled


def _terms_for(text):
    words = WORD.findall(text.lower())
    out = set()
    for a, b in zip(words, words[1:]):
        if a not in STOP and b not in STOP and not a[0].isdigit() and not b[0].isdigit():
            out.add(f"{a} {b}")
    for m in ACRONYM.findall(text):
        base = m[:-1] if m.endswith("s") and m[:-1].isupper() else m
        if 3 <= len(base) <= 16 and base not in GENERIC_ACRONYMS:
            out.add(base)
    return out


def term_frequencies(weeks):
    """term -> Counter(week -> document frequency), plus papers per week."""
    if not weeks:
        return {}, Counter()
    df = defaultdict(Counter)
    in_title = Counter()
    per_week = Counter()
    for r in db.q("SELECT week, title, abstract FROM papers WHERE week >= ? AND week <= ?", (weeks[0], weeks[-1])):
        per_week[r["week"]] += 1
        title_terms = _terms_for(r["title"])
        for t in _terms_for(f"{r['title']}. {r['abstract']}"):
            df[t][r["week"]] += 1
        for t in title_terms:
            in_title[t] += 1
    # A phrase must show up in at least two titles: authors name what is new in the
    # title, while generic abstract filler ("requires learning") never gets there.
    df = {t: c for t, c in df.items() if sum(c.values()) >= 5 and in_title[t] >= 2}
    return df, per_week


def emerging_terms(df, per_week, recent_weeks, base_weeks, limit=10):
    """Terms whose recent rate jumped vs the base window.

    Each term is also checked against the whole history (weeks before the base
    window too), so a phrase quiet in the base window but used months ago is
    labeled a comeback, not a brand-new term:
      new     — never seen before the recent window
      revival — absent from the base window, but used earlier
      rising  — already present in the base window
    """
    n_r = sum(per_week[w] for w in recent_weeks) or 1
    n_b = sum(per_week[w] for w in base_weeks) or 1
    floor = max(8, int(0.002 * n_r))
    cands = []
    for t, c in df.items():
        d_r = sum(c[w] for w in recent_weeks)
        if d_r < floor:
            continue
        d_b = sum(c[w] for w in base_weeks)
        lift = (d_r / n_r) / ((d_b + 1) / (n_b + 1))
        if lift < 3:
            continue
        earlier = sum(v for w, v in c.items() if w < base_weeks[0])
        first = min(w for w, v in c.items() if v)
        status = "rising" if d_b else ("revival" if earlier else "new")
        cands.append({"term": t, "recent": d_r, "base": d_b, "earlier": earlier, "first_week": first,
                      "status": status, "lift": lift,
                      "rate_recent": d_r / n_r, "rate_base": d_b / n_b,
                      "score": d_r ** 0.5 * math.log(lift)})
    cands.sort(key=lambda x: -x["score"])
    chosen = []
    for c in cands:
        low = c["term"].lower()
        if any(low in o["term"].lower() or o["term"].lower() in low for o in chosen):
            continue
        chosen.append(c)
        if len(chosen) >= limit:
            break
    return chosen


def _papers_with_term(term, weeks, limit=4):
    like = f"%{term}%"
    marks = ",".join("?" * len(weeks))
    return db.q(f"SELECT id, title, week FROM papers WHERE week IN ({marks}) AND (title LIKE ? OR abstract LIKE ?) "
                f"ORDER BY (title LIKE ?) DESC, published DESC LIMIT ?", (*weeks, like, like, like, limit))


def _top_papers_for_signal(slug, weeks, limit=4):
    marks = ",".join("?" * len(weeks))
    return db.q(f"SELECT p.id, p.title, p.week FROM papers p JOIN paper_signal ps ON ps.paper_id=p.id "
                f"WHERE ps.slug=? AND p.week IN ({marks}) ORDER BY p.published DESC LIMIT ?", (slug, *weeks, limit))


def run():
    sigs = db.q("SELECT * FROM signals ORDER BY custom, rowid")
    sig_by = {s["slug"]: s for s in sigs}
    cats = [c for c, _ in config.CATEGORIES]
    cat_names = dict(config.CATEGORIES)
    weeks = completed_mondays()
    this_monday = arxiv.monday(date.today())
    if len(weeks) < 3:
        snap = {"ready": False, "weeks": weeks, "generated_at": _now()}
        db.kv_set("snapshot", snap)
        return snap

    W = len(weeks)
    R, B = _windows(W)
    recent_idx = list(range(W - R, W))
    base_idx = list(range(W - R - B, W - R))
    recent_weeks = [weeks[i] for i in recent_idx]
    base_weeks = [weeks[i] for i in base_idx]
    analysis_week = weeks[-1]

    series, n, vol, sampled = build_series(weeks, cats, sigs)

    # ---- per-signal stats -------------------------------------------------
    stats = {}
    for s in sigs:
        ser = series[s["slug"]]
        r_share = _mean([ser["share"][i] for i in recent_idx])
        b_share = _mean([ser["share"][i] for i in base_idx])
        r_count = sum(ser["count"][i] for i in recent_idx)
        b_count = sum(ser["count"][i] for i in base_idx)
        lift = (r_share / b_share) if b_share > 0 else (None if r_share == 0 else float("inf"))
        n_r = sum(n[c][i] for c in cats for i in recent_idx)
        n_b = sum(n[c][i] for c in cats for i in base_idx)
        z = ztest(r_count, n_r, b_count, n_b)
        slope = _slope_log(ser["share"][-12:])
        cat_lift = {}
        for c in cats:
            cr = _mean([ser["by_cat"][c][i] for i in recent_idx])
            cb = _mean([ser["by_cat"][c][i] for i in base_idx])
            cnt = sum(round((ser["by_cat"][c][i] or 0) * n[c][i]) for i in recent_idx)
            cnt_b = sum(round((ser["by_cat"][c][i] or 0) * n[c][i]) for i in base_idx)
            cz = ztest(cnt, sum(n[c][i] for i in recent_idx), cnt_b, sum(n[c][i] for i in base_idx))
            cat_lift[c] = {"recent": cr, "base": cb, "lift": (cr / cb) if cb > 0 else None, "count": cnt,
                           "z": round(cz, 2)}
        pen_r = sum(1 for c in cats if cat_lift[c]["recent"] >= 0.01)
        pen_b = sum(1 for c in cats if cat_lift[c]["base"] >= 0.01)
        stats[s["slug"]] = {
            "recent_share": r_share, "base_share": b_share, "lift": lift if lift != float("inf") else None,
            "new": lift == float("inf"), "z": round(z, 2), "recent_count": r_count, "base_count": b_count,
            "slope": slope, "doubling_weeks": (math.log(2) / slope) if slope and slope > 0.005 else None,
            "cat_lift": cat_lift, "penetration": pen_r, "penetration_base": pen_b,
        }

    insights = []

    def add(kind, subject, title, body, score, evidence):
        insights.append({"kind": kind, "subject": subject, "title": title, "body": body,
                         "score": round(score, 3), "evidence": evidence})

    # ---- detector 1: momentum (acceleration / deceleration) ---------------
    accel, decel = [], []
    for s in sigs:
        st = stats[s["slug"]]
        if st["recent_count"] < 15:
            continue
        lift = st["lift"]
        if lift is None and not st["new"]:
            continue
        ev = {"slug": s["slug"], "papers": _top_papers_for_signal(s["slug"], recent_weeks)}
        if (st["new"] or lift >= 1.25) and st["z"] >= 2.5:
            accel.append(s["slug"])
            dbl = st["doubling_weeks"]
            body = (f"近 {R} 周，{s['name']} 出现在 {pct(st['recent_share'])} 的论文中，"
                    f"此前 {B} 周平均为 {pct(st['base_share'])}（{lift:.2f}×）。" if lift else
                    f"{s['name']} 在近 {R} 周首次出现，共 {st['recent_count']} 篇。")
            if dbl and dbl < 52:
                body += f" 按近 12 周的对数斜率，占比约每 {dbl:.0f} 周翻一番。"
            rising = [cat_names[c] for c, v in st["cat_lift"].items() if v["lift"] and v["lift"] >= 1.2 and v["z"] >= 2]
            if rising:
                body += f" 上升集中在：{'、'.join(rising)}。"
            add("acceleration", s["slug"], f"{s['name']} 正在加速", body,
                math.log(lift if lift else 4) * math.sqrt(st["recent_count"]), ev)
        elif lift is not None and lift <= 0.8 and st["z"] <= -2.5:
            decel.append(s["slug"])
            add("deceleration", s["slug"], f"{s['name']} 热度回落",
                f"近 {R} 周占比 {pct(st['recent_share'])}，此前 {B} 周为 {pct(st['base_share'])}（{lift:.2f}×）。"
                f" 留意它是被新范式取代，还是已沉淀为默认工具而不再被单独提及。",
                -math.log(lift) * math.sqrt(st["recent_count"]) * 0.8, ev)

    # ---- detector 2: cross-field synchrony (the Jack Clark pattern) -------
    for s in sigs:
        st = stats[s["slug"]]
        rising = [c for c, v in st["cat_lift"].items() if v["lift"] and v["lift"] >= 1.25 and v["z"] >= 2]
        if len(rising) >= 3:
            names = "、".join(f"{cat_names[c]} {st['cat_lift'][c]['lift']:.1f}×" for c in rising)
            add("synchrony", s["slug"], f"{s['name']} 在 {len(rising)} 个领域同时上升",
                f"不是单一社区的热点：{names}。多个独立领域同步加速，往往意味着底层能力或工具发生了共性变化"
                f"——这正是 2016 年 GPU 出现在视觉、语音、游戏所有论文里时的形态。",
                len(rising) * 1.5 + min(math.log(max(st["lift"] or 1, 1)), 0.7) * 3
                + min(math.sqrt(st["recent_count"]) / 10, 1.5),
                {"slug": s["slug"], "cats": rising})

    # ---- detector 3: penetration / diffusion ------------------------------
    for s in sigs:
        st = stats[s["slug"]]
        if st["penetration"] > st["penetration_base"] and st["penetration"] >= 3:
            add("diffusion", s["slug"], f"{s['name']} 渗透到 {st['penetration']}/{len(cats)} 个领域",
                f"占比 ≥1% 的领域从 {st['penetration_base']} 个增加到 {st['penetration']} 个。"
                f"工具从一个社区扩散到多个社区，是它变成基础设施的早期信号。",
                (st["penetration"] - st["penetration_base"]) * 2.0 + st["penetration"] * 0.3,
                {"slug": s["slug"]})

    # ---- detector 4: leadership shift inside a competitive group ----------
    group = [s for s in sigs if s["grp"] == config.COMPETITIVE_GROUP]
    if group:
        rank_r = sorted(group, key=lambda s: -stats[s["slug"]]["recent_share"])
        rank_b = sorted(group, key=lambda s: -stats[s["slug"]]["base_share"])
        lead_r, lead_b = rank_r[0], rank_b[0]
        standings = "；".join(f"{s['name']} {pct(stats[s['slug']]['recent_share'])}" for s in rank_r[:5])
        if lead_r["slug"] != lead_b["slug"]:
            add("shift", config.COMPETITIVE_GROUP, f"基座模型格局变化：{lead_r['name']} 取代 {lead_b['name']}",
                f"按论文提及占比，近 {R} 周排名第一的是 {lead_r['name']}（此前 {B} 周是 {lead_b['name']}）。当前：{standings}。"
                f" 研究者用什么模型做实验，是比发布会更诚实的采用率指标。",
                6.0, {"slugs": [s["slug"] for s in rank_r]})
        else:
            movers = [s for s in group if rank_b.index(s) - rank_r.index(s) >= 2]
            for s in movers:
                add("shift", s["slug"], f"{s['name']} 在研究者中的使用排名上升",
                    f"排名从第 {rank_b.index(s) + 1} 升至第 {rank_r.index(s) + 1}。当前：{standings}。",
                    3.0 + rank_b.index(s) - rank_r.index(s), {"slugs": [x["slug"] for x in rank_r]})

    # ---- detector 5: emerging vocabulary -----------------------------------
    # Whole history, so a term can be told apart as new vs coming back.
    df, per_week = term_frequencies(weeks)
    terms = emerging_terms(df, per_week, recent_weeks, base_weeks)
    for t in terms[:6]:
        if t["status"] == "new":
            title = f"全新术语：“{t['term']}”"
            hist = f"自 {weeks[0]} 有数据以来从未出现过。新术语稳定出现，通常先于新子领域被命名。"
        elif t["status"] == "revival":
            title = f"术语回潮：“{t['term']}”"
            hist = (f"此前 {B} 周没有出现，但更早已有 {t['earlier']} 篇（最早 {t['first_week']} 周）："
                    f"这是一个方向重新升温，不是全新出现。")
        else:
            title = f"术语升温：“{t['term']}”"
            hist = f"此前 {B} 周已有 {t['base']} 篇，最早见于 {t['first_week']} 周。"
        add("emerging", t["term"], title,
            f"近 {R} 周 {t['recent']} 篇论文使用这个说法（相对基线 {t['lift']:.1f}×）。{hist}",
            t["score"], {"term": t["term"], "papers": _papers_with_term(t["term"], recent_weeks)})

    # ---- detector 6: submission volume -------------------------------------
    for c in cats:
        r = _mean([vol[c][i] or None for i in recent_idx])
        b = _mean([vol[c][i] or None for i in base_idx])
        if b and r / b >= 1.15:
            add("volume", c, f"{cat_names[c]}（{c}）投稿量增长 {(r / b - 1) * 100:.0f}%",
                f"近 {R} 周平均每周 {r:.0f} 篇，此前 {B} 周为 {b:.0f} 篇。短期激增常与会议截稿相关"
                f"（如 ICLR、ICRA、ICASSP），持续数月不回落才说明研究人力在向这里流动。",
                (r / b - 1) * 2.5, {"cat": c})

    # ---- detector 7: regime ------------------------------------------------
    if len(accel) >= 3:
        names = "、".join(sig_by[x]["name"] for x in accel[:6])
        add("regime", "regime", f"{len(accel)} 条曲线同时向上",
            f"同时加速的信号：{names}。减速的有 {len(decel)} 条。单条曲线上升可能是噪声，多条一起上升更值得写进年度判断。",
            len(accel) * 1.2, {"slugs": accel})

    # ---- theses: your own bets, re-scored every run ------------------------
    thesis_eval = []
    for th in db.q("SELECT * FROM theses ORDER BY id"):
        slugs = [x for x in json.loads(th["slugs"]) if x in stats]
        lifts = [stats[x]["lift"] for x in slugs if stats[x]["lift"]]
        avg = math.exp(_mean([math.log(l) for l in lifts])) if lifts else None
        if avg is None:
            verdict = "数据不足"
        elif (avg >= 1.1) == (th["stance"] == "up") and abs(math.log(avg)) >= math.log(1.1):
            verdict = "证据支持"
        elif abs(math.log(avg)) < math.log(1.1):
            verdict = "尚无变化"
        else:
            verdict = "证据相反"
        thesis_eval.append({**th, "slugs": slugs, "lift": avg, "verdict": verdict})
        if avg is not None:
            add("thesis", f"thesis-{th['id']}", f"你的判断「{th['text'][:28]}」：{verdict}",
                f"关联信号近 {R} 周相对此前 {B} 周的几何平均变化为 {avg:.2f}×（你预期{'上升' if th['stance'] == 'up' else '下降'}）。",
                4.0 + abs(math.log(avg)) * 4, {"slugs": slugs, "thesis_id": th["id"]})

    _persist_insights(insights, analysis_week)
    timeline = build_timeline(weeks, cats, sigs, series, n, vol, sampled, df, per_week)

    snap = {
        "ready": True,
        "generated_at": _now(),
        "analysis_week": analysis_week,
        "current_week": this_monday,
        "windows": {"recent": R, "base": B, "recent_weeks": recent_weeks, "base_weeks": base_weeks},
        "weeks": weeks,
        "categories": [{"id": c, "name": cat_names[c]} for c in cats],
        "signals": [{k: s[k] for k in ("slug", "name", "grp", "pattern", "description", "custom")} for s in sigs],
        "series": series,
        "stats": stats,
        "volume": vol,
        "sampled": sampled,
        "papers_per_cat": n,
        "emerging": terms,
        "timeline": timeline,
        "theses": thesis_eval,
    }
    db.kv_set("snapshot", snap)
    return snap


def _persist_insights(items, week):
    """Upsert this run's cards for `week`; drop untouched cards from earlier runs that no longer fire."""
    ts = _now()
    keep = {(it["kind"], it["subject"]) for it in items}
    with db.tx() as c:
        for row in c.execute("SELECT id, kind, subject FROM insights WHERE week=? AND status='new'", (week,)).fetchall():
            if (row["kind"], row["subject"]) not in keep:
                c.execute("DELETE FROM insights WHERE id=?", (row["id"],))
        for it in items:
            c.execute(
                "INSERT INTO insights(kind, subject, week, title, body, score, evidence, first_seen, updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(kind, subject, week) DO UPDATE SET "
                "title=excluded.title, body=excluded.body, score=excluded.score, evidence=excluded.evidence, "
                "updated_at=excluded.updated_at",
                (it["kind"], it["subject"], week, it["title"], it["body"], it["score"],
                 json.dumps(it["evidence"], ensure_ascii=False), ts, ts),
            )


def build_timeline(weeks, cats, sigs, series, n, vol, sampled, df, per_week):
    """One entry per week: what moved that week relative to its own trailing 8 weeks."""
    out = []
    sig_by = {s["slug"]: s for s in sigs}
    for i, w in enumerate(weeks):
        lo = max(0, i - 8)
        risers = []
        for s in sigs:
            ser = series[s["slug"]]
            cur = ser["share"][i]
            prev = _mean(ser["share"][lo:i])
            if cur is None or i < 3 or ser["count"][i] < 5 or not prev:
                continue
            risers.append({"slug": s["slug"], "name": s["name"], "share": cur, "prev": prev, "lift": cur / prev})
        risers.sort(key=lambda x: -x["lift"])
        hot = {r["slug"]: math.log(r["lift"]) for r in risers if r["lift"] > 1}

        week_terms = []
        prior_weeks = weeks[lo:i]
        if df and prior_weeks and per_week.get(w):
            n_w = per_week[w]
            n_p = sum(per_week[x] for x in prior_weeks) or 1
            for t, c in df.items():
                d = c.get(w, 0)
                if d < max(4, 0.003 * n_w):
                    continue
                d_p = sum(c.get(x, 0) for x in prior_weeks)
                lift = (d / n_w) / ((d_p + 1) / (n_p + 1))
                if lift >= 2.5:
                    week_terms.append({"term": t, "count": d, "lift": lift, "score": math.sqrt(d) * math.log(lift)})
            week_terms.sort(key=lambda x: -x["score"])
            picked = []
            for t in week_terms:
                if any(t["term"] in o["term"] or o["term"] in t["term"] for o in picked):
                    continue
                picked.append(t)
                if len(picked) >= 5:
                    break
            week_terms = picked

        notable = []
        if hot:
            marks = ",".join("?" * len(hot))
            rows = db.q(f"SELECT p.id, p.title, p.primary_cat, GROUP_CONCAT(ps.slug) slugs FROM papers p "
                        f"JOIN paper_signal ps ON ps.paper_id=p.id WHERE p.week=? AND ps.slug IN ({marks}) "
                        f"GROUP BY p.id", (w, *hot))
            for r in rows:
                sl = r["slugs"].split(",")
                r["score"] = sum(hot[x] for x in sl)
                r["signals"] = [sig_by[x]["name"] for x in sl]
            rows.sort(key=lambda r: -r["score"])
            notable = [{k: r[k] for k in ("id", "title", "primary_cat", "signals")} for r in rows[:4]]

        out.append({
            "week": w,
            "papers": sum(n[c][i] for c in cats),
            "volume": sum(vol[c][i] or 0 for c in cats),
            "sampled": bool(sampled[i]),
            "risers": risers[:4],
            "terms": week_terms,
            "notable": notable,
        })
    return out
