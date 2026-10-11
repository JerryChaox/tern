"""Optional weekly analyst memo written by Claude from the computed snapshot.

Runs only when the `anthropic` package is installed and credentials resolve
(ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN, or an `ant auth login` profile).
Every other part of Tern works without it.
"""

import json

from . import db

MODEL = "claude-opus-5-5"

PROMPT = """你是一名像 2016 年的 Jack Clark 那样工作的 AI 研究分析员：不追新闻，只读论文数据，
从所有人都能看到的公开信息里找出还没被意识到的重要性。

下面是 arXiv 论文的统计快照（信号 = 正则匹配的主题，share = 占当周论文比例，lift = 近期 / 基线）。
请写一份中文周度研究备忘录，要求：
1. 开头一句话给出本周最重要的判断。
2. 3–5 条发现，每条引用具体数字，并区分「数据显示」与「我的推断」。
3. 一条「可能被忽视的信号」：指标变化不大但含义重大的东西，或多个领域的共性变化。
4. 一条「未来 6–12 个月可检验的预测」，写清楚什么数据会证伪它。
5. 不超过 450 字，Markdown，不要开场白。

数据：
{data}
"""


def available():
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return True


def _digest(snap):
    names = {s["slug"]: s["name"] for s in snap["signals"]}
    sigs = []
    for slug, st in snap["stats"].items():
        sigs.append({"signal": names[slug], "recent_share": round(st["recent_share"], 4),
                     "base_share": round(st["base_share"], 4), "lift": st["lift"] and round(st["lift"], 2),
                     "recent_papers": st["recent_count"], "fields_rising": [
                         c for c, v in st["cat_lift"].items() if v["lift"] and v["lift"] >= 1.25 and v.get("z", 0) >= 2]})
    sigs.sort(key=lambda x: -(x["lift"] or 0))
    insights = db.q("SELECT kind, title, body FROM insights WHERE week=? ORDER BY score DESC LIMIT 12",
                    (snap["analysis_week"],))
    return json.dumps({"week": snap["analysis_week"], "windows": snap["windows"], "signals": sigs,
                       "emerging_terms": [{"term": t["term"], "recent": t["recent"], "base": t["base"]}
                                          for t in snap["emerging"]],
                       "insights": insights}, ensure_ascii=False)


def generate(snap):
    import anthropic

    client = anthropic.Anthropic()
    resp = client.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        output_config={"effort": "medium"},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        messages=[{"role": "user", "content": PROMPT.format(data=_digest(snap))}],
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError("Claude declined to write the memo")
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    memo = {"week": snap["analysis_week"], "model": resp.model, "text": text}
    db.kv_set(f"memo:{snap['analysis_week']}", memo)
    return memo
