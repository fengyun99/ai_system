# -*- coding: utf-8 -*-
"""回答生成：RAG 提示词构建 + 流式生成 + 充分性判断与拒答。"""
from __future__ import annotations

import datetime

from app.rag import llm

SYSTEM_PROMPT = """你是住房公积金中心的专业智能客服"小金"，面向缴存职工解答公积金政策与业务问题。

当前日期：{current_date}

回答要求：
1. 只依据下方材料作答，不编造政策口径；材料未覆盖时如实说明并建议拨打 12329 咨询；
2. 涉及金额/比例/期限等数字必须与材料一致，不得自行计算推广；
3. 分点作答、简明准确，使用 Markdown；引用公开网络材料时，在句末标注来源标题；
4. 结尾不需要客套话。

{business_sense_block}
材料（知识库片段 + 联网检索结果，按相关性降序）：
{context}"""

REFUSE_TEXT = ("抱歉，**当前内容暂时不支持回答**，为避免误导我不作推测性解答。\n\n"
               "您可以：\n"
               "- 换个说法再问一次（例如补充业务类型或所在城市）；\n"
               "- 需要人工帮助时，可点击页面右下角 **转人工** 接入在线坐席（9:00-17:00），"
               "或拨打住房公积金服务热线 **12329**。")

WEB_EMPTY_REFUSE_TEXT = ("抱歉，知识库与联网检索均未找到与您问题直接相关的信息，**当前内容暂时不支持回答**。\n\n"
                         "建议您点击页面右下角 **转人工** 接入在线坐席（9:00-17:00），"
                         "或拨打住房公积金服务热线 **12329** 核实。")

EXTERNAL_REFUSE_TEXT = ("您咨询的地区暂不在本中心服务范围内（当前仅支持福建省内公积金业务），"
                        "且联网补充当前不可用，**当前内容暂时不支持回答**。\n\n"
                        "您可以选择 **转人工** 服务，由坐席为您对接咨询当地政策。")

OFF_TOPIC_REFUSE_TEXT = ("抱歉，我是住房公积金智能客服，**只能回答与住房公积金相关的问题**"
                         "（如缴存、提取、贷款、转移、账户查询等）。\n\n"
                         "如果您有公积金方面的问题，欢迎随时提问；若需要人工帮助，"
                         "可点击 **转人工** 接入在线坐席或拨打 **12329**。")


def build_context(materials: list[dict]) -> str:
    blocks = []
    for i, m in enumerate(materials, 1):
        if m.get("source") == "web":
            blocks.append(f"联网材料{i}（来源：{m.get('title', '')} · {m.get('url', '')}）\n"
                          f"{m.get('text', '')}\n" + "=" * 30)
        else:
            blocks.append(f"知识片段{i}（来源：{m.get('title', '')}）\n{m.get('text', '')}\n" + "=" * 30)
    return "\n".join(blocks)


def build_messages(question: str, materials: list[dict],
                   history: list[dict] | None = None) -> list[dict]:
    now = datetime.datetime.now().strftime("%Y年%m月%d日")
    msgs = [{"role": "system", "content": SYSTEM_PROMPT.format(
        current_date=now, context=build_context(materials), business_sense_block="",
    )}]
    for h in (history or [])[-6:]:      # 近 3 轮
        if h.get("question"):
            msgs.append({"role": "user", "content": h["question"]})
        if h.get("answer"):
            msgs.append({"role": "assistant", "content": h["answer"]})
    msgs.append({"role": "user", "content": question})
    return msgs


def judge_sufficient(materials: list[dict]) -> bool:
    """材料充分性（快速规则版）：至少 1 条候选且非空即充分，交给生成端严格引用。"""
    return bool(materials)
