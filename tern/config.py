"""Static configuration: tracked arXiv categories and default signal trackers.

A "signal" is a named regex over title + abstract. Its weekly share of papers is
the time series Tern watches — the same move Jack Clark made by hand when he
turned printed arXiv papers into capability charts.
"""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("TERN_DATA_DIR", ROOT / "data"))
DB_PATH = DATA_DIR / "tern.db"
WEB_DIR = ROOT / "web"

HOST = os.environ.get("TERN_HOST", "127.0.0.1")
PORT = int(os.environ.get("TERN_PORT", "8787"))
# When exposed through a Cloudflare tunnel: comma-separated client IPs allowed in.
# Tunnel requests carry Cf-Connecting-IP (set by Cloudflare's edge); requests
# without it come straight from this machine and are always allowed.
ALLOW_IPS = {s.strip() for s in os.environ.get("TERN_ALLOW_IPS", "").split(",") if s.strip()}

# Deployment split (single writer): the local instance fetches, analyzes and publishes a
# copy of the database to R2; the online instance is read-only and serves that copy.
# TERN_PUBLISH_R2 = "<bucket>" on the writer; TERN_READONLY = 1 on the online reader.
PUBLISH_R2 = os.environ.get("TERN_PUBLISH_R2", "")
PUBLISH_KEY = "tern.db"
READONLY = os.environ.get("TERN_READONLY") == "1"
# Absolute site URL for canonical links and the sitemap; empty = derived from the Host header.
PUBLIC_URL = os.environ.get("TERN_PUBLIC_URL", "")

# Local hour at which the daily fetch runs.
DAILY_HOUR = int(os.environ.get("TERN_DAILY_HOUR", "7"))
# First-run backfill: how many past weeks, and how many papers sampled per
# (category, week). Each (category, week) costs two arXiv API calls.
BACKFILL_WEEKS = int(os.environ.get("TERN_BACKFILL_WEEKS", "26"))
BACKFILL_PER_WEEK = int(os.environ.get("TERN_BACKFILL_PER_WEEK", "240"))
# Daily fetch: minimum window (days; normally it resumes from the last run) and per-category cap.
DAILY_LOOKBACK_DAYS = 3
DAILY_CAP_PER_CAT = 1500  # per 3 days of window
# A missed daily run is caught up on the next one, up to this many days back.
DAILY_MAX_CATCHUP_DAYS = 21

# arXiv asks for at most one request every 3 seconds.
ARXIV_API = "https://export.arxiv.org/api/query"
ARXIV_MIN_INTERVAL = 3.5

CATEGORIES = [
    ("cs.LG", "机器学习"),
    ("cs.CL", "语言"),
    ("cs.CV", "视觉"),
    ("cs.AI", "AI 综合"),
    ("cs.RO", "机器人"),
    ("eess.AS", "语音/音频"),
]

# group -> [(slug, name, regex, description)]
DEFAULT_SIGNALS = {
    "算力与硬件": [
        ("nvidia-gpu", "Nvidia GPU", r"\bnvidia\b|\b[ahbl]100s?\b|\bh200\b|\bgb?200\b|\bb200\b|\bcuda\b|\brtx ?\d{4}\b",
         "论文明确提到 Nvidia 硬件——Jack Clark 2016 年看到的那条线"),
        ("gpu-hours", "GPU 小时 / 训练成本", r"gpu[- ]hours?|gpu[- ]days?|training (cost|budget)|\bflops?\b|petaflop",
         "论文报告算力开销"),
        ("tpu-other-accel", "TPU 与其他加速器", r"\btpus?\b|\btrainium\b|\bnpus?\b|\bascend\b|\bgaudi\b|\bmi300",
         "非 Nvidia 加速器"),
        ("efficiency", "量化 / 端侧推理", r"quantiz|\bint4\b|\bint8\b|on-device|edge device|low-bit|pruning",
         "让模型跑在更少算力上"),
    ],
    "方法范式": [
        ("agents", "智能体", r"\bagent(s|ic)?\b|tool[- ]use|tool[- ]calling|computer[- ]use",
         "LLM 驱动的自主体与工具调用"),
        ("reasoning-rl", "推理与 RL 后训练", r"chain[- ]of[- ]thought|test[- ]time (compute|scaling)|\brlvr\b|\bgrpo\b|reasoning model|long cot|reinforcement learning with verifiable",
         "推理链、测试时算力、可验证奖励 RL"),
        ("diffusion", "扩散模型", r"\bdiffusion\b|flow matching|score[- ]based",
         "扩散 / flow matching 生成模型"),
        ("moe", "混合专家 MoE", r"mixture[- ]of[- ]experts|\bmoe\b",
         "稀疏专家架构"),
        ("ssm", "状态空间 / 线性注意力", r"\bmamba\b|state[- ]space model|linear attention|\brwkv\b",
         "Transformer 之外的序列架构"),
        ("world-models", "世界模型", r"world models?",
         "学习环境动力学的模型"),
        ("vla", "VLA / 具身基础模型", r"vision[- ]language[- ]action|\bvlas?\b|embodied (foundation|agent)|robot foundation model",
         "机器人基础模型"),
        ("multimodal", "多模态大模型", r"\bvlms?\b|\bmllms?\b|multimodal large language|vision[- ]language model|large multimodal",
         "视觉-语言等多模态 LLM"),
        ("rag", "检索增强 RAG", r"retrieval[- ]augmented|\brag\b",
         "检索增强生成"),
        ("synthetic-data", "合成数据", r"synthetic data|data synthesis|self[- ]generated data|distill",
         "合成数据与蒸馏"),
        ("long-context", "长上下文", r"long[- ]context|context window|million tokens|\b1m tokens",
         "长上下文建模"),
    ],
    "安全与评测": [
        ("safety", "对齐与安全", r"\balignment\b|jailbreak|red[- ]teaming|ai safety|harmful|reward hacking|deceptive",
         "对齐、越狱与风险"),
        ("interp", "可解释性", r"interpretability|sparse autoencoder|\bsaes?\b|circuit|mechanistic|probing",
         "机制可解释性"),
        ("benchmark", "新基准", r"we (introduce|present|propose) [^.]{0,60}benchmark|new benchmark|benchmark for",
         "提出新 benchmark——旧的被打穿的旁证"),
        ("human-level", "超越人类", r"human[- ]level|surpass(es|ing)? human|superhuman|expert[- ]level",
         "声称达到或超过人类水平"),
    ],
    "基座模型": [
        ("m-llama", "Llama", r"\bllama[- ]?\d?", "论文使用 / 提到 Llama"),
        ("m-qwen", "Qwen", r"\bqwen", "论文使用 / 提到 Qwen"),
        ("m-deepseek", "DeepSeek", r"deepseek", "论文使用 / 提到 DeepSeek"),
        ("m-gpt", "GPT", r"\bgpt-?[45o]|\bchatgpt|\bo[134](-mini)?\b", "论文使用 / 提到 OpenAI GPT"),
        ("m-claude", "Claude", r"\bclaude\b", "论文使用 / 提到 Claude"),
        ("m-gemini", "Gemini", r"\bgemini\b|\bgemma\b", "论文使用 / 提到 Gemini / Gemma"),
        ("m-mistral", "Mistral", r"\bmistral\b|\bmixtral\b", "论文使用 / 提到 Mistral"),
    ],
}

# Group whose members compete for the same slot; used by the "leadership shift" detector.
COMPETITIVE_GROUP = "基座模型"
