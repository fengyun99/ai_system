# -*- coding: utf-8 -*-
"""意图路由仿真测试：批量真实客户话术 → 校验意图识别不误判。

覆盖 rag / business / chitchat / off_topic 四意图全外延 + 边界混合句
（问候+实质、感谢+实质、投诉+具体业务、情绪宣泄无诉求——2026-09-28 修复回归）。
只调意图识别函数（rewrite.recognize_intent），不跑检索/工具/生成管线。

用法：.venv/Scripts/python scripts/intent_test.py
前置：model-config.json 已配有效 key；无需 DB/ES。
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.rag import llm  # noqa: E402
from app.rag.llm import TokenMeter  # noqa: E402
from app.rag.rewrite import recognize_intent  # noqa: E402
from app.settings import get_settings  # noqa: E402

# (期望意图集合, 话术, 说明)。期望为集合的条目是业务上双解均可接受的边界句。
CASES: list[tuple[set[str], str, str]] = [
    # ---------- rag：政策/业务知识咨询 ----------
    ({"rag"}, "公积金贷款最高能贷多少", ""),
    ({"rag"}, "租房提取公积金需要准备什么材料", ""),
    ({"rag"}, "离职后公积金怎么处理", ""),
    ({"rag"}, "商业贷款可以转公积金贷款吗？条件是什么", ""),
    ({"rag"}, "公积金缴存比例是多少", ""),
    ({"rag"}, "提前还款有没有违约金", ""),
    ({"rag"}, "公积金能异地转移吗", ""),
    ({"rag"}, "福州的贷款额度和泉州一样吗", ""),
    ({"rag"}, "什么情况可以销户提取", ""),
    ({"rag"}, "公积金账户里的钱有利息吗", ""),
    ({"rag"}, "你们公积金中心的电话是多少", "机构信息咨询"),

    # ---------- business：本人业务办理/查询 ----------
    ({"business"}, "查一下我的公积金余额", ""),
    ({"business"}, "我要查我的贷款还剩多少", ""),
    ({"business"}, "帮我看看这个月缴存到账没有", ""),
    ({"business"}, "我要办理租房提取", ""),
    ({"business"}, "我想提前还款一部分", ""),
    ({"business"}, "帮我查下我的缴存明细", ""),
    ({"business"}, "我要修改还款银行卡", ""),
    ({"business"}, "打印一份缴存证明", ""),

    # ---------- chitchat：无实质业务诉求的社交与情绪 ----------
    ({"chitchat"}, "你好", "问候"),
    ({"chitchat"}, "在吗？", "在场确认"),
    ({"chitchat"}, "谢谢啦", "感谢"),
    ({"chitchat"}, "再见", "告别"),
    ({"chitchat"}, "好的，知道了", "附和承接"),
    ({"chitchat"}, "你是真人还是机器人", "身份询问"),
    ({"chitchat"}, "你都能帮我做什么", "能力询问"),
    ({"off_topic"}, "讲个笑话听听", "内容请求→off_topic(与推荐电影一致)"),
    ({"chitchat"}, "测试", "探活"),
    ({"chitchat"}, "气死了，我要投诉你们！", "情绪宣泄(修复回归)"),
    ({"chitchat"}, "我要投诉你们网点工作人员态度很差", "服务投诉无办理诉求"),

    # ---------- off_topic：与公积金无关的实质问题 ----------
    ({"off_topic"}, "今天天气怎么样", ""),
    ({"off_topic"}, "帮我写一段Python排序代码", ""),
    ({"off_topic"}, "最近股市行情如何", ""),
    ({"off_topic"}, "推荐几部好看的电影", ""),
    ({"off_topic"}, "北京有什么好玩的地方", ""),

    # ---------- 边界/混合 ----------
    ({"rag"}, "你好，请问公积金怎么提取", "问候+实质→rag"),
    ({"rag"}, "谢谢，对了公积金贷款利率是多少", "感谢+实质→rag"),
    ({"chitchat"}, "我的提取申请被拒了，我要投诉", "投诉情绪优先安抚,不查数据"),
    ({"rag", "business"}, "我的提取申请为什么被拒了？", "具体业务疑问→rag/business"),
    ({"business"}, "帮我查一下我老婆的公积金余额", "查询诉求(他人,工具层拒绝)"),
]


async def main() -> int:
    llm.load_model_config()
    chat_key = get_settings()["rag"].get("chat_key", "deepseek")
    print(f"[intent_test] 路由模型={chat_key} 用例={len(CASES)} 条\n")
    fails: list[tuple[str, str, set[str]]] = []
    for i, (expect, q, note) in enumerate(CASES, 1):
        meter = TokenMeter()
        try:
            r = await recognize_intent(q, "", chat_key, meter)
        except Exception as e:  # noqa: BLE001
            print(f"❌ [{i:02d}] {q} → 调用异常: {e}")
            fails.append((q, f"异常:{e}", expect))
            continue
        got, reason = r["intent"], r.get("reason", "")
        ok = got in expect
        mark = "✅" if ok else "❌"
        extra = f"（{note}）" if note else ""
        print(f"{mark} [{i:02d}] {q} {extra}\n      → {got}  期望{'/'.join(sorted(expect))}  依据: {reason[:50]}")
        if not ok:
            fails.append((q, got, expect))
    print(f"\n===== 意图路由仿真：{len(CASES) - len(fails)}/{len(CASES)} 通过 =====")
    if fails:
        print("误判清单：")
        for q, got, expect in fails:
            print(f"  - {q} → {got}（期望 {'/'.join(sorted(expect))}）")
    return 0 if not fails else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
