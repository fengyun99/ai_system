# -*- coding: utf-8 -*-
"""统一 LLM 网关——model-config.json 配置驱动，换模型=改配置不改代码。

对齐原服务三约定：
  1. api_key 支持多 key 轮询（itertools.cycle）；
  2. api_key 允许 Enc[...]（Java 同款 SM4-CTR）密文，明文首次加载自动加密回写；
  3. 聊天/向量/重排统一走 OpenAI 兼容协议（rerank 为 Cohere 扁平形）。
"""
from __future__ import annotations

import asyncio
import itertools
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncIterator

import httpx
import jwt as _jwt  # noqa: F401  (统一依赖面)
from langchain_openai import ChatOpenAI
from openai import AsyncOpenAI

from app.core.config_loader import encrypt_to_enc, _ENC_RE, CONFIG_DIR
from app.core.crypto import decrypt_enc_value
from app.settings import MODEL_CONFIG_PATH, get_settings


# ------------------------------------------------------------------
# model-config.json 加载（含 Enc[...] 自动升级回写）
# ------------------------------------------------------------------

@dataclass
class ModelEntry:
    key: str
    base_url: str
    api_keys: list[str]                 # 解密后的明文 key 池
    model: str
    embeddings_model: str = ""
    temperature: float | None = None
    price: dict = field(default_factory=dict)   # 元/1K tokens: {"input": x, "output": y}
    _cycles: dict = field(default_factory=dict)

    def next_key(self) -> str:
        if "chat" not in self._cycles:
            self._cycles["chat"] = itertools.cycle(self.api_keys)
        return next(self._cycles["chat"])


_ENTRIES: dict[str, ModelEntry] = {}


def load_model_config(path: Path | None = None) -> dict[str, ModelEntry]:
    """加载 model-config.json；api_key 为明文时自动加密回写（与 app.yml 行为一致）。"""
    global _ENTRIES
    path = path or MODEL_CONFIG_PATH
    raw = json.loads(path.read_text(encoding="utf-8"))
    upgraded = False
    entries: dict[str, ModelEntry] = {}
    for item in raw:
        keys = item.get("api_key") or []
        if isinstance(keys, str):
            keys = [keys]
        plain_keys = []
        for k in keys:
            m = _ENC_RE.match(k.strip())
            if m:
                plain_keys.append(decrypt_enc_value(m.group(1)))
            else:
                plain_keys.append(k)
                upgraded = True
        if upgraded:
            item["api_key"] = [encrypt_to_enc(k) for k in plain_keys]
        price = item.get("price") or {}
        entries[item["key"]] = ModelEntry(
            key=item["key"], base_url=item["base_url"].rstrip("/"),
            api_keys=plain_keys, model=item["model"],
            embeddings_model=item.get("embeddings_model", ""),
            temperature=item.get("temperature"),
            price={"input": float(price.get("input") or 0),
                   "output": float(price.get("output") or 0)},
        )
    if upgraded:
        path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    _ENTRIES = entries
    return entries


def get_entry(key: str) -> ModelEntry:
    if not _ENTRIES:
        load_model_config()
    if key not in _ENTRIES:
        raise KeyError(f"model-config.json 缺少 key={key} 条目")
    return _ENTRIES[key]


def price_of(model_name: str) -> tuple[float, float]:
    """按模型名查（元/1K tokens）两口价；未配置返回 (0, 0)——成本记 0，可由 token×现价补算。"""
    for e in _ENTRIES.values():
        if model_name in (e.model, e.embeddings_model):
            return (e.price.get("input", 0.0), e.price.get("output", 0.0))
    return (0.0, 0.0)


# ------------------------------------------------------------------
# token 记账
# ------------------------------------------------------------------

@dataclass
class TokenRow:
    stage: str          # intent/region/classify/decompose/retrieve/rerank/generate/tool
    model: str
    prompt_tokens: int
    completion_tokens: int
    estimated: int = 0  # 0=供应商 usage 真值 1=字符估算
    stage_no: int = 0   # 归属的阶段行号（stage_rows 序号）；0=未归属具体行


class TokenMeter:
    """一轮回答的 token 消耗合计（含缓存命中时按供应商真值）。

    行级记账：每笔记到具体阶段行（stage_no），落库按行精确回填；
    同一阶段行的多笔调用（如并行子任务）自动聚合到该行。
    """

    def __init__(self):
        self.rows: list[TokenRow] = []

    def add(self, stage: str, model: str, pt: int, ct: int, estimated: int = 0,
            stage_no: int = 0) -> None:
        if pt or ct:
            self.rows.append(TokenRow(stage, model, pt, ct, estimated, stage_no))

    def totals(self) -> tuple[int, int]:
        return (sum(r.prompt_tokens for r in self.rows),
                sum(r.completion_tokens for r in self.rows))

    def by_stage_no(self, stage_no: int) -> tuple[int, int, int]:
        """该阶段行的 (tokens_in, tokens_out, 含估算标记)。"""
        rows = [r for r in self.rows if r.stage_no == stage_no]
        return (sum(r.prompt_tokens for r in rows),
                sum(r.completion_tokens for r in rows),
                1 if any(r.estimated for r in rows) else 0)

    def _row_cost(self, r: TokenRow) -> float:
        pin, pout = price_of(r.model)
        return r.prompt_tokens / 1000 * pin + r.completion_tokens / 1000 * pout

    def cost_by_stage_no(self, stage_no: int) -> float:
        """该阶段行成本（元）——按调用时点的现价计算，落库即定格（ADR 0002）。"""
        return sum(self._row_cost(r) for r in self.rows if r.stage_no == stage_no)

    def total_cost(self) -> float:
        return sum(self._row_cost(r) for r in self.rows)


# ------------------------------------------------------------------
# 聊天（LangChain ChatOpenAI，流式含 usage）
# ------------------------------------------------------------------

_CHAT_MODELS: dict[str, ChatOpenAI] = {}


def get_chat_model(key: str, *, temperature: float = 0.1, streaming: bool = True) -> ChatOpenAI:
    cache_key = f"{key}:{temperature}:{streaming}"
    if cache_key not in _CHAT_MODELS:
        e = get_entry(key)
        kwargs = dict(
            model=e.model, api_key=e.next_key(), base_url=e.base_url + "/",
            temperature=e.temperature if e.temperature is not None else temperature,
            streaming=streaming, stream_usage=True,
            request_timeout=(10, 120), max_retries=2,
        )
        _CHAT_MODELS[cache_key] = ChatOpenAI(**kwargs)
    return _CHAT_MODELS[cache_key]


async def ainvoke_text(messages: list, key: str, meter: TokenMeter | None = None,
                        stage: str = "generate", stage_no: int = 0) -> str:
    """非流式调用，返回文本并记账。"""
    e = get_entry(key)
    model = get_chat_model(key, streaming=False)
    resp = await model.ainvoke(messages)
    usage = resp.usage_metadata or {}
    if meter:
        meter.add(stage, e.model,
                  usage.get("input_tokens", 0), usage.get("output_tokens", 0),
                  stage_no=stage_no)
    return (resp.content or "").strip()


async def astream_text(messages: list, key: str, meter: TokenMeter | None = None,
                       stage: str = "generate", stage_no: int = 0) -> AsyncIterator[str]:
    """流式调用：逐块产出文本，usage 在末块记账。"""
    e = get_entry(key)
    model = get_chat_model(key)
    pt = ct = 0
    async for chunk in model.astream(messages):
        usage = chunk.usage_metadata
        if usage:
            pt = usage.get("input_tokens", pt)
            ct = usage.get("output_tokens", ct)
        if chunk.content:
            yield chunk.content
    if meter:
        meter.add(stage, e.model, pt, ct, stage_no=stage_no)


async def ainvoke_json(messages: list, key: str, meter: TokenMeter | None = None,
                        stage: str = "generate", stage_no: int = 0) -> dict:
    """调用并解析 JSON 输出（提示词要求纯 JSON；容错剥 ``` 围栏）。"""
    text = await ainvoke_text(messages, key, meter, stage, stage_no)
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        # 二次容错：截取首个 { 到末个 }
        s, t = text.find("{"), text.rfind("}")
        if s >= 0 and t > s:
            return json.loads(text[s:t + 1])
        raise


# ------------------------------------------------------------------
# 向量（OpenAI 兼容 /embeddings）
# ------------------------------------------------------------------

_EMBED_CLIENTS: dict[str, AsyncOpenAI] = {}


async def embed_texts(texts: list[str], key: str, meter: TokenMeter | None = None,
                      stage: str = "retrieve", stage_no: int = 0) -> list[list[float]]:
    e = get_entry(key)
    if key not in _EMBED_CLIENTS:
        _EMBED_CLIENTS[key] = AsyncOpenAI(api_key=e.next_key(), base_url=e.base_url + "/")
    model_name = e.embeddings_model or e.model or "text-embedding-v1"
    resp = await _EMBED_CLIENTS[key].embeddings.create(model=model_name, input=texts)
    if meter:
        # 真值优先：OpenAI 兼容 /embeddings 响应带 usage.prompt_tokens；缺失/为 0 才按字符估算
        pt = int(getattr(resp.usage, "prompt_tokens", 0) or 0)
        if pt:
            meter.add(stage, model_name, pt, 0, stage_no=stage_no)
        else:
            meter.add(stage, model_name, sum(len(t) for t in texts), 0,
                      estimated=1, stage_no=stage_no)
    return [d.embedding for d in resp.data]


# ------------------------------------------------------------------
# 重排（Cohere 扁平形 OpenAI 兼容协议）
# ------------------------------------------------------------------

class RerankError(Exception):
    pass


def _rerank_char_estimate(query: str, documents: list[str]) -> int:
    """无 usage 可读时的字符估算口径（1 汉字≈1 token），成功兜底与失败路径共用。"""
    return len(query) + sum(len(d) for d in documents)


async def rerank_documents(query: str, documents: list[str], top_n: int,
                           timeout_ms: int = 3000, meter: TokenMeter | None = None,
                           stage: str = "rerank", stage_no: int = 0) -> list[tuple[int, float]]:
    """返回 [(原始下标, 相关性分)]；失败抛 RerankError，由调用方回退融合序（不阻塞回答）。"""
    e = get_entry(get_settings()["rag"].get("rerank_key", "rerank"))
    payload = {"model": e.model, "query": query, "documents": documents,
               "top_n": top_n, "return_documents": False}

    def _meter_failure() -> None:
        # 失败也是一次真实消耗：按字符估算记账后抛错
        if meter:
            meter.add(stage, e.model, _rerank_char_estimate(query, documents), 0,
                      estimated=1, stage_no=stage_no)

    try:
        async with httpx.AsyncClient(timeout=timeout_ms / 1000) as client:
            resp = await client.post(e.base_url, json=payload,
                                     headers={"Authorization": f"Bearer {e.next_key()}"})
    except httpx.HTTPError as exc:
        _meter_failure()
        raise RerankError(f"rerank 传输失败: {exc}") from exc
    if resp.status_code != 200:
        _meter_failure()
        raise RerankError(f"rerank HTTP {resp.status_code}: {resp.text[:200]}")
    body = resp.json()
    results = body.get("results")
    if results is None:
        _meter_failure()
        raise RerankError("rerank 响应缺 results")
    usage = body.get("usage") or {}
    if meter:
        pt = int(usage.get("prompt_tokens") or usage.get("total_tokens") or 0)
        if not pt:
            pt, estimated = _rerank_char_estimate(query, documents), 1
        else:
            estimated = 0
        meter.add(stage, e.model, pt, 0, estimated=estimated, stage_no=stage_no)
    return [(int(r["index"]), float(r["relevance_score"])) for r in results]
