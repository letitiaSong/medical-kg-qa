# -*- coding: utf-8 -*-
"""全局配置与 .env 加载。

作业要求（实验3）强调"配置大模型 API 接口"和"TuGraph 与本地 Python 连接"，
因此所有连接参数统一从环境变量读取，代码里不写死任何密钥。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
OUTPUT_DIR = PROJECT_ROOT / "outputs"
DOCS_DIR = PROJECT_ROOT / "docs"


def _load_dotenv(path: Path = PROJECT_ROOT / ".env") -> None:
    """极简 .env 解析（避免强依赖 python-dotenv，装不上也能跑）。"""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv()


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


def _env_bool(key: str, default: bool = False) -> bool:
    v = _env(key, "1" if default else "0").lower()
    return v in {"1", "true", "yes", "on"}


@dataclass
class TuGraphConfig:
    host: str = field(default_factory=lambda: _env("TUGRAPH_HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: int(_env("TUGRAPH_PORT", "7070")))
    user: str = field(default_factory=lambda: _env("TUGRAPH_USER", "admin"))
    password: str = field(default_factory=lambda: _env("TUGRAPH_PASSWORD", "73@TuGraph"))
    graph: str = field(default_factory=lambda: _env("TUGRAPH_GRAPH", "medical_course_2026"))
    # auto: 先试 REST，失败自动退到 mock；rest: 只连真库；mock: 只用离线模拟库
    mode: str = field(default_factory=lambda: _env("TUGRAPH_MODE", "auto").lower())
    timeout: int = 15

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def cypher_url(self) -> str:
        return f"{self.base_url}/cypher"

    def masked(self) -> dict:
        return {
            "host": self.host,
            "port": self.port,
            "user": self.user,
            "password": "***" if self.password else "",
            "graph": self.graph,
            "mode": self.mode,
        }


@dataclass
class LLMConfig:
    api_key: str = field(default_factory=lambda: _env("DASHSCOPE_API_KEY", ""))
    base_url: str = field(
        default_factory=lambda: _env(
            "DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
        )
    )
    model: str = field(default_factory=lambda: _env("QWEN_MODEL", "qwen-plus"))
    temperature: float = field(default_factory=lambda: float(_env("QWEN_TEMPERATURE", "0.0")))
    timeout: int = field(default_factory=lambda: int(_env("QWEN_TIMEOUT", "60")))
    # auto: 有 key 用真模型，没有就走离线假模型；real 强制真；fake 强制离线
    mode: str = field(default_factory=lambda: _env("LLM_MODE", "auto").lower())

    @property
    def use_llm(self) -> bool:
        if self.mode == "fake":
            return False
        if self.mode == "real":
            return True
        return bool(self.api_key)

    def masked(self) -> dict:
        key = self.api_key
        return {
            "base_url": self.base_url,
            "model": self.model,
            "api_key": (key[:4] + "***" + key[-4:]) if len(key) > 8 else ("<未配置>"),
            "mode": self.mode,
        }


TUGRAPH = TuGraphConfig()
LLM = LLMConfig()

# ---- 图谱 Schema（作业要求：5 类节点、4 类关系）----
LABELS = ["Disease", "Symptom", "Drug", "Department", "Examination"]
RELATIONS = ["HAS_SYMPTOM", "USES_DRUG", "BELONGS_TO", "REQUIRES_EXAM"]
# 情境性关系：规则/大模型可抽到"建议检查"，入库时统一映射为 REQUIRES_EXAM 并打 scope 标记
RELATION_ALIASES = {"RECOMMENDS_EXAM": "REQUIRES_EXAM"}

COMMON_PROPS = ["id", "name", "description"]

# ---- 数据文件位置 ----
RAW_QA = DATA_DIR / "raw" / "qa_medical_40.csv"
CLEAN_QA = DATA_DIR / "clean" / "qa_clean.csv"
ENTITY_DICT = DATA_DIR / "dict" / "medical_entities.csv"
NER_GOLD = DATA_DIR / "gold" / "ner_gold.csv"
RE_GOLD = DATA_DIR / "gold" / "re_gold.csv"
GRAPH_DIR = DATA_DIR / "graph"
DEMO_DIR = GRAPH_DIR / "demo"
T2C_TESTSET = DATA_DIR / "testset" / "t2c_testset.csv"
MOCK_STORE = OUTPUT_DIR / "mock_graph.json"


def ensure_dirs() -> None:
    for p in [
        DATA_DIR / "raw",
        DATA_DIR / "clean",
        DATA_DIR / "dict",
        DATA_DIR / "gold",
        GRAPH_DIR,
        DEMO_DIR,
        DATA_DIR / "testset",
        OUTPUT_DIR,
        DOCS_DIR,
        OUTPUT_DIR / "extraction",
    ]:
        p.mkdir(parents=True, exist_ok=True)