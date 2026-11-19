# -*- coding: utf-8 -*-
"""大模型调用层：OpenAI 兼容接口（通义千问 DashScope）+ 离线假模型。

只用标准库 urllib，不额外装 openai 包，换模型只需改 .env 里的
LLM_BASE_URL / LLM_MODEL —— 兼容 vLLM、Ollama、DeepSeek、Moonshot 等。
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional

from ..config import LLM, LLMConfig


class LLMError(RuntimeError):
    """模型调用失败（网络、鉴权、限流、返回格式）。"""


@dataclass
class LLMReply:
    text: str
    model: str = ""
    elapsed_ms: float = 0.0
    source: str = ""

    def __str__(self) -> str:  # pragma: no cover - 便于调试
        return self.text


class BaseLLM:
    name = "base"
    model = ""

    def available(self) -> bool:  # pragma: no cover - 抽象
        return False

    def chat(self, messages: list[dict], temperature: Optional[float] = None) -> LLMReply:
        raise NotImplementedError

    def describe(self) -> dict:
        return {"name": self.name, "model": self.model, "available": self.available()}


class OpenAICompatLLM(BaseLLM):
    """任何 OpenAI Chat Completions 兼容服务都能用。"""

    name = "openai-compatible"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        timeout: int | None = None,
    ) -> None:
        cfg = LLM
        self.api_key = (api_key if api_key is not None else cfg.api_key).strip()
        self.base_url = (base_url or cfg.base_url).rstrip("/")
        self.model = model or cfg.model
        self.temperature = cfg.temperature if temperature is None else temperature
        self.timeout = timeout or cfg.timeout

    def available(self) -> bool:
        return bool(self.api_key) and self.model != ""

    @property
    def endpoint(self) -> str:
        base = self.base_url
        if base.endswith("/chat/completions"):
            return base
        return base + "/chat/completions"

    def chat(self, messages: list[dict], temperature: Optional[float] = None) -> LLMReply:
        if not self.available():
            raise LLMError(
                "未配置 LLM_API_KEY，无法调用真实模型。请在 .env 里填写 DASHSCOPE_API_KEY，"
                "或使用 --fake 离线模式。"
            )
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature if temperature is None else temperature,
        }
        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:400]
            raise LLMError(f"模型接口返回 HTTP {exc.code}：{detail}") from exc
        except urllib.error.URLError as exc:
            raise LLMError(f"无法访问模型接口 {self.endpoint}：{exc.reason}") from exc
        except TimeoutError as exc:
            raise LLMError(f"调用模型超时（{self.timeout}s）") from exc

        elapsed = (time.perf_counter() - started) * 1000
        try:
            data = json.loads(body)
            text = data["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError) as exc:
            raise LLMError(f"模型返回格式异常：{body[:300]}") from exc
        return LLMReply(text=text, model=self.model, elapsed_ms=elapsed, source=self.name)


def build_llm(
    mode: str | None = None,
    dictionary=None,
    cfg: Optional[LLMConfig] = None,
    verbose: bool = True,
) -> tuple[BaseLLM, str]:
    """按配置返回 (llm, 说明)。auto 时有 key 用真模型，没 key 自动用离线规则模型。"""
    cfg = cfg or LLM
    mode = (mode or cfg.mode or "auto").lower()

    if mode in {"real", "openai", "llm"}:
        llm = OpenAICompatLLM()
        if not llm.available():
            raise LLMError("LLM_MODE=real 但没有配置 LLM_API_KEY / DASHSCOPE_API_KEY")
        note = f"使用真实大模型：{llm.model} @ {llm.base_url}"
        if verbose:
            print(note)
        return llm, note

    from .fake import FakeLLM  # 延迟导入，避免循环依赖

    if mode == "fake":
        llm = FakeLLM(dictionary)
        note = "使用离线规则模型（不调用外部 API，效果等价于固定模板的 Text2Cypher）"
        if verbose:
            print(note)
        return llm, note

    if cfg.use_llm and cfg.api_key:
        llm = OpenAICompatLLM()
        note = f"使用真实大模型：{llm.model} @ {llm.base_url}"
        if verbose:
            print(note)
        return llm, note

    llm = FakeLLM(dictionary)
    note = "未检测到 LLM_API_KEY，自动使用离线规则模型（可用于无网络的课堂演示）"
    if verbose:
        print(note)
    return llm, note