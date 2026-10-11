# -*- coding: utf-8 -*-
"""LangGraph Agentic RAG 主图。

节点流（每节点=一个登记阶段）：
  intent 意图识别 ─┬─ business → agent(MCP 工具循环)
                   ├─ chitchat → generate_direct
                   └─ rag → region 区域识别
                              ├─ 外地区 → refuse
                              └─ 本省 → fanout(分类 ∥ 分化 并行) → retrieve(混合检索+RRF)
                                        → rerank(重排，失败回退融合序) → 生成/拒答
"""
from __future__ import annotations

import asyncio
import contextlib
import datetime
import functools
import json
import time
import traceback
import uuid

from langgraph.graph import StateGraph, START, END

from app.models import SysDept
from app.rag import llm, qa, rewrite, tools, vectorstore, websearch
from app.rag.fusion import rrf_fuse
from app.rag.state import ChatState
from app.settings import get_settings

MAX_AGENT_ROUNDS = 6
MAX_ERROR_DETAIL = 2000   # error_detail 堆栈截断长度（graph 与 chat 落库共用）


def _rag_cfg() -> dict:
    return get_settings()["rag"]


def _model_name(key: str) -> str:
    try:
        return llm.get_entry(key).model
    except KeyError:
        return key


@contextlib.contextmanager
def _timer():
    """耗时 + 起止墙钟（DATETIME(6) 精度落库，供阶段时间线还原并行重叠）。"""
    t0 = time.perf_counter()
    out: dict = {"ms": 0, "started_at": datetime.datetime.now(), "finished_at": None}
    try:
        yield out
    finally:
        out["ms"] = int((time.perf_counter() - t0) * 1000)
        out["finished_at"] = datetime.datetime.now()


def _emit(state: dict, event: dict) -> None:
    cb = state.get("emit")
    if callable(cb):
        with contextlib.suppress(Exception):
            cb(event)


async def _dept_names(codes: set[str]) -> dict[str, str]:
    """来源展示用：dept_no → 机构名称（展示租户名称而非编号）。"""
    codes = {c for c in codes if c and c not in ("web",)}
    if not codes:
        return {}
    rows = await SysDept.filter(dept_no__in=list(codes))
    return {d.dept_no: d.dept_name for d in rows}


def _source_items(materials: list[dict], names: dict[str, str], limit: int = 6) -> list[dict]:
    """来源清单：知识库来源带内容摘要（前端可点开查看），联网来源带 URL（前端可跳转）。

    混合场景（联网+知识库并存）按配额展示：联网最多 limit-2 条，兜底保留知识库 2 条。
    """
    web = [m for m in materials if m.get("source") == "web"]
    kb = [m for m in materials if m.get("source") != "web"]
    if web and kb:
        picked = web[: max(limit - 2, 1)] + kb[:2]   # 混合配额：联网为主，保留知识库尾部
    else:
        picked = (web or kb)[:limit]

    out = []
    for m in picked:
        item = {
            "title": m.get("title") or "",
            "source": m.get("source", "kb"),
            "rerank_score": m.get("rerank_score"),
            "dept_name": names.get(m.get("dept_code", ""), ""),
        }
        if item["source"] == "web":
            item["url"] = m.get("url", "")
            item["engine"] = m.get("engine", "")
        else:
            item["knowledge_id"] = m.get("knowledge_id")
            item["text"] = (m.get("text") or "")[:600]
        out.append(item)
    return out


def _stage(state: dict, stage_type: str, name: str, *, input_data=None, output_data=None,
           status: str = "done", model: str = "", duration_ms: int | None = None,
           timer: dict | None = None, error_detail: str = "",
           stage_no: int | None = None) -> dict:
    """登记阶段行。stage_no：阶段行号（LLM 计账后登记须先 _next_stage_no 预分配同号）。

    timer：来自 _timer 的计时字典（耗时 + 起止墙钟一体）；无计时行为瞬时行（起止=当下）。
    """
    if timer is not None:
        duration_ms = timer["ms"]
        started_at, finished_at = timer["started_at"], timer["finished_at"]
    else:
        started_at = finished_at = datetime.datetime.now()
    row = {
        "stage_no": stage_no or len(state.setdefault("stage_rows", [])) + 1,
        "stage_type": stage_type, "name": name, "status": status,
        "model": model, "duration_ms": duration_ms if duration_ms is not None else 0,
        "started_at": started_at, "finished_at": finished_at,
        "error_detail": error_detail,
        "input_data": input_data if input_data is not None else {},
        "output_data": output_data if output_data is not None else {},
    }
    state["stage_rows"].append(row)
    # 前端阶段事件：轻量摘要（token/耗时明细归管理端）
    summary = row["output_data"]
    if isinstance(summary, dict):
        summary = {k: v for k, v in summary.items() if k not in ("materials_detail",)}
    _emit(state, {"type": "stage", "stage_type": stage_type, "name": name,
                  "status": status, "duration_ms": row["duration_ms"], "summary": summary})
    return row


def _next_stage_no(state: dict) -> int:
    """下一个阶段行号（在 LLM 调用前预分配，meter 按此号记账）。"""
    return len(state.get("stage_rows") or []) + 1


def stage_error_guard(stage_type: str, label: str):
    """节点异常兜底：失败也登记一行阶段（error_detail 含堆栈、耗时到失败点），原样重抛。

    节点内 LLM 调用抛错时该节点的正常登记行不会执行——本包装器保证异常轮次
    仍有失败行可审计（排障不再只靠 SSE 短消息）。
    """
    def deco(fn):
        @functools.wraps(fn)
        async def wrapper(state: ChatState) -> dict:
            captured: BaseException | None = None
            error_detail = ""
            with _timer() as t:
                try:
                    return await fn(state)
                except Exception as e:  # noqa: BLE001 捕获后先退出计时，再登记失败行
                    captured, error_detail = e, traceback.format_exc()[:MAX_ERROR_DETAIL]
            # 成功路径已在 with 内 return；此处计时已完整（耗时/起止到失败点）
            _stage(state, stage_type, f"{label}（异常）", status="failed",
                   timer=t, error_detail=error_detail)
            raise captured
        return wrapper
    return deco


def _history_text(history: list[dict]) -> str:
    return "\n".join(f"问：{h.get('question', '')}\n答：{str(h.get('answer', ''))[:200]}"
                     for h in (history or [])[-3:])


# ------------------------------------------------------------------ 节点

async def intent_node(state: ChatState) -> dict:
    chat_key = _rag_cfg().get("chat_key", "deepseek")
    _emit(state, {"type": "progress", "stage": "understanding"})
    no = _next_stage_no(state)
    with _timer() as t:
        result = await rewrite.recognize_intent(
            state["question"], _history_text(state.get("history") or []), chat_key,
            state["meter"], stage_no=no)
    _stage(state, "intent", "意图识别", stage_no=no,
           input_data={"question": state["question"][:200]},
           output_data=result, model=_model_name(chat_key), timer=t)
    return {"intent": result["intent"], "intent_reason": result["reason"]}


async def region_node(state: ChatState) -> dict:
    chat_key = _rag_cfg().get("chat_key", "deepseek")
    no = _next_stage_no(state)
    with _timer() as t:
        result = await rewrite.extract_region(
            state["question"], state.get("dept_name", ""), chat_key, state["meter"], stage_no=no)
    # 区域 → 机构映射（哪些机构存在由数据库事实决定，代码不硬编码机构）
    target_dept_no, is_external = state["dept_no"], bool(result.get("is_external"))
    if result.get("region_name") and not is_external:
        name = result["region_name"].strip()
        matched = None
        async for d in SysDept.filter(status="0"):
            if d.dept_name == name or d.dept_name.startswith(name) or name in d.dept_name:
                matched = d
                break
        if matched is None:
            is_external = True
        else:
            target_dept_no = matched.dept_no
    extra = list(state.get("extra_depts") or [])
    if target_dept_no != state["dept_no"]:
        from app.common.deps import resolve_ancestor_chain
        extra = await resolve_ancestor_chain(target_dept_no)
    _stage(state, "region", "区域识别", stage_no=no,
           input_data={"region_name": result.get("region_name", "")},
           output_data={"region_name": result.get("region_name", ""),
                        "is_external": is_external,
                        "target_dept_no": target_dept_no},
           model=_model_name(chat_key), timer=t)
    return {"region_name": result.get("region_name", ""), "is_external": is_external,
            "target_dept_no": target_dept_no, "extra_depts": extra}


async def fanout_node(state: ChatState) -> dict:
    """问题分类 ∥ 问题分化（并行使命）。"""
    chat_key = _rag_cfg().get("chat_key", "deepseek")
    max_sub = int(_rag_cfg().get("max_sub_queries", 4))
    # 并行两路：先预分配两行号（gather 内 meter 并发记账互不干扰）
    base = _next_stage_no(state)
    cls_no, dec_no = base, base + 1
    with _timer() as t1, _timer() as t2:
        cls, dec = await asyncio.gather(
            rewrite.classify_theme(state["question"], chat_key, state["meter"], stage_no=cls_no),
            rewrite.decompose_question(state["question"], chat_key, state["meter"], max_sub,
                                       stage_no=dec_no),
        )
    _stage(state, "classify", "问题分类", stage_no=cls_no,
           input_data={"question": state["question"][:200]},
           output_data=cls, model=_model_name(chat_key), timer=t1)
    _stage(state, "decompose", "问题分化", stage_no=dec_no,
           input_data={"question": state["question"][:200]},
           output_data=dec, model=_model_name(chat_key), timer=t2)
    return {"theme": cls["theme"], "sub_queries": dec["sub_queries"]}


async def retrieve_node(state: ChatState) -> dict:
    cfg = _rag_cfg()
    embed_key = cfg.get("embeddings_key", "qwen")
    pool = int(cfg.get("candidate_pool", 30))
    _emit(state, {"type": "progress", "stage": "searching"})
    dept_no = state.get("target_dept_no") or state["dept_no"]
    extra = state.get("extra_depts") or []
    no = _next_stage_no(state)

    with _timer() as t:
        sub_queries = state.get("sub_queries") or [state["question"]]
        vectors = await llm.embed_texts(sub_queries, embed_key, state["meter"],
                                        stage="retrieve", stage_no=no)
        # 每个子查询独立双路召回，全部路数一起 RRF 融合
        route_lists: list[list[str]] = []
        per_route: list[dict] = []
        for query, vec in zip(sub_queries, vectors):
            hits = vectorstore.hybrid_search(
                query, vec, dept_no, extra, theme=state.get("theme", "") or "",
                size=max(pool, 20),
            )
            route_lists.append([h["chunk_id"] for h in hits["bm25"]])
            route_lists.append([h["chunk_id"] for h in hits["knn"]])
            per_route.append({
                "sub_query": query,
                "bm25_hits": len(hits["bm25"]),
                "knn_hits": len(hits["knn"]),
            })
        fused = rrf_fuse(route_lists)
        top_ids = [cid for cid, _ in fused[:pool]]
        details = vectorstore.mget_chunks(top_ids)
        materials = []
        for cid in top_ids:
            d = details.get(cid)
            if d:
                materials.append({
                    "chunk_id": cid, "text": d["text"], "title": d["title"],
                    "dept_code": d["dept_code"], "biz_type": d["biz_type"],
                    "knowledge_id": d.get("knowledge_id"), "source": "kb",
                })
    snapshot_id = uuid.uuid4().hex[:16]
    # 召回审计明细：融合后 top20 候选（chunk_id 事后不可回溯，只能在检索当时记录）
    recall_audit = []
    for rank, (cid, score) in enumerate(fused[:20], 1):
        d = details.get(cid)
        if d:
            recall_audit.append({
                "chunk_id": cid, "knowledge_id": d.get("knowledge_id") or 0,
                "title": (d.get("title") or "")[:128], "rank": rank, "score": round(score, 4),
            })
    _stage(state, "retrieve", "混合检索(BM25+kNN→RRF)", stage_no=no,
           input_data={"sub_queries": sub_queries, "dept_code": dept_no,
                       "extra_dept": extra, "theme": state.get("theme", "")},
           output_data={"routes": per_route, "fused": len(fused),
                        "materials": len(materials), "snapshot_id": snapshot_id},
           model=_model_name(embed_key), timer=t)
    return {"materials": materials, "kb_materials": materials, "snapshot_id": snapshot_id,
            "recall_audit": recall_audit}


async def rerank_node(state: ChatState) -> dict:
    cfg = _rag_cfg()
    top_k = int(cfg.get("top_k", 6))
    timeout_ms = int(cfg.get("rerank_timeout_ms", 3000))
    materials = state.get("materials") or []
    if not materials:
        return {"rerank_used": False}
    no = _next_stage_no(state)
    try:
        with _timer() as t:
            ranking = await llm.rerank_documents(
                state["question"], [m["text"][:800] for m in materials], top_k,
                timeout_ms, state["meter"], stage="rerank", stage_no=no)
        reranked = [dict(materials[i], rerank_score=round(s, 4)) for i, s in ranking]
        _stage(state, "rerank", "重排序", stage_no=no,
               input_data={"candidates": len(materials), "top_k": top_k},
               output_data={"kept": [m["chunk_id"] for m in reranked],
                            "scores": [round(s, 4) for _, s in ranking]},
               model=_model_name(cfg.get("rerank_key", "rerank")), timer=t)
        return {"materials": reranked, "rerank_used": True,
                "recall_kept": [m["chunk_id"] for m in reranked]}
    except Exception as e:  # noqa: BLE001 重排失败一律回退融合原序，不阻塞回答
        _stage(state, "rerank", "重排序", stage_no=no,
               input_data={"candidates": len(materials)},
               output_data={"fallback": True, "error": str(e)[:200], "kept_top_k": top_k},
               status="failed", model=_model_name(cfg.get("rerank_key", "rerank")),
               timer=t, error_detail=traceback.format_exc()[:MAX_ERROR_DETAIL])
        return {"materials": materials[:top_k], "rerank_used": False,
                "recall_kept": [m["chunk_id"] for m in materials[:top_k]]}


async def judge_node(state: ChatState) -> dict:
    """材料充分性判断：不足则转联网补充（判官失败保守放行给生成端）。"""
    chat_key = _rag_cfg().get("chat_key", "deepseek")
    materials = state.get("materials") or []
    if not materials:
        _stage(state, "judge", "材料充分性判断", input_data={"materials": 0},
               output_data={"can_answer": False, "reason": "无候选材料"}, model="", duration_ms=0)
        return {"sufficient": False}
    no = _next_stage_no(state)
    with _timer() as t:
        verdict = await rewrite.judge_sufficiency(state["question"], materials, chat_key,
                                                  state["meter"], stage_no=no)
    _stage(state, "judge", "材料充分性判断", stage_no=no,
           input_data={"question": state["question"][:120], "materials": len(materials)},
           output_data=verdict, model=_model_name(chat_key), timer=t)
    return {"sufficient": verdict["can_answer"]}


async def web_search_node(state: ChatState) -> dict:
    """联网补充：材料来自自建检索服务（SearXNG 协议），不调用模型厂商联网能力。

    联网前已由判官判定知识库材料不足；联网成功时来源以联网为主，
    并保留知识库材料尾部（混合展示口径：材料可混合，来源注明类型）。
    """
    cfg = _rag_cfg()
    query = state["question"]
    _emit(state, {"type": "progress", "stage": "web_searching"})
    try:
        with _timer() as t:
            raw = await websearch.search(query, limit=int(cfg.get("top_k", 6)))
        web_materials = [{
            "chunk_id": f"web:{i}", "text": f"{r['title']}\n{r['content']}",
            "title": r["title"] or r["url"], "url": r["url"], "engine": r["engine"],
            "dept_code": "web", "biz_type": "web", "source": "web",
            "rerank_score": r.get("score"),
        } for i, r in enumerate(raw)]
        kb_tail = [m for m in (state.get("kb_materials") or [])[:2]]
        _stage(state, "web_search", "联网检索(自建服务)",
               input_data={"query": query, "engines": (get_settings().get("websearch") or {}).get("engines", "")},
               output_data={"count": len(web_materials),
                            "mixed_kb": len(kb_tail),
                            "top": [{"title": m["title"][:60], "url": m["url"][:120]} for m in web_materials[:3]]},
               model="local-search", timer=t)
        return {"web_materials": web_materials, "web_ok": bool(web_materials),
                "materials": web_materials + kb_tail, "web_attempted": True}
    except websearch.WebSearchError as e:  # noqa: BLE001 联网不可用→按拒答降级，不阻塞其它路径
        _stage(state, "web_search", "联网检索(自建服务)", input_data={"query": query},
               output_data={"error": str(e)[:200]}, status="failed", model="local-search",
               timer=t, error_detail=traceback.format_exc()[:MAX_ERROR_DETAIL])
        return {"web_materials": [], "web_ok": False, "materials": [],
                "web_attempted": True}


async def generate_node(state: ChatState) -> dict:
    chat_key = _rag_cfg().get("chat_key", "deepseek")
    _emit(state, {"type": "progress", "stage": "generating"})
    messages = qa.build_messages(state["question"], state["materials"], state.get("history"))
    pieces: list[str] = []
    gen_no = _next_stage_no(state)
    with _timer() as t:
        async for chunk in llm.astream_text(messages, chat_key, state["meter"],
                                             stage="generate", stage_no=gen_no):
            pieces.append(chunk)
            _emit(state, {"type": "text", "content": chunk})
    answer = "".join(pieces)

    # 来源清单（混合展示：知识库可点开查看内容 / 联网可跳转原文；租户显示机构名称）
    names = await _dept_names({m.get("dept_code", "") for m in state["materials"]})
    _emit(state, {"type": "sources", "materials": _source_items(state["materials"], names)})
    _stage(state, "generate", "回答生成", stage_no=gen_no,
           input_data={"snapshot_id": state.get("snapshot_id", ""),
                       "material_count": len(state.get("materials") or []),
                       "web_materials": sum(1 for m in state["materials"] if m.get("source") == "web")},
           output_data={"chars": len(answer)}, model=_model_name(chat_key), timer=t)

    # 可能相关问题推荐（追问推荐）：调用发生即登记（含空结果），保证 token 不成孤儿
    sug_no = _next_stage_no(state)
    with _timer() as sug_t:
        questions = await rewrite.suggest_questions(state["question"], answer, state["materials"],
                                                    chat_key, state["meter"], stage_no=sug_no)
    if questions:
        _emit(state, {"type": "question", "questions": questions})
    _stage(state, "suggest", "相关问题推荐", stage_no=sug_no,
           input_data={"question": state["question"][:120]},
           output_data={"questions": questions}, model=_model_name(chat_key), timer=sug_t)
    return {"answer": answer}


async def refuse_node(state: ChatState) -> dict:
    if state.get("is_external") and not state.get("web_attempted"):
        text = qa.EXTERNAL_REFUSE_TEXT
    elif state.get("web_attempted"):
        text = qa.WEB_EMPTY_REFUSE_TEXT
    else:
        text = qa.REFUSE_TEXT
    _emit(state, {"type": "progress", "stage": "generating"})
    _emit(state, {"type": "text", "content": text})
    _stage(state, "generate", "拒答",
           input_data={"reason": "external" if state.get("is_external") else
                       ("web_empty" if state.get("web_attempted") else "insufficient")},
           output_data={"chars": len(text)}, model="", duration_ms=0)
    return {"answer": text, "refused": True}


async def off_topic_refuse_node(state: ChatState) -> dict:
    """离线话题拒答：与公积金无关的实质问题，直接拒绝并引导回公积金范围。"""
    text = qa.OFF_TOPIC_REFUSE_TEXT
    _emit(state, {"type": "progress", "stage": "generating"})
    _emit(state, {"type": "text", "content": text})
    _stage(state, "generate", "无关话题拒答",
           input_data={"intent": "off_topic", "reason": state.get("intent_reason", "")[:120]},
           output_data={"chars": len(text)}, model="", duration_ms=0)
    return {"answer": text, "refused": True}


async def direct_node(state: ChatState) -> dict:
    chat_key = _rag_cfg().get("chat_key", "deepseek")
    _emit(state, {"type": "progress", "stage": "generating"})
    messages = [
        {"role": "system", "content": (
            "你是公积金中心的智能客服小金，友好简洁地回应寒暄与闲聊，不涉及具体政策口径。"
            "被问你是谁/能做什么时：一句话自我介绍并引导（政策咨询、查个人业务、在线办理均可）。"
            "遇到投诉、不满或激动情绪（如「气死了」「我要投诉」）：先共情安抚（一两句即可），"
            "告知人工渠道——拨打 12329 转人工或点击界面「转人工」，并邀请用户说明具体遇到的问题；"
            "不查询账户数据、不承诺处理进度、不编造工单。用户补充出具体业务问题后会由系统重新路由处理。"
        )},
        *[m for h in (state.get("history") or [])[-2:] for m in (
            {"role": "user", "content": h.get("question", "")},
            {"role": "assistant", "content": str(h.get("answer", ""))[:400]})],
        {"role": "user", "content": state["question"]},
    ]
    pieces: list[str] = []
    gen_no = _next_stage_no(state)
    with _timer() as t:
        async for chunk in llm.astream_text(messages, chat_key, state["meter"],
                                             stage="generate", stage_no=gen_no):
            pieces.append(chunk)
            _emit(state, {"type": "text", "content": chunk})
    _stage(state, "generate", "直接生成", stage_no=gen_no, input_data={"intent": "chitchat"},
           output_data={"chars": len("".join(pieces))}, model=_model_name(chat_key), timer=t)
    return {"answer": "".join(pieces)}


def flow_sections(flow_def, instance) -> list[dict]:
    """还原"最后一态的表单数据"（紧凑三段式：办理信息 / 信息确认 / 办理结果）。

    - 仅呈现表单字段最终值（跨表单节点合并）+ 确认摘要 + 结果，不堆叠系统核验明细；
    - 全部敏感字段（银行卡号/身份证号/手机号）脱敏后展示。
    """
    from app.mock_data import mask

    nodes = load_nodes_of(flow_def, instance)
    try:
        steps = json.loads(instance.steps or "[]")
    except (json.JSONDecodeError, TypeError):
        steps = []
    by_node: dict[str, list[dict]] = {}
    for st in steps:
        by_node.setdefault(st.get("node_key"), []).append(st)

    sensitive = {"bank_card": (4, 4), "repay_card": (4, 4), "id_card": (3, 4), "phone": (3, 2)}

    def show(name: str, value) -> str:
        text = "" if value in (None, "") else str(value)
        if not text:
            return ""
        if name in sensitive:
            h, t = sensitive[name]
            return mask(text, h, t)
        return text

    fields: list[dict] = []
    confirm_summary = ""
    result_no = ""
    prior_notes: list[str] = []

    for n in nodes:
        attempts = by_node.get(n["key"], [])
        ok_attempt = next((a for a in reversed(attempts) if not a.get("errors")), None)
        last = attempts[-1] if attempts else {}
        data = (ok_attempt or last).get("data") or {}
        if n["type"] == "form":
            for f in n.get("fields", []):
                v = show(f["name"], data.get(f["name"]))
                if v:
                    fields.append({"label": f.get("label", f["name"]), "value": v})
            if ok_attempt:      # 已修正的历史失败尝试：保留一行提示（不算"垃圾数据"）
                for a in attempts:
                    prior_notes.extend((a.get("errors") or {}).values())
                prior_notes = prior_notes[:2]
        elif n["type"] == "upload":
            up = data.get("files") or {}
            for f in n.get("files", []):
                info = up.get(f["name"]) or {}
                if info.get("filename"):
                    size_kb = (info.get("size") or 0) / 1024
                    fields.append({"label": f.get("label", f["name"]),
                                   "value": f"{info['filename']}（{size_kb:.0f}KB）"})
        elif n["type"] == "confirm":
            confirm_summary = _render_summary(
                n.get("summary_template", ""),
                {k: show(k, v) for k, v in _parse_vars(instance).items()})
        elif n["type"] == "auto":
            res = next((a.get("result") for a in reversed(attempts) if a.get("result")), "") or ""
            for line in res.splitlines():
                if "受理单号" in line:
                    result_no = line.strip().lstrip("- ").strip()

    out = [{"type": "form_summary", "title": "办理信息", "fields": fields}]
    if confirm_summary:
        out.append({"type": "confirm", "title": "信息确认", "summary": confirm_summary})
    if prior_notes:
        out.append({"type": "note", "text": "此前提交未通过校验（已修正）：" + "；".join(prior_notes)})
    if instance.status == "done":
        end_text = next((n.get("text", "") for n in nodes if n["type"] == "end"), "")
        out.append({"type": "result", "text": (result_no + "\n" if result_no else "") + end_text})
    elif instance.status == "cancelled":
        out.append({"type": "result", "text": "该业务办理已取消"})
    else:
        out.append({"type": "result", "text": "办理中…"})
    return out


def load_nodes_of(flow_def, instance=None) -> list[dict]:
    """展示层节点：运行/历史实例优先快照，否则用已发布定义（与引擎口径一致）。"""
    if instance is not None:
        snap = (getattr(instance, "nodes_snapshot", "") or "").strip()
        if snap:
            try:
                return json.loads(snap)
            except (json.JSONDecodeError, TypeError):
                pass
    try:
        return json.loads(flow_def.published_nodes or "[]")
    except (json.JSONDecodeError, TypeError):
        return []


def _parse_vars(instance) -> dict:
    try:
        return json.loads(instance.vars or "{}")
    except (json.JSONDecodeError, TypeError):
        return {}


def _render_summary(template: str, vars_: dict) -> str:
    from app.mock_data import mask
    sens = {"bank_card": (4, 4), "repay_card": (4, 4), "id_card": (3, 4), "phone": (3, 2)}
    out = template
    for k, v in vars_.items():
        text = "" if v in (None, "") else str(v)
        if k in sens and text:
            h, t = sens[k]
            text = mask(text, h, t)
        out = out.replace("{" + k + "}", text)
    # 未填字段兜底：不留 {xxx} 占位符
    import re as _re
    return _re.sub(r"\{[a-z_]+\}", "—", out)


AGENT_SYSTEM = """你是公积金中心的业务办理助手小金。用户要查询自己的公积金业务时，
直接使用提供的工具查询后作答——**当前账户身份已随登录态绑定**，身份证号/手机号/姓名无需向用户索要、
也无需在回答中复述（工具返回已脱敏）。工具返回的数据就是权威数据，不要编造。
只在用户明确提出查询/办理本人业务时才调用工具；纯投诉、情绪表达、寒暄等无数据诉求时
不调用任何工具，直接安抚并指引人工渠道（12329 热线或界面「转人工」）。
回答用 Markdown，金额保留千分位。"""


async def agent_node(state: ChatState) -> dict:
    chat_key = _rag_cfg().get("chat_key", "deepseek")
    _emit(state, {"type": "progress", "stage": "understanding"})

    # 办理意图优先匹配业务流程：命中 → 只做办理推荐（不查数据、不做政策长回答）。
    # 未命中办理流程的（如"查一下我的余额"）才走下方工具循环按查询作答。
    from app.flow_engine import recommend_flows
    flows = await recommend_flows(state["dept_no"], state["question"])
    if flows:
        names = "、".join(f["name"] for f in flows)
        redirect = all(f.get("mode") == "redirect" for f in flows)
        if redirect:
            text = (f"已为您匹配到可办理业务：{names}。该业务需提交材料核验，"
                    "点击下方入口将跳转业务系统页面办理。")
        else:
            text = (f"好的，已为您匹配到可办理业务：{names}。"
                    "点击下方入口即可在线办理；办理期间问答将暂停，完成或取消后可继续提问。")
        _emit(state, {"type": "progress", "stage": "generating"})
        _emit(state, {"type": "text", "content": text})
        _stage(state, "generate", "办理推荐引导", input_data={"intent": "business", "flows": [f["flow_key"] for f in flows]},
               output_data={"chars": len(text)}, model=_model_name(chat_key), duration_ms=0)
        _emit(state, {"type": "recommend", "flows": flows})
        _stage(state, "flow", "办理推荐", input_data={"question": state["question"][:120]},
               output_data={"flows": [f"{f['flow_key']}({f.get('mode', 'embed')})" for f in flows]},
               model="", duration_ms=0)
        return {"answer": text}
    s = get_settings()
    base_url = f"http://127.0.0.1:{s['server']['port']}/mcp"   # 根挂载后端点即 /mcp

    # list_tools 发现 → 按部门过滤可见集 → bind_tools
    with _timer() as t_disc:
        all_tools = await tools.fetch_langchain_tools(base_url)
        visible = {t["name"] for t in await tools.get_visible_tool_names(state["dept_no"])}
        bound = [t for t in all_tools if t.name in visible]
    _stage(state, "tool", "工具发现(list_tools)",
           input_data={"endpoint": base_url},
           output_data={"discovered": [t.name for t in all_tools],
                        "visible": sorted(visible)},
           model="mcp", timer=t_disc)

    model = llm.get_chat_model(chat_key)
    model_with_tools = model.bind_tools(bound) if bound else model
    messages: list = [
        {"role": "system", "content": AGENT_SYSTEM},
        {"role": "user", "content": state["question"]},
    ]
    pieces: list[str] = []
    final_gen_no = 0    # 末轮（无工具调用）回答的生成行号，循环后登记时使用
    final_gen_t: dict | None = None   # 末轮生成 ainvoke 计时（生成行耗时不再为 0）
    for _round in range(MAX_AGENT_ROUNDS):
        with _timer() as inv_t:
            resp = await model_with_tools.ainvoke(messages)
        messages.append(resp)
        usage = resp.usage_metadata or {}
        tool_calls = getattr(resp, "tool_calls", None) or []
        if tool_calls:
            # 本轮决策调用的消耗记到本轮首个工具行（该行在工具执行完登记，号即当前下一号）
            state["meter"].add("tool", _model_name(chat_key),
                               usage.get("input_tokens", 0), usage.get("output_tokens", 0),
                               stage_no=_next_stage_no(state))
        else:
            # 末轮无工具调用即最终回答：预分配生成行号并记下本次计时
            final_gen_no = _next_stage_no(state)
            final_gen_t = inv_t
            state["meter"].add("generate", _model_name(chat_key),
                               usage.get("input_tokens", 0), usage.get("output_tokens", 0),
                               stage_no=final_gen_no)
            pieces = [(resp.content or "")]
            _emit(state, {"type": "text", "content": resp.content or ""})
            break
        # 同轮工具并发执行（gather 保序回传）
        async def _run_one(tc: dict) -> tuple[dict, str, int]:
            # 身份注入：需要证件号但未提供的工具调用，自动使用登录态身份（三要素不出会话）
            args = dict(tc.get("args") or {})
            if not str(args.get("id_card") or "").strip() and state.get("user_id_card"):
                args["id_card"] = state["user_id_card"]
            tc = {**tc, "args": args}
            with _timer() as tool_t:
                tool_obj = next((t_ for t_ in bound if t_.name == tc["name"]), None)
                try:
                    raw = await tool_obj.ainvoke(args) if tool_obj else f"工具 {tc['name']} 不可用"
                except Exception as e:  # noqa: BLE001 业务失败终止该工具，错误回填
                    raw = f"工具执行失败: {e}"
            # langchain 工具结果为 content 块列表时抽取纯文本（兼容对象/字典两种块形态）
            if isinstance(raw, list):
                parts = []
                for b in raw:
                    if isinstance(b, dict):
                        parts.append(b.get("text", ""))
                    else:
                        parts.append(getattr(b, "text", str(b)))
                raw = "".join(parts)
            return tc, str(raw), tool_t

        outs = await asyncio.gather(*[_run_one(tc) for tc in tool_calls])
        for tc, result, tool_t in outs:
            # 工具入参中的身份要素掩码展示（三要素不明文外露）
            from app.mock_data import mask as _mask
            shown_args = {
                k: (_mask(str(v)) if k in ("id_card", "phone", "bank_card", "repay_card") else v)
                for k, v in (tc.get("args") or {}).items()
            }
            _emit(state, {"type": "tool", "name": tc["name"], "arguments": shown_args})
            _emit(state, {"type": "tool_result", "name": tc["name"],
                          "result": result[:600]})
            _stage(state, "tool", f"工具调用:{tc['name']}",
                   input_data={"arguments": {k: v for k, v in (tc.get("args") or {}).items()
                                             if k not in ("id_card", "phone", "bank_card")}},
                   output_data={"result": result[:1000]}, model="mcp", timer=tool_t)
        for tc, result, _t in outs:
            messages.append({"role": "tool", "content": result[:4000],
                             "tool_call_id": tc["id"], "name": tc["name"]})
    else:
        pieces = ["（已达到最大工具调用轮次，请换个问法或稍后再试）"]
        _emit(state, {"type": "text", "content": pieces[0]})

    answer = "".join(pieces)
    _stage(state, "generate", "业务回答生成", stage_no=final_gen_no or None,
           input_data={"intent": "business"},
           output_data={"chars": len(answer)}, model=_model_name(chat_key),
           timer=final_gen_t)   # 末轮计时；耗尽最大轮次时为瞬时行

    # 办理推荐：关键词命中的流程下发（简单业务走流程引擎嵌入，复杂业务跳转页面）
    from app.flow_engine import recommend_flows
    flows = await recommend_flows(state["dept_no"], state["question"])
    if flows:
        _emit(state, {"type": "recommend", "flows": flows})
        _stage(state, "flow", "办理推荐", input_data={"question": state["question"][:120]},
               output_data={"flows": [f"{f['flow_key']}({f.get('mode', 'embed')})" for f in flows]},
               model="", duration_ms=0)
    sug_no = _next_stage_no(state)
    with _timer() as sug_t:
        questions = await rewrite.suggest_questions(state["question"], answer, [], chat_key,
                                                    state["meter"], stage_no=sug_no)
    if questions:
        _emit(state, {"type": "question", "questions": questions})
    _stage(state, "suggest", "相关问题推荐", stage_no=sug_no,
           input_data={"question": state["question"][:120]},
           output_data={"questions": questions}, model=_model_name(chat_key), timer=sug_t)
    return {"answer": answer}


# ------------------------------------------------------------------ 路由与建图

def _route_intent(state: ChatState) -> str:
    return {"business": "agent", "chitchat": "direct", "off_topic": "off_topic_refuse"}.get(
        state.get("intent", "rag"), "region")


def _route_region(state: ChatState) -> str:
    if not state.get("is_external"):
        return "fanout"
    # 外地区：联网补充开启则直接联网回答，否则拒答
    if _rag_cfg().get("web_external_region", True) and websearch.is_enabled():
        return "web_search"
    return "refuse"


def _route_after_rerank(state: ChatState) -> str:
    return "judge"


def _route_judge(state: ChatState) -> str:
    if state.get("sufficient", True):
        return "generate"
    # 材料不足：联网补充开启则联网兜底，否则拒答
    if _rag_cfg().get("web_on_insufficient", True) and websearch.is_enabled():
        return "web_search"
    return "refuse"


def _route_after_web(state: ChatState) -> str:
    # 判据是"联网是否真的取到材料"（混合展示会带上知识库尾部，不能据此放行）
    return "generate" if state.get("web_ok") else "refuse"


def build_chat_graph():
    guard = stage_error_guard   # 节点异常兜底：失败登记阶段行（含堆栈）后重抛
    g = StateGraph(ChatState)
    g.add_node("intent", guard("intent", "意图识别")(intent_node))
    g.add_node("region", guard("region", "区域识别")(region_node))
    g.add_node("fanout", guard("fanout", "分类∥分化")(fanout_node))
    g.add_node("retrieve", guard("retrieve", "混合检索")(retrieve_node))
    g.add_node("rerank", guard("rerank", "重排序")(rerank_node))
    g.add_node("judge", guard("judge", "充分性判断")(judge_node))
    g.add_node("web_search", guard("web_search", "联网检索")(web_search_node))
    g.add_node("generate", guard("generate", "回答生成")(generate_node))
    g.add_node("direct", guard("generate", "直接生成")(direct_node))
    g.add_node("agent", guard("agent", "业务工具循环")(agent_node))
    g.add_node("refuse", guard("generate", "拒答")(refuse_node))
    g.add_node("off_topic_refuse", guard("generate", "无关话题拒答")(off_topic_refuse_node))

    g.add_edge(START, "intent")
    g.add_conditional_edges("intent", _route_intent,
                            {"agent": "agent", "direct": "direct", "region": "region",
                             "off_topic_refuse": "off_topic_refuse"})
    g.add_conditional_edges("region", _route_region,
                            {"fanout": "fanout", "web_search": "web_search", "refuse": "refuse"})
    g.add_edge("fanout", "retrieve")
    g.add_edge("retrieve", "rerank")
    g.add_edge("rerank", "judge")
    g.add_conditional_edges("judge", _route_judge,
                            {"generate": "generate", "web_search": "web_search", "refuse": "refuse"})
    g.add_conditional_edges("web_search", _route_after_web,
                            {"generate": "generate", "refuse": "refuse"})
    g.add_edge("generate", END)
    g.add_edge("direct", END)
    g.add_edge("agent", END)
    g.add_edge("refuse", END)
    g.add_edge("off_topic_refuse", END)
    return g.compile()


_chat_graph = None


def get_chat_graph():
    global _chat_graph
    if _chat_graph is None:
        _chat_graph = build_chat_graph()
    return _chat_graph
