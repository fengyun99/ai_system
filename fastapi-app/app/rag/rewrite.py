# -*- coding: utf-8 -*-
"""前置推理（Pre-answer）：意图识别 / 区域识别 / 问题分类 / 问题分化。

四者全部走结构化 JSON 输出的小模型调用；每次调用即一个独立登记阶段。
"""
from __future__ import annotations

from app.rag import llm

_INTENT_PROMPT = """你是公积金智能客服的路由器。判断用户问题的意图类别，只输出 JSON：
{{"intent": "rag|business|chitchat|off_topic", "reason": "一句话依据"}}
- rag：公积金政策/业务知识咨询（缴存、贷款、提取、转移等）
- business：用户要办理/查询自己的业务（含"我要查我的余额/我要办提取/我的贷款"等）；
  投诉/抱怨/情绪宣泄若未提出具体要查什么办什么，不算 business
- chitchat：面向客服的社交与情绪话语——问候/告别/感谢/在场确认(在吗)、
  附和(好的/嗯嗯)、问你是谁或能干什么、测试探活，
  以及投诉抱怨等情绪宣泄（如"气死了""我要投诉"，但没有具体业务问题）
- off_topic：与住房公积金无关的实质问题或内容请求（天气、股票、写代码、
  讲笑话、推荐电影、闲聊他人事务等）

历史对话（可能为空）：
{history}

用户问题：{question}"""

_REGION_PROMPT = """从用户问题中提取地区指向，只输出 JSON：
{{"region_name": "机构所在地名称或空串", "is_external": true/false}}
- 空串=is_external=false：未提及地区，按当前机构处理
- 提及本省城市（如 福州/泉州/厦门/省直）→ region_name=该名称，is_external=false
- 提及外省地区（如 北京/上海/成都）→ region_name=该名称，is_external=true

当前用户所属机构：{dept_name}
用户问题：{question}"""

_CLASSIFY_PROMPT = """对公积金问题做主题分类，只输出 JSON：
{{"theme": "deposit|loan|withdraw|other"}}
- deposit 缴存类（开户、缴存比例、汇补缴、封存）
- loan 贷款类（额度、利率、还款、商转公）
- withdraw 提取类（购房/租房/离职/销户提取、材料）
- other 其他（转移、异地、综合咨询）

问题：{question}"""

_DECOMPOSE_PROMPT = """把用户问题分解为 1-{max_sub} 个用于检索的子查询，只输出 JSON：
{{"sub_queries": ["..."]}}
- 单一问题保持原样（1 条）
- 复合问题拆成独立可检索的短句（口语转书面、补全省略主语）
- 子查询不要包含"我的/我要查"等个人指代（检索公共知识库）

用户问题：{question}"""


async def recognize_intent(question: str, history_text: str, chat_key: str,
                           meter: llm.TokenMeter, stage_no: int = 0) -> dict:
    data = await llm.ainvoke_json(
        [_user_msg(_INTENT_PROMPT.format(history=history_text or "（无）", question=question))],
        chat_key, meter, stage="intent", stage_no=stage_no)
    intent = data.get("intent", "rag")
    if intent not in ("rag", "business", "chitchat", "off_topic"):
        intent = "rag"
    return {"intent": intent, "reason": data.get("reason", "")}


_SUGGEST_PROMPT = """基于以下问答，推荐 3 个用户可能继续追问的公积金问题（口语化、简短、可直接检索）。
只输出 JSON：{{"questions": ["...", "...", "..."]}}
不要与已问问题重复。

已问：{question}
回答摘要：{answer}

知识片段主题参考：{topics}"""


async def suggest_questions(question: str, answer: str, materials: list[dict],
                            chat_key: str, meter: llm.TokenMeter, stage_no: int = 0) -> list[str]:
    """可能相关问题推荐（对齐原系统追问推荐）。失败返回空列表，不阻塞回答。"""
    topics = "；".join(sorted({(m.get("title") or "")[:24] for m in materials[:4]}))
    try:
        data = await llm.ainvoke_json(
            [_user_msg(_SUGGEST_PROMPT.format(question=question, answer=(answer or "")[:200],
                                              topics=topics or "（无）"))],
            chat_key, meter, stage="suggest", stage_no=stage_no)
        qs = [q.strip() for q in data.get("questions", []) if q and q.strip()]
        return qs[:3]
    except Exception:  # noqa: BLE001 推荐失败不影响回答
        return []


async def extract_region(question: str, dept_name: str, chat_key: str,
                         meter: llm.TokenMeter, stage_no: int = 0) -> dict:
    data = await llm.ainvoke_json(
        [_user_msg(_REGION_PROMPT.format(dept_name=dept_name, question=question))],
        chat_key, meter, stage="region", stage_no=stage_no)
    return {
        "region_name": (data.get("region_name") or "").strip(),
        "is_external": bool(data.get("is_external", False)),
    }


async def classify_theme(question: str, chat_key: str, meter: llm.TokenMeter,
                        stage_no: int = 0) -> dict:
    data = await llm.ainvoke_json(
        [_user_msg(_CLASSIFY_PROMPT.format(question=question))],
        chat_key, meter, stage="classify", stage_no=stage_no)
    theme = data.get("theme", "other")
    if theme not in ("deposit", "loan", "withdraw", "other"):
        theme = "other"
    return {"theme": theme}


async def decompose_question(question: str, chat_key: str, meter: llm.TokenMeter,
                             max_sub: int = 4, stage_no: int = 0) -> dict:
    data = await llm.ainvoke_json(
        [_user_msg(_DECOMPOSE_PROMPT.format(question=question, max_sub=max_sub))],
        chat_key, meter, stage="decompose", stage_no=stage_no)
    subs = [q.strip() for q in data.get("sub_queries", []) if q and q.strip()]
    if not subs:
        subs = [question]
    return {"sub_queries": subs[:max_sub]}


def _user_msg(content: str) -> dict:
    return {"role": "user", "content": content}


_JUDGE_PROMPT = """快速判断：下方材料能否回答用户问题（能否提供所需的政策口径/金额/条件等实质信息）。
只输出 JSON：{{"can_answer": true/false, "reason": "一句话"}}
沾边但无实质信息、或明确未收录该事项 → false。

问题：{question}
材料：
{materials}"""


async def judge_sufficiency(question: str, materials: list[dict], chat_key: str,
                            meter, max_chars: int = 1200, stage_no: int = 0) -> dict:
    """材料充分性判断（LLM-as-judge）：不足则链路转联网补充。"""
    blocks, used = [], 0
    for i, m in enumerate(materials[:5], 1):
        text = (m.get("text") or "")[:400]
        blocks.append(f"[{i}] {m.get('title', '')}\n{text}")
        used += len(text)
        if used >= max_chars:
            break
    try:
        data = await llm.ainvoke_json(
            [_user_msg(_JUDGE_PROMPT.format(question=question, materials="\n\n".join(blocks)))],
            chat_key, meter, stage="judge", stage_no=stage_no)
        return {"can_answer": bool(data.get("can_answer", True)), "reason": data.get("reason", "")}
    except Exception as e:  # noqa: BLE001 判官失败不阻塞主链路（保守放行给生成端）
        return {"can_answer": True, "reason": f"judge 调用失败，保守放行: {str(e)[:80]}"}
