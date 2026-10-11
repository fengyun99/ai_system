# -*- coding: utf-8 -*-
"""模型连通性自检——检查 model-config.json 各条目（chat / embeddings）是否可用。

用法：.venv/Scripts/python.exe scripts/check_models.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.rag import llm  # noqa: E402  （加载即完成 Enc[] 解密）


def check_chat(entry) -> tuple[bool, str]:
    try:
        resp = httpx.post(
            f"{entry.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {entry.next_key()}"},
            json={"model": entry.model,
                  "messages": [{"role": "user", "content": "回复OK"}],
                  "max_tokens": 8},
            timeout=20,
        )
        if resp.status_code == 200:
            content = resp.json()["choices"][0]["message"]["content"] or ""
            return True, f"模型 {entry.model} 应答: {content[:12]!r}"
        return False, f"HTTP {resp.status_code}: {resp.text[:120]}"
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"


def check_embeddings(entry) -> tuple[bool, str]:
    model = entry.embeddings_model or entry.model
    try:
        resp = httpx.post(
            f"{entry.base_url}/embeddings",
            headers={"Authorization": f"Bearer {entry.next_key()}"},
            json={"model": model, "input": "公积金"},
            timeout=20,
        )
        if resp.status_code == 200:
            dims = len(resp.json()["data"][0]["embedding"])
            return True, f"模型 {model} 维度 {dims}"
        return False, f"HTTP {resp.status_code}: {resp.text[:120]}"
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"


def main() -> int:
    entries = llm.load_model_config()
    print(f"共 {len(entries)} 个条目：\n")
    all_ok = True
    for key, e in entries.items():
        emb_model = e.embeddings_model or e.model
        if "embedding" not in e.model:
            chat_ok, chat_msg = check_chat(e)
            line = f"[{'✅' if chat_ok else '❌'}] {key:12} chat      {chat_msg}"
            print(line)
            all_ok &= chat_ok
        else:
            print(f"[➖] {key:12} chat      跳过（纯向量条目）")
        if "embedding" in emb_model or key == "embeddings":
            emb_ok, emb_msg = check_embeddings(e)
            print(f"[{'✅' if emb_ok else '❌'}] {key:12} embeddings {emb_msg}")
            all_ok &= emb_ok
    if not all_ok:
        print("\n⚠️ 存在不可用条目：把有效的 DeepSeek key 明文填入 config/model-config.json 的 api_key 数组"
              "\n   （首次启动自动加密为 Enc[...]），然后重启后端并重跑本脚本。")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
