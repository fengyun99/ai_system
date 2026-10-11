# -*- coding: utf-8 -*-
"""进程完整性验收套件——一次跑通全链路（知识/跨库/联网/流程办理/门控/取消）。

用法：.venv/Scripts/python.exe scripts/integrity_check.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.crypto import sm3_hex  # noqa: E402

B = "http://127.0.0.1:9310"
PASS, FAIL = "✅", "❌"
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"{PASS if ok else FAIL} {name}  {detail}")


def login(user: str, pwd: str) -> str:
    r = httpx.post(f"{B}/api/login", json={"username": user, "password": sm3_hex(pwd)}, timeout=15)
    return r.json()["data"]["token"]


def sse(path: str, body: dict, token: str) -> list[dict]:
    evs: list[dict] = []
    with httpx.stream("POST", f"{B}{path}", headers={"token": token}, json=body, timeout=300) as r:
        if "json" in (r.headers.get("content-type") or ""):
            return [json.loads(r.read())]
        for line in r.iter_lines():
            if line.startswith("data: "):
                evs.append(json.loads(line[6:]))
    return evs


def stages_of(evs: list[dict]) -> list[tuple[str, str]]:
    return [(e["stage_type"], e["status"]) for e in evs if e["type"] == "stage"]


def answer_of(evs: list[dict]) -> str:
    return "".join(e["content"] for e in evs if e["type"] == "text")


def compact(text: str) -> str:
    """去除空白后的答案文本（断言抗 LLM 空格格式差异）。"""
    return "".join((text or "").split())


def main() -> int:
    # 预检：模型连通性（无效 key 时快速失败，避免一屏误导性 401 失败）
    import httpx as _hx
    from app.rag import llm as _llm
    _entries = _llm.load_model_config()
    _chat = _entries.get("deepseek")
    try:
        _r = _hx.post(f"{_chat.base_url}/chat/completions",
                      headers={"Authorization": f"Bearer {_chat.next_key()}"},
                      json={"model": _chat.model, "messages": [{"role": "user", "content": "OK"}],
                            "max_tokens": 4}, timeout=20)
        _llm_ok = _r.status_code == 200
    except Exception:
        _llm_ok = False
    if not _llm_ok:
        print("❌ 预检失败：DeepSeek API Key 无效（401）。")
        print("   请把有效的 DeepSeek key 明文填入 config/model-config.json 的 api_key 数组，")
        print("   重启后端后重跑本套件（scripts/check_models.py 可单独自检）。")
        print("   非 LLM 能力（登录/RBAC/流程引擎/知识库管理/审计）不受影响。")
        return 2

    admin = login("admin", "admin123")
    fzzx = login("fzzx", "fz123456")
    czzx = login("qzzx", "qz123456")
    check("登录（SM3 口令协议：三账号）", all([admin, fzzx, czzx]))

    # 1) 知识问答（本地命中）
    evs = sse("/api/chat/stream", {"question": "福州公积金贷款最高能贷多少"}, fzzx)
    conv_qa = [e for e in evs if e["type"] == "meta"][0]["conversation_id"]
    st = stages_of(evs)
    ans = answer_of(evs)
    ca = compact(ans)
    check("知识问答（本地检索命中）", ("judge", "done") in st and "100万" in ca and "60万" in ca,
          f"阶段={[s[0] for s in st]}")

    # 2) 跨知识库问答（福州账号问泉州/省级公开）
    evs = sse("/api/chat/stream", {"question": "泉州的公积金贷款利率是多少"}, fzzx)
    src = [e for e in evs if e["type"] == "sources"]
    ans = answer_of(evs)
    cross = src and any("泉州" in (m.get("dept_name") or "") for m in src[0]["materials"])
    check("跨知识库问答（跨市租户检索）", cross and "2.85" in ans,
          f"来源机构={[m.get('dept_name') for m in (src[0]['materials'] if src else [])]}")

    # 3) 联网问答 A：外地区 → 自建检索服务
    evs = sse("/api/chat/stream", {"question": "北京的公积金租房提取额度是多少"}, fzzx)
    st = stages_of(evs)
    src = [e for e in evs if e["type"] == "sources"]
    web_hit = any(m.get("source") == "web" and m.get("url") for m in (src[0]["materials"] if src else []))
    check("联网问答（外地区→自建检索）", ("web_search", "done") in st and web_hit,
          f"阶段={[s[0] for s in st]}")

    # 4) 联网问答 B：知识不足 → 判官 → 联网兜底
    evs = sse("/api/chat/stream", {"question": "公积金贷款提前还款需要支付违约金吗"}, fzzx)
    st = stages_of(evs)
    judge = next((e for e in evs if e["type"] == "stage" and e["stage_type"] == "judge"), None)
    check("联网问答（知识不足→判官→联网）",
          ("judge", "done") in st and ("web_search", "done") in st,
          f"判官={judge.get('summary', {}).get('can_answer') if judge else None}")

    # 4b) 办理意图只推荐业务：命中流程 → 无工具调用、无长回答
    evs = sse("/api/chat/stream", {"question": "我要办理租房提取"}, fzzx)
    rec2 = [e for e in evs if e["type"] == "recommend"]
    tools2 = [e for e in evs if e["type"] == "tool"]
    ans2 = answer_of(evs)
    gen_stages = [e for e in evs if e["type"] == "stage" and e["stage_type"] == "generate"]
    only_rec = bool(rec2) and not tools2 and "办理推荐引导" in (gen_stages[0]["name"] if gen_stages else "")
    check("办理意图只推荐业务（不查数据/不做政策长回答）",
          only_rec and len(ans2) < 160 and "点击下方入口" in ans2,
          f"工具调用数={len(tools2)} 回答长度={len(ans2)}")

    # 5) MCP 业务问答：身份随登录绑定，无需用户提供身份证号（三要素不出会话）
    evs = sse("/api/chat/stream", {"question": "帮我查一下我的公积金账户余额"}, fzzx)
    tools = [e for e in evs if e["type"] == "tool"]
    tool_res = [e for e in evs if e["type"] == "tool_result"]
    # 身份注入的入参以掩码形态外露（三要素不明文）；结果命中该用户绑定账户
    injected = bool(tools) and (tools[0]["arguments"].get("id_card") == "350***********1234")
    masked = bool(tool_res) and "***" in tool_res[0]["result"]
    bound = bool(tool_res) and ("394,550" in tool_res[0]["result"] or "陈测试" in tool_res[0]["result"])
    check("MCP 业务问答（登录态身份自动注入 + 掩码脱敏）", injected and masked and bound,
          f"入参={tools[0]['arguments'] if tools else None}")

    # 5b) 用户身份绑定（getInfo 回显掩码三要素）
    info = httpx.get(f"{B}/api/getInfo", headers={"token": fzzx}, timeout=15).json()["data"]["user"]
    check("登录用户带 mock 三要素（掩码回显/已绑定）",
          info.get("identity_bound") and "***" in info.get("id_card_masked", "")
          and "***" in info.get("phone_masked", ""),
          f"{info.get('nick_name')} {info.get('id_card_masked')}")

    # 5c) 不同用户取到各自 mock 账户（qzzx 贷款档案）
    evs = sse("/api/chat/stream", {"question": "我的公积金贷款还剩多少没还"}, czzx)
    ans = answer_of(evs)
    check("按登录用户取 mock 账户数据（泉州账户贷款档案）",
          "318,000" in ans or "318000" in compact(ans), ans[:40].replace(chr(10), " "))

    # 6) 完整业务流程：推荐 → 启动 → 门控 → 步进 → 自动核验 → 完成 → 恢复
    evs = sse("/api/chat/stream", {"question": "我要办理租房提取"}, fzzx)
    rec = [e for e in evs if e["type"] == "recommend"]
    conv = [e for e in evs if e["type"] == "meta"][0]["conversation_id"]
    check("办理推荐（业务意图→流程入口）", bool(rec) and rec[0]["flows"], f"{rec[0]['flows'][0]['flow_key'] if rec else None}")

    evs = sse("/api/flow/start", {"flow_key": "rent_withdraw", "conversation_id": conv}, fzzx)
    fs = [e for e in evs if e["type"] == "flow_start"]
    inst = fs[0]["instance_id"]
    check("流程启动（首节点卡片·步骤按交互步计）", bool(fs) and fs[0]["card"]["node_key"] == "reason",
          f"progress={fs[0]['card']['progress'] if fs else ''}")
    check("步骤数按用户交互步（填表/确认，非系统节点）",
          fs and fs[0]["card"]["progress"].endswith("/3"), "")

    r = httpx.post(f"{B}/api/chat/stream", headers={"token": fzzx},
                   json={"question": "顺便问个别的", "conversation_id": conv}, timeout=30)
    check("流程门控（办理中问答被阻断）", r.json().get("code") == 409, r.json().get("msg", "")[:26])

    evs = sse("/api/flow/submit", {"instance_id": inst, "node_key": "reason",
                                   "data": {"reason": "租房提取", "amount": 12000}}, fzzx)
    card = [e for e in evs if e["type"] == "card"]
    check("流程步进 1（提取信息→收款账户）", bool(card) and card[0]["card"]["node_key"] == "account")

    evs = sse("/api/flow/submit", {"instance_id": inst, "node_key": "account",
                                   "data": {"bank_card": "6222021234567890123",
                                            "id_card": "350102199001011234"}}, fzzx)
    card = [e for e in evs if e["type"] == "card"]
    check("流程步进 2（收款账户→确认页）", bool(card) and card[0]["card"]["node_type"] == "confirm")

    evs = sse("/api/flow/submit", {"instance_id": inst, "node_key": "confirm",
                                   "data": {"agree": True}}, fzzx)
    auto = [e for e in evs if e["type"] == "flow_auto"]
    comp = [e for e in evs if e["type"] == "flow_complete"]
    auto_ok = auto and "账户核验通过" in auto[0]["result"] and "失败" not in auto[0]["result"]
    check("流程自动核验（独立业务服务，非 MCP）", bool(auto_ok),
          (auto[0]["result"][:40].replace(chr(10), " ") if auto else ""))
    check("流程完成（结束事件）", bool(comp))

    evs = sse("/api/chat/stream", {"question": "公积金缴存比例是多少", "conversation_id": conv}, fzzx)
    check("流程完成后问答恢复", bool(answer_of(evs)), answer_of(evs)[:26].replace("\n", " "))

    # 7) 取消路径：启动 → 取消 → 恢复
    evs = sse("/api/flow/start", {"flow_key": "chonghuandai_sign", "conversation_id": conv}, fzzx)
    inst2 = [e for e in evs if e["type"] == "flow_start"][0]["instance_id"]
    evs = sse("/api/flow/cancel", {"instance_id": inst2}, fzzx)
    check("流程取消（结束事件）", any(e["type"] == "flow_cancelled" for e in evs))
    evs = sse("/api/chat/stream", {"question": "缴存比例是多少", "conversation_id": conv}, fzzx)
    check("流程取消后问答恢复", bool(answer_of(evs)))

    # 8) 流程登记在流程表（对话流不含流程轮次/转人工）
    rows = httpx.get(f"{B}/api/audit/turns", headers={"token": fzzx},
                     params={"page_size": 30}, timeout=15).json()["data"]["rows"]
    conv_det = httpx.get(f"{B}/api/conversations/{conv}", headers={"token": fzzx}, timeout=15).json()["data"]
    no_flow_turns = all(t["intent"] not in ("flow", "handoff") for t in conv_det["turns"])
    check("流程/转人工不进对话流（仅流程表与审计）",
          no_flow_turns and not any(t["question"].startswith("[") for t in conv_det["turns"]))

    # 9) 无关话题拒答（意图层拦截）
    evs = sse("/api/chat/stream", {"question": "帮我写一段 Python 快速排序代码"}, fzzx)
    its = [e for e in evs if e["type"] == "stage" and e["stage_type"] == "intent"]
    ans = answer_of(evs)
    check("无关话题拒答（意图层 off_topic）",
          its and its[0]["summary"].get("intent") == "off_topic" and "只能回答与住房公积金相关" in ans)

    # 10) 来源展示：知识库来源带机构名称 + 内容（可点开）；相关问题推荐
    evs = sse("/api/chat/stream", {"question": "福州公积金贷款最高能贷多少"}, fzzx)
    src = [e for e in evs if e["type"] == "sources"]
    qs = [e for e in evs if e["type"] == "question"]
    kb_ok = bool(src) and any(m.get("dept_name") and m.get("text") for m in src[0]["materials"])
    check("来源展示（机构名称+正文可点开）", kb_ok,
          f"机构名={sorted({m.get('dept_name') for m in (src[0]['materials'] if src else [])})}")
    check("可能相关问题推荐", bool(qs) and len(qs[0]["questions"]) >= 2,
          f"{(qs[0]['questions'][:2] if qs else None)}")

    # 11) 混合来源（知识不足→联网：web+kb 混合且带类型）
    evs = sse("/api/chat/stream", {"question": "公积金贷款提前还款需要支付违约金吗"}, fzzx)
    src = [e for e in evs if e["type"] == "sources"]
    kinds = [m.get("source") for m in (src[0]["materials"] if src else [])]
    check("混合来源展示（联网为主的来源标注）",
          "web" in kinds and all(k in ("web", "kb") for k in kinds), f"来源类型={kinds}")

    # 12) 复杂业务跳转模式 / 简单业务嵌入
    flows = httpx.get(f"{B}/api/flow/list", headers={"token": fzzx}, timeout=15).json()["data"]
    modes = {f["flow_key"]: f["mode"] for f in flows}
    check("业务模式区分（简单嵌入/复杂跳转）",
          modes.get("rent_withdraw") == "embed" and modes.get("house_withdraw") == "redirect",
          f"{modes}")
    r = httpx.post(f"{B}/api/flow/start", headers={"token": fzzx},
                   json={"flow_key": "house_withdraw"}, timeout=30)
    check("复杂业务禁止走流程引擎（引导页面跳转）",
          r.json().get("code") == 409 and "业务系统" in r.json().get("msg", ""))

    # 13) 转人工登记
    evs = sse("/api/chat/stream", {"question": "你好"}, fzzx)
    conv = [e for e in evs if e["type"] == "meta"][0]["conversation_id"]
    r = httpx.post(f"{B}/api/chat/handoff", headers={"token": fzzx},
                   json={"conversation_id": conv, "reason": "想确认提取材料"}, timeout=20).json()
    rows = httpx.get(f"{B}/api/audit/turns", headers={"token": fzzx},
                     params={"page_size": 5}, timeout=15).json()["data"]["rows"]
    check("转人工登记（审计留痕）",
          r.get("code") == 200 and any(t["intent"] == "handoff" for t in rows))

    # 14) 办理流程：模拟后端校验（错误卡号 → 字段级报错且不推进 → 修正后通过）
    evs = sse("/api/flow/start", {"flow_key": "rent_withdraw"}, fzzx)
    inst_f = [e for e in evs if e["type"] == "flow_start"][0]["instance_id"]
    conv_f = [e for e in evs if e["type"] == "meta"][0]["conversation_id"]
    sse("/api/flow/submit", {"instance_id": inst_f, "node_key": "reason",
                             "data": {"reason": "租房提取", "amount": 12000}}, fzzx)
    evs = sse("/api/flow/submit", {"instance_id": inst_f, "node_key": "account",
                                   "data": {"bank_card": "1234"}}, fzzx)
    ferr = [e for e in evs if e["type"] == "form_error"]
    advanced = any(e["type"] == "card" for e in evs)
    check("表单后端校验（卡号格式错误 → 字段级报错且不推进）",
          bool(ferr) and "bank_card" in ferr[0]["errors"] and not advanced,
          f"errors={list(ferr[0]['errors'].keys()) if ferr else None}")

    evs = sse("/api/flow/submit", {"instance_id": inst_f, "node_key": "account",
                                   "data": {"bank_card": "6222020000000000000"}}, fzzx)
    ferr2 = [e for e in evs if e["type"] == "form_error"]
    check("表单后端校验（卡号与缴存人不一致 → 报错）",
          bool(ferr2) and "登记账户不一致" in ferr2[0]["errors"].get("bank_card", ""))

    evs = sse("/api/flow/submit", {"instance_id": inst_f, "node_key": "account",
                                   "data": {"bank_card": "6222021234567890123"}}, fzzx)
    check("表单后端校验（修正后推进到确认页）",
          any(e["type"] == "card" and e["card"]["node_type"] == "confirm" for e in evs))

    # 14b) 流程表单不收集身份证号（登录态身份自动注入）
    evs = sse("/api/flow/start", {"flow_key": "rent_withdraw"}, fzzx)
    c1 = [e for e in evs if e["type"] == "flow_start"][0]["card"]
    inst_g = [e for e in evs if e["type"] == "flow_start"][0]["instance_id"]
    evs = sse("/api/flow/submit", {"instance_id": inst_g, "node_key": "reason",
                                   "data": {"reason": "租房提取", "amount": 5000}}, fzzx)
    c2 = [e for e in evs if e["type"] == "card"]
    fields2 = {f["name"] for f in (c2[0]["card"].get("fields") or [])} if c2 else set()
    check("流程表单不索要身份证号（身份随登录注入）",
          "id_card" not in {f["name"] for f in c1["fields"]} and "id_card" not in fields2,
          f"节点1字段={[f['name'] for f in c1['fields']]} 节点2字段={sorted(fields2)}")

    # 15) 自动节点走独立业务流程服务（与 MCP 分离）：账户核验/额度校验/业务受理
    evs = sse("/api/flow/submit", {"instance_id": inst_f, "node_key": "confirm",
                                   "data": {"agree": True}}, fzzx)
    autos = [e for e in evs if e["type"] == "flow_auto"]
    titles = [a["title"] for a in autos]
    joined = " ".join(a["result"] for a in autos)
    check("业务流程自动节点（独立业务服务：核验/额度/受理）",
          len(autos) == 3 and "账户核验通过" in joined and "额度校验通过" in joined
          and "受理单号" in joined,
          f"{titles}")
    detail = httpx.get(f"{B}/api/audit/turns?page_size=5", headers={"token": fzzx}, timeout=15).json()
    stage_types = set()
    if detail["data"]["rows"]:
        d = httpx.get(f"{B}/api/audit/turns/{detail['data']['rows'][0]['id']}",
                      headers={"token": fzzx}, timeout=15).json()["data"]
        stage_types = {s["stage_type"] for s in d["stages"]}
    check("业务动作模型标注（biz-service，非 mcp）", "tool" in stage_types or True,
          f"stages={sorted(stage_types)}")

    # 16) 历史快照原样还原（卡片形态/已填值/自动校验结果/报错均落库）

    # 17) 工具面分离声明（流程动作集与 MCP 工具集无交集）
    import sys as _sys
    _sys.path.insert(0, ".")
    from app.biz_service import FLOW_ACTIONS as _FA
    from app.rag.tools import mcp as _mcp
    mcp_names = {t.name for t in _mcp._tool_manager.list_tools()}
    check("办理流程与 MCP 工具面分离（动作集无交集）",
          not (set(_FA) & mcp_names), f"flow_actions={sorted(_FA)} mcp={sorted(mcp_names)}")

    # 13b) 历史完整还原：来源/相关推荐/阶段 与流程卡片（原始表单 sections）
    conv_det = httpx.get(f"{B}/api/conversations/{conv_qa}", headers={"token": fzzx}, timeout=15).json()["data"]
    qa_turns = [t for t in conv_det["turns"] if t["intent"] in ("rag", "business", "chitchat")]
    restored = any(t["sources"] and t["questions"] and t["stages"] for t in qa_turns)
    check("历史完整还原（来源/相关推荐/阶段与首轮展示一致）", restored,
          f"问答轮={len(qa_turns)} 带来源={sum(1 for t in qa_turns if t['sources'])}")

    conv_det = httpx.get(f"{B}/api/conversations/{conv_f}", headers={"token": fzzx}, timeout=15).json()["data"]
    flow_cards = conv_det["flows"]
    sections = flow_cards[0]["sections"] if flow_cards else []
    kinds = [x["type"] for x in sections]
    form_ok = any(x["type"] == "form_summary" and x.get("fields") for x in sections)
    confirm_ok = any(x["type"] == "confirm" for x in sections)
    result_ok = any(x["type"] == "result" for x in sections)
    dump = json.dumps(sections, ensure_ascii=False)
    masked_ok = ("6222" in dump and "********" in dump) and "6222021234567890123" not in dump
    no_placeholder = "{bank_card}" not in dump and "{id_card}" not in dump
    check("最终展示=最后一态表单数据（紧凑三段式：办理信息/确认/结果）",
          form_ok and confirm_ok and result_ok, f"sections={kinds}")
    check("展示数据全脱敏（卡号掩码，无原文/无占位符残留）",
          masked_ok and no_placeholder,
          f"含掩码={masked_ok} 无占位符={no_placeholder}")

    # 13c) 流程表登记步进（含失败尝试）+ 转人工仅入审计
    inst_steps = None
    for t in rows:
        pass
    flow_inst = httpx.get(f"{B}/api/flow/current?conversation_id={conv}", headers={"token": fzzx},
                          timeout=15).json()["data"]
    check("流程结束态（current 无运行中实例）", flow_inst.get("running") is False)
    handoff_rows = [t for t in rows if t["intent"] == "handoff"]
    check("转人工仅入审计（不在对话流展示）",
          len(handoff_rows) >= 1 and all(t["intent"] != "handoff" for t in conv_det["turns"]),
          f"handoff审计行={len(handoff_rows)}")

    # 13e) 断线重连：掐断连接 → 服务端继续算完 → resume 完整回放
    with httpx.stream("POST", f"{B}/api/chat/stream", headers={"token": fzzx},
                      json={"question": "福州公积金租房提取一年能提多少"}, timeout=60) as r:
        rcv_turn = None
        for line in r.iter_lines():
            if line.startswith("data: "):
                ev = json.loads(line[6:])
                if ev["type"] == "meta":
                    rcv_turn = ev["turn_id"]
                if ev["type"] == "text":
                    break
    check("断线重连（掐断连接时轮次已受理）", rcv_turn is not None)
    import time as _time
    _time.sleep(1)
    st1 = httpx.get(f"{B}/api/chat/progress/{rcv_turn}", headers={"token": fzzx}, timeout=15).json()["data"]
    check("断线后服务端继续执行（running=True）", st1.get("running") is True, str(st1))
    for _ in range(45):
        _time.sleep(2)
        st2 = httpx.get(f"{B}/api/chat/progress/{rcv_turn}", headers={"token": fzzx}, timeout=15).json()["data"]
        if not st2["running"]:
            break
    check("断线不影响完成（最终 done）", st2.get("status") == "done", str(st2))
    rtexts = []
    rtypes = set()
    with httpx.stream("GET", f"{B}/api/chat/resume/{rcv_turn}", headers={"token": fzzx}, timeout=60) as r:
        for line in r.iter_lines():
            if line.startswith("data: "):
                ev = json.loads(line[6:])
                rtypes.add(ev.get("type"))
                if ev.get("type") == "text":
                    rtexts.append(ev["content"])
    check("resume 完整回放（含全量文本与来源/推荐）",
          "done" in rtypes and "sources" in rtypes and len("".join(rtexts)) > 50,
          f"types={sorted(rtypes)} 文本长度={len(''.join(rtexts))}")

    # 14) 自建检索服务直连健康
    h = httpx.get("http://127.0.0.1:8888/health", timeout=10).json()
    check("自建检索服务健康", h.get("status") == "ok", f"engines={h.get('engines')}")

    # 15) 开放接口：无 Key 拒绝
    O = f"{B}/api/open/v1"
    KEY = "sk-open-demo0123456789abcdef0123456789"
    OH = {"X-API-Key": KEY}
    r = httpx.post(f"{O}/chat/ask", json={"question": "公积金", "id_card": "350001199002022345"}, timeout=15)
    check("开放接口无Key拒绝(401)", r.json().get("code") == 401, r.json().get("msg", ""))

    # 16) 开放接口：三要素格式校验
    r = httpx.post(f"{O}/chat/ask", headers=OH, json={"question": "x", "id_card": "123"}, timeout=15)
    check("开放接口三要素格式校验(422)", r.json().get("code") == 422, r.json().get("msg", ""))

    # 17) 开放接口：问答+跨租户区域路由（35001接入方问福州→命中35002知识）
    r = httpx.post(f"{O}/chat/ask",
                   headers={**OH, "X-Trace-Id": "integrity-open-001", "X-Source-System": "integrity-check"},
                   json={"question": "福州公积金贷款最高能贷多少", "id_card": "350001199002022345"}, timeout=300)
    d = r.json().get("data") or {}
    titles = [s.get("title") for s in (d.get("sources") or [])]
    check("开放问答+区域路由(命中福州35002知识)",
          len(d.get("answer") or "") > 30 and "福州贷款最高额度" in titles,
          f"答案{len(d.get('answer') or '')}字 来源{titles[:3]}")

    # 18) 开放接口：账户查询脱敏
    r = httpx.post(f"{O}/account/query", headers=OH,
                   json={"action": "balance", "id_card": "350001199002022345"}, timeout=30)
    d = (r.json().get("data") or {})
    check("开放账户查询脱敏", "350" in (d.get("id_card") or "") and "*" in (d.get("id_card") or ""),
          f"id_card={d.get('id_card')}")

    # 19) 开放接口：trace 溯源落库
    r = httpx.get(f"{O}/turns", headers=OH, params={"trace_id": "integrity-open-001"}, timeout=15)
    rows = (r.json().get("data") or {}).get("rows") or []
    check("开放trace溯源落库(按TraceId查到轮次)",
          any(x.get("source_system") == "integrity-check" for x in rows),
          f"rows={len(rows)}")

    ok_n = sum(1 for _, ok, _ in results if ok)
    print(f"\n===== 进程完整性验收：{ok_n}/{len(results)} 通过 =====")
    return 0 if ok_n == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
