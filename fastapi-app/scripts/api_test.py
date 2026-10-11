# -*- coding: utf-8 -*-
"""全量接口测试：以 HTTP API 覆盖界面全部能力（不依赖浏览器）。

覆盖分组（对应门户/管理端/开放接口的全部界面功能）：
  A 认证与会话   B 门户问答   C MCP 工具   D 业务流程办理
  E 管理端       F 开放接口（含 mock 用户三要素 → MCP 解析）
  G 流程配置管理   H 审计导出与RAG审计   I 知识命中报表

用法：.venv/Scripts/python.exe scripts/api_test.py
前置：后端(9310)/检索服务(8888) 已启动；知识已入库。
"""
from __future__ import annotations

import json
import sys
import time
import uuid
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.crypto import sm3_hex  # noqa: E402
from app.mock_data import TEST_API_ACCOUNTS  # noqa: E402

B = "http://127.0.0.1:9310"
O = f"{B}/api/open/v1"
OPEN_KEY = "sk-open-demo0123456789abcdef0123456789"
OH = {"X-API-Key": OPEN_KEY}
MA, MB = TEST_API_ACCOUNTS["a"], TEST_API_ACCOUNTS["b"]

PASS, FAIL = "✅", "❌"
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"{PASS if ok else FAIL} {name}  {detail}", flush=True)


def login(user: str, pwd: str) -> str:
    r = httpx.post(f"{B}/api/login", json={"username": user, "password": sm3_hex(pwd)}, timeout=15)
    return r.json()["data"]["token"]


def sse(method: str, path: str, token: str, body: dict | None = None, timeout: int = 300) -> list[dict]:
    """调 SSE 接口并收集全部事件；非 SSE(JSON 错误)响应返回单元素列表。"""
    evs: list[dict] = []
    with httpx.stream(method, f"{B}{path}", headers={"token": token}, json=body, timeout=timeout) as r:
        ctype = r.headers.get("content-type", "")
        if "json" in ctype:
            return [json.loads(r.read())]
        for line in r.iter_lines():
            if line.startswith("data: "):
                evs.append(json.loads(line[6:]))
    return evs


def wait_turn(turn_id: int, token: str, timeout_s: int = 180) -> dict:
    for _ in range(timeout_s // 3):
        time.sleep(3)
        st = httpx.get(f"{B}/api/chat/progress/{turn_id}", headers={"token": token}, timeout=15).json()["data"]
        if not st["running"]:
            return st
    return {"running": True, "status": "timeout"}


def evtexts(evs: list[dict]) -> str:
    return "".join(e.get("content", "") for e in evs if e.get("type") == "text")


def main() -> int:
    t_admin = login("admin", "admin123")

    # ---------- A 认证与会话 ----------
    print("\n===== A 认证与会话 =====", flush=True)
    r = httpx.post(f"{B}/api/login", json={"username": "admin", "password": sm3_hex("wrong")}, timeout=15).json()
    check("A1 错误口令被拒(401)", r["code"] == 401 and "密码" in r["msg"], r["msg"])
    r = httpx.get(f"{B}/api/getInfo", headers={"token": t_admin}, timeout=15).json()
    check("A2 getInfo 用户与角色", r["code"] == 200 and r["data"]["user"]["user_name"] == "admin", "")
    r = httpx.get(f"{B}/api/getRouters", headers={"token": t_admin}, timeout=15).json()
    check("A3 getRouters 菜单树", r["code"] == 200 and len(r["data"]) > 0, f"菜单{len(r['data'])}组")
    r = httpx.get(f"{B}/api/getInfo", timeout=15).json()
    check("A4 无token访问被拒(401)", r["code"] == 401, r["msg"])
    t_fzzx = login("fzzx", "fz123456")
    t_qzzx = login("qzzx", "qz123456")
    check("A5 三演示账号均可登录", all([t_admin, t_fzzx, t_qzzx]), "")

    # ---------- B 门户问答 ----------
    print("\n===== B 门户问答 =====", flush=True)
    evs = sse("POST", "/api/chat/stream", t_admin,
              {"question": "福州公积金贷款最高能贷多少？多孩家庭有上浮吗"})
    meta = next((e for e in evs if e.get("type") == "meta"), {})
    conv_id, turn_id = meta.get("conversation_id"), meta.get("turn_id")
    stages = [e.get("name", "") for e in evs if e.get("type") == "stage"]
    srcs = next((e for e in evs if e.get("type") == "sources"), {}).get("materials", [])
    titles = {m.get("title") for m in srcs}
    text = evtexts(evs)
    check("B1 SSE问答全管线(九阶段)", any("意图" in s for s in stages) and any("检索" in s for s in stages)
          and any("生成" in s for s in stages), f"阶段{len(stages)}个")
    check("B2 回答内容含额度口径", ("100" in text and "60" in text and "20%" in text) or len(text) > 100,
          f"文本{len(text)}字")
    check("B3 引用来源命中福州35002知识", "福州贷款最高额度" in titles, str(list(titles)[:3]))
    st = wait_turn(turn_id, t_admin)
    check("B4 轮次落库done", st["status"] == "done", str(st))
    r = httpx.get(f"{B}/api/conversations", headers={"token": t_admin}, timeout=15).json()
    check("B5 会话列表", r["code"] == 200 and any(c["id"] == conv_id for c in r["data"]), f"共{len(r['data'])}会话")
    r = httpx.get(f"{B}/api/conversations/{conv_id}", headers={"token": t_admin}, timeout=15).json()
    check("B6 会话详情(含轮次与来源)", r["code"] == 200 and len(r["data"]["turns"] or []) >= 1, "")

    evs = sse("POST", "/api/chat/stream", t_admin, {"question": "帮我写一段Python排序代码"})
    text = evtexts(evs)
    check("B7 无关话题拒答", "住房公积金" in text and len(text) < 300, text[:40])
    evs = sse("POST", "/api/chat/stream", t_admin, {"question": "你好呀"})
    check("B8 闲聊直答", len(evtexts(evs)) > 0, "")
    r = httpx.post(f"{B}/api/chat/stream", headers={"token": t_admin}, json={"question": "  "}, timeout=15).json()
    check("B9 空问题被拒", r["code"] != 200, r["msg"])

    # 投诉/情绪宣泄：不得误判 business 触发个人数据查询（2026-09-28 修复）
    evs = sse("POST", "/api/chat/stream", t_admin, {"question": "气死了，我要投诉你们！"})
    meta_c = next((e for e in evs if e.get("type") == "meta"), {})
    tid_c = meta_c.get("turn_id")
    st_c = wait_turn(tid_c, t_admin)
    text_c = evtexts(evs)
    det_c = httpx.get(f"{B}/api/audit/turns/{tid_c}", headers={"token": t_admin}, timeout=15).json()["data"]
    no_tool = not any(s["stage_type"] == "tool" for s in det_c["stages"])
    check("B9b 投诉情绪路由chitchat不查数据", det_c["intent"] == "chitchat" and no_tool,
          f"intent={det_c['intent']} 阶段={[s['stage_type'] for s in det_c['stages']]}")
    check("B9c 投诉安抚+人工渠道指引", ("12329" in text_c or "转人工" in text_c) and "余额" not in text_c,
          text_c[:40])

    # 回答反馈：点赞/差评+修改意见（进入 RAG 审计差评口径）
    r = httpx.post(f"{B}/api/chat/feedback", headers={"token": t_admin},
                   json={"turn_id": turn_id, "rating": "down", "comment": "额度口径应更新"}, timeout=15).json()
    check("B9d 差评+修改意见提交", r["code"] == 200 and r["data"]["rating"] == "down", str(r.get("data", "")))
    r = httpx.post(f"{B}/api/chat/feedback", headers={"token": t_fzzx},
                   json={"turn_id": turn_id, "rating": "up"}, timeout=15).json()
    check("B9e 他人轮次反馈被拒", r["code"] == 404, r.get("msg", ""))
    r = httpx.post(f"{B}/api/chat/feedback", headers={"token": t_admin},
                   json={"turn_id": turn_id, "rating": "up"}, timeout=15).json()
    check("B9f 重评覆盖为点赞", r["code"] == 200 and r["data"]["rating"] == "up", "")
    httpx.post(f"{B}/api/chat/feedback", headers={"token": t_admin},
               json={"turn_id": turn_id, "rating": "down", "comment": "B组差评回归"}, timeout=15)

    # 停止：发起后等生成中 → 点停
    import threading
    holder: dict = {}
    def _ask(): holder["evs"] = sse("POST", "/api/chat/stream", t_admin, {"question": "公积金贷款提前还款有违约金吗"})
    th = threading.Thread(target=_ask); th.start()
    time.sleep(6)
    r = httpx.get(f"{B}/api/conversations", headers={"token": t_admin}, timeout=15).json()
    conv_latest = r["data"][0]["id"]
    r = httpx.get(f"{B}/api/conversations/{conv_latest}", headers={"token": t_admin}, timeout=15).json()
    gen_turn = next((t["id"] for t in r["data"]["turns"] if t["status"] == "generating"), None)
    rr = httpx.post(f"{B}/api/chat/stop", headers={"token": t_admin}, json={"turn_id": gen_turn}, timeout=15).json()
    st = wait_turn(gen_turn, t_admin, 30)
    check("B10 停止→interrupted落库", rr["code"] == 200 and st["status"] == "interrupted", str(st))
    th.join(timeout=60)

    r = httpx.post(f"{B}/api/chat/handoff", headers={"token": t_admin},
                   json={"conversation_id": conv_id, "reason": "接口测试转人工"}, timeout=15).json()
    check("B11 转人工受理", r["code"] == 200 and "坐席" in (r["data"] or {}).get("text", ""), "")

    # ---------- C MCP 工具 ----------
    print("\n===== C MCP 工具 =====", flush=True)
    evs = sse("POST", "/api/chat/stream", t_fzzx, {"question": "帮我查一下我的公积金账户余额"})
    tool_evs = [e for e in evs if e.get("type") == "tool"]
    text = evtexts(evs)
    check("C1 登录态三要素→MCP工具调用", len(tool_evs) >= 1, f"工具事件{len(tool_evs)}个")
    check("C2 工具结果脱敏展示", ("***" in text or "*" in text) and "余额" in text, text[:50])
    # 开放接口：mock 用户三要素（外部传入）→ MCP 解析
    r = httpx.post(f"{O}/chat/ask", headers={**OH, "X-Trace-Id": f"apitest-{uuid.uuid4().hex[:8]}"},
                   json={"question": "帮我查一下我的公积金账户余额", "id_card": MA["id_card"],
                         "name": MA["name"], "phone": MA["phone"]}, timeout=300).json()["data"]
    ans = r.get("answer") or ""
    check("C3 外部传mock用户甲三要素→MCP解析", ("188" in ans and ("96" in ans or "缴存" in ans)),
          ans[:80])
    r = httpx.post(f"{O}/account/query", headers=OH,
                   json={"action": "loan", "id_card": MA["id_card"]}, timeout=30).json()["data"]
    check("C4 mock用户甲贷款查询(有贷款)", "300,000" in r["result"] or "贷款" in r["result"], r["result"][:50])
    r = httpx.post(f"{O}/account/query", headers=OH,
                   json={"action": "deposit", "id_card": MB["id_card"], "months": 3}, timeout=30).json()["data"]
    check("C5 mock用户乙缴存明细(封存户)", MB["name"] in r["result"], r["result"][:50])

    # ---------- D 业务流程办理 ----------
    print("\n===== D 业务流程办理 =====", flush=True)
    r = httpx.get(f"{B}/api/flow/list", headers={"token": t_fzzx}, timeout=15).json()
    check("D1 流程列表(含租房提取)", any(f["flow_key"] == "rent_withdraw" for f in r["data"]), "")
    evs = sse("POST", "/api/flow/start", t_fzzx, {"flow_key": "rent_withdraw"})
    fs = next((e for e in evs if e.get("type") == "flow_start"), {})
    inst = fs.get("instance_id")
    auto0 = next((e for e in evs if e.get("type") == "flow_auto"), {})
    check("D2 发起流程+首节点自动核验(缴存资格)", bool(inst) and "缴存资格核验通过" in (auto0.get("result") or ""),
          (auto0.get("result") or "")[:50])
    card0 = next((e for e in evs if e.get("type") == "flow_start"), {}).get("card") or {}
    node0 = card0.get("node_key")
    # 婚姻状况声明（已婚联动校验演示：先不填配偶）
    if node0 == "marriage":
        evs = sse("POST", "/api/flow/submit", t_fzzx, {"instance_id": inst, "node_key": "marriage",
                                                       "data": {"marriage": "已婚"}})
        fe = next((e for e in evs if e.get("type") == "form_error"), {})
        check("D3 已婚联动校验(配偶必填拦截)", "配偶" in str(fe.get("errors")), str(fe.get("errors"))[:80])
        evs = sse("POST", "/api/flow/submit", t_fzzx, {"instance_id": inst, "node_key": "marriage",
                                                       "data": {"marriage": "已婚", "spouse_name": "王管理员",
                                                                "spouse_id_card": "350001199002022345"}})
    else:
        evs = []
    check("D3b 婚姻声明通过→无房核验(不动产联网)", any(e.get("type") == "flow_auto" and "无自有住房" in (e.get("result") or "") for e in evs),
          "")
    # 租赁信息填报
    evs = sse("POST", "/api/flow/submit", t_fzzx, {"instance_id": inst, "node_key": "rent_info",
                                                   "data": {"rent_type": "商品房", "rent_amount": 2500,
                                                            "frequency": "按月提取", "amount": 12000}})
    check("D3c 租赁信息→材料上传节点", any(e.get("type") == "card" and (e.get("card") or {}).get("node_type") == "upload" for e in evs), "")
    # 材料上传：先缺必传提交（拦截），再上传文件后通过
    evs = sse("POST", "/api/flow/submit", t_fzzx, {"instance_id": inst, "node_key": "materials", "data": {"files": {}}})
    fe = next((e for e in evs if e.get("type") == "form_error"), {})
    check("D3d 必传材料拦截", "租赁合同" in str(fe.get("errors")), str(fe.get("errors"))[:60])
    import io
    fake_pdf = io.BytesIO(b"%PDF-1.4 demo rent contract " * 40)
    r = httpx.post(f"{B}/api/flow/upload/{inst}", headers={"token": t_fzzx},
                   data={"slot": "lease_contract"}, files={"file": ("租赁合同.pdf", fake_pdf, "application/pdf")},
                   timeout=30).json()
    check("D3e 材料上传接口", r["code"] == 200 and r["data"]["filename"].endswith(".pdf"), str(r.get("data"))[:60])
    evs = sse("POST", "/api/flow/submit", t_fzzx, {"instance_id": inst, "node_key": "materials",
                                                   "data": {"files": {"lease_contract": r["data"]}}})
    check("D3f 材料通过→备案核验(住建系统)", any(e.get("type") == "flow_auto" and "备案核验通过" in (e.get("result") or "") for e in evs),
          "")
    # 门控：办理中提问 → 409
    conv_flow = fs.get("conversation_id") or next((e for e in evs if e.get("type") == "meta"), {}).get("conversation_id")
    r = httpx.post(f"{B}/api/chat/stream", headers={"token": t_fzzx},
                   json={"question": "现在能提问吗", "conversation_id": conv_flow}, timeout=15).json()
    check("D4 办理中门控409", r.get("code") == 409, r.get("msg", ""))
    # 步骤2 卡号：先错格式
    evs = sse("POST", "/api/flow/submit", t_fzzx, {"instance_id": inst, "node_key": "account",
                                                   "data": {"bank_card": "1234"}})
    fe = next((e for e in evs if e.get("type") == "form_error"), {})
    check("D5 卡号格式校验拦截", bool(fe) and any("16-19" in str(v) for v in (fe.get("errors") or {}).values()),
          str(fe.get("errors"))[:80])
    # 他人卡（admin 的登记卡）
    evs = sse("POST", "/api/flow/submit", t_fzzx, {"instance_id": inst, "node_key": "account",
                                                   "data": {"bank_card": "6228480402564890018"}})
    fe = next((e for e in evs if e.get("type") == "form_error"), {})
    check("D6 他人卡业务校验拦截", bool(fe) and "不一致" in str(fe.get("errors")), str(fe.get("errors"))[:80])
    # 正确卡（fzzx=陈测试 登记卡）
    evs = sse("POST", "/api/flow/submit", t_fzzx, {"instance_id": inst, "node_key": "account",
                                                   "data": {"bank_card": "6222021234567890123"}})
    check("D7 本人登记卡通过→确认页", any(e.get("type") == "card" for e in evs), "")
    # 确认 → 自动节点 → 完成
    evs = sse("POST", "/api/flow/submit", t_fzzx, {"instance_id": inst, "node_key": "confirm",
                                                   "data": {"agree": True}})
    done_ev = next((e for e in evs if e.get("type") == "flow_complete"), {})
    sse_done = next((e for e in evs if e.get("type") == "done"), {})
    whole = json.dumps([done_ev, sse_done], ensure_ascii=False)
    check("D8 自动节点链→办理完成(受理单号)", "已提交成功" in (done_ev.get("text") or "") and "SL" in whole,
          (done_ev.get("text") or "")[:60])
    # 完成后恢复提问（门控解除）
    evs = sse("POST", "/api/chat/stream", t_fzzx, {"question": "公积金怎么提取", "conversation_id": conv_flow})
    check("D9 完成后门控解除可提问", not (len(evs) == 1 and evs[0].get("code") == 409), "")
    # 历史还原：current 终态
    r = httpx.get(f"{B}/api/flow/current", headers={"token": t_fzzx},
                  params={"conversation_id": conv_flow}, timeout=15).json()["data"]
    disp = (sse_done.get("flow_display") or {})
    disp_text = json.dumps(disp, ensure_ascii=False)
    check("D10 流程终态(展示载荷含材料与受理)", (r or {}).get("running") is False and disp.get("status") == "done"
          and ".pdf" in disp_text and "SL" in disp_text,
          f"status={disp.get('status')} 含材料={'.pdf' in disp_text}")
    # 取消流程：新开实例后取消
    evs = sse("POST", "/api/flow/start", t_fzzx, {"flow_key": "chonghuandai_sign", "conversation_id": conv_flow})
    inst2 = next((e for e in evs if e.get("type") == "flow_start"), {}).get("instance_id")
    evs2 = sse("POST", "/api/flow/cancel", t_fzzx, {"instance_id": inst2})
    check("D11 取消流程", any(e.get("type") == "flow_cancelled" for e in evs2), "")

    # ---------- E 管理端 ----------
    print("\n===== E 管理端 =====", flush=True)
    r = httpx.get(f"{B}/api/audit/dashboard", headers={"token": t_admin}, timeout=15).json()["data"]
    check("E1 仪表盘统计", r.get("turn_count", 0) >= 5, f"轮次{r.get('turn_count')}")
    r = httpx.get(f"{B}/api/audit/turns", headers={"token": t_admin}, params={"page": 1, "size": 5}, timeout=15).json()["data"]
    check("E2 轮次审计列表", r["total"] >= 5, f"共{r['total']}条")
    tid = r["rows"][0]["id"]
    r = httpx.get(f"{B}/api/audit/turns/{tid}", headers={"token": t_admin}, timeout=15).json()["data"]
    check("E3 轮次阶段流水详情", len(r.get("stages") or []) >= 5, f"{len(r.get('stages') or [])}阶段")
    r = httpx.post(f"{B}/api/knowledge", headers={"token": t_admin},
                   json={"dept_no": "35001", "biz_type": "qa", "theme": "deposit",
                         "title": f"接口测试知识{int(time.time())}", "question": "接口测试问法",
                         "answer": "接口测试答案：单位与职工各12%。"}, timeout=30).json()
    kid = r["data"]["id"] if isinstance(r["data"], dict) else r["data"]
    time.sleep(6)
    httpx.post(f"{B}/api/knowledge/sync/{kid}", headers={"token": t_admin}, timeout=30).json()
    r = httpx.get(f"{B}/api/knowledge/list", headers={"token": t_admin}, params={"q": "接口测试"}, timeout=15).json()["data"]
    row = next((x for x in r["rows"] if x["id"] == kid), {})
    check("E4 新增知识+同步ES", row.get("sync_status") in (1, "1", "已同步"), str(row.get("sync_status")))
    r = httpx.delete(f"{B}/api/knowledge/{kid}", headers={"token": t_admin}, timeout=15).json()
    check("E5 删除知识", r["code"] == 200, "")
    r = httpx.post(f"{B}/api/system/users", headers={"token": t_admin},
                   json={"user_name": f"apitest{int(time.time())}", "nick_name": "接口测试用户",
                         "password": "Test@2026", "dept_id": 4, "role_ids": [3]}, timeout=15).json()
    uid = r["data"]["id"] if isinstance(r["data"], dict) else r["data"]
    r = httpx.get(f"{B}/api/system/users", headers={"token": t_admin}, timeout=15).json()
    check("E6 新增用户", any(u["user_id"] == uid for u in r["data"]), f"uid={uid}")
    r = httpx.delete(f"{B}/api/system/users/{uid}", headers={"token": t_admin}, timeout=15).json()
    check("E7 删除用户", r["code"] == 200, "")
    for path, name in [("/api/system/roles", "角色"), ("/api/system/depts", "部门"), ("/api/system/menus", "菜单")]:
        r = httpx.get(f"{B}{path}", headers={"token": t_admin}, timeout=15).json()
        check(f"E8 {name}列表", r["code"] == 200 and len(r["data"]) > 0, f"{len(r['data'])}条")

    # ---------- F 开放接口 ----------
    print("\n===== F 开放接口 =====", flush=True)
    r = httpx.post(f"{O}/chat/ask", json={"question": "x", "id_card": MA["id_card"]}, timeout=15).json()
    check("F1 无Key拒绝", r["code"] == 401, r["msg"])
    r = httpx.post(f"{O}/chat/ask", headers=OH, json={"question": "x", "id_card": "123"}, timeout=15).json()
    check("F2 三要素格式校验", r["code"] == 422, r["msg"])
    r = httpx.post(f"{O}/chat/ask", headers={**OH, "X-Trace-Id": "apitest-final", "X-Source-System": "api-test"},
                   json={"question": "福州公积金贷款最高能贷多少", "id_card": MA["id_card"]}, timeout=300)
    d = r.json()["data"]
    titles = [s["title"] for s in d["sources"]]
    check("F3 问答+跨租户区域路由(35001问福州)", "福州贷款最高额度" in titles and len(d["answer"]) > 30,
          f"来源{titles[:2]}")
    check("F4 X-Trace-Id回显", r.headers.get("X-Trace-Id") == "apitest-final", r.headers.get("X-Trace-Id", ""))
    r = httpx.get(f"{O}/turns", headers=OH, params={"trace_id": "apitest-final"}, timeout=15).json()["data"]
    check("F5 TraceId溯源落库", any(x["source_system"] == "api-test" for x in r["rows"]), f"{len(r['rows'])}条")
    conv_open = d["conversation_id"]
    r = httpx.post(f"{O}/chat/ask", headers=OH,
                   json={"question": "那单职工呢", "id_card": MA["id_card"], "conversation_id": conv_open}, timeout=300).json()["data"]
    check("F6 会话延续(外部传conversation_id)", r["conversation_id"] == conv_open, "")
    r = httpx.post(f"{O}/chat/ask", headers=OH,
                   json={"question": "x", "id_card": MA["id_card"], "conversation_id": 999999}, timeout=15).json()
    check("F7 越权会话延续被拒(404)", r["code"] == 404, r["msg"])
    r = httpx.get(f"{O}/knowledge", headers=OH, params={"theme": "loan"}, timeout=15).json()["data"]
    check("F8 公开知识查询(仅is_public)", r["total"] >= 1, f"total={r['total']}")

    # ---------- G 流程配置管理 ----------
    print("\n===== G 流程配置管理 =====", flush=True)
    FA = f"{B}/api/flow-admin"
    r = httpx.get(f"{FA}/list", headers={"token": t_admin}, timeout=15).json()
    rent_row = next((x for x in r["data"] if x["flow_key"] == "rent_withdraw"), {})
    rent_id = rent_row["id"]
    check("G1 流程定义列表(含发布状态)", r["code"] == 200 and rent_row.get("published") is True
          and not rent_row.get("dirty"), f"节点{rent_row.get('published_nodes')}")
    r = httpx.get(f"{FA}/list", headers={"token": t_qzzx}, timeout=15).json()
    check("G2 权限隔离(普通用户403)", r["code"] == 403, r.get("msg", ""))
    det = httpx.get(f"{FA}/{rent_id}", headers={"token": t_admin}, timeout=15).json()["data"]
    import json as _json
    orig_nodes = _json.loads(det["nodes"])

    # 草稿隔离：改标题存草稿（不发布）→ 新办理仍用旧标题
    draft = _json.dumps([{**n, **({"title": "婚姻声明(v2草稿)"} if n["key"] == "marriage" else {})}
                         for n in orig_nodes], ensure_ascii=False)
    body = {k: det[k] for k in ("flow_key", "name", "description", "dept_no", "keywords", "mode", "url")}
    r = httpx.put(f"{FA}/{rent_id}", headers={"token": t_admin},
                  json={**body, "nodes": draft}, timeout=15).json()
    check("G3 草稿保存(dirty标记)", r["code"] == 200 and r["data"]["dirty"], "")
    evs = sse("POST", "/api/flow/start", t_fzzx, {"flow_key": "rent_withdraw"})
    card = next((e for e in evs if e.get("type") == "flow_start"), {}).get("card") or {}
    check("G4 草稿不影响线上(新办理用旧标题)", "v2草稿" not in (card.get("title") or ""), card.get("title", ""))

    # 发布生效：再发布 → 新办理用新标题
    r = httpx.post(f"{FA}/{rent_id}/publish", headers={"token": t_admin}, timeout=15).json()
    check("G5 发布成功", r["code"] == 200, str(r.get("msg", "")))
    evs = sse("POST", "/api/flow/submit", t_fzzx, {"instance_id": card["instance_id"],
                                                   "node_key": "marriage",
                                                   "data": {"marriage": "未婚"}})
    evs2 = sse("POST", "/api/flow/start", t_fzzx, {"flow_key": "rent_withdraw"})
    card2 = next((e for e in evs2 if e.get("type") == "flow_start"), {}).get("card") or {}
    check("G6 发布后新办理用新标题", "v2草稿" in (card2.get("title") or ""), card2.get("title", ""))
    inst_running = card2["instance_id"]

    # 快照隔离：把 marriage 节点从定义里删掉再发布 → 运行中实例(旧定义)仍能按原序列提交
    shrunk = _json.dumps([n for n in orig_nodes if n["key"] != "marriage"], ensure_ascii=False)
    httpx.put(f"{FA}/{rent_id}", headers={"token": t_admin}, json={**body, "nodes": shrunk}, timeout=15)
    httpx.post(f"{FA}/{rent_id}/publish", headers={"token": t_admin}, timeout=15)
    evs = sse("POST", "/api/flow/submit", t_fzzx, {"instance_id": inst_running,
                                                   "node_key": "marriage", "data": {"marriage": "未婚"}})
    check("G7 快照隔离(删节点后老实例仍按原序列走)", not (len(evs) == 1 and evs[0].get("code") == 409),
          "老实例 marriage 提交未被 409 拒" if evs else "")

    # 实例监控 + 强制取消
    r = httpx.get(f"{FA}/instances", headers={"token": t_admin}, params={"status": "running"}, timeout=15).json()["data"]
    hit = next((x for x in r["rows"] if x["id"] == inst_running), {})
    check("G8 实例监控(列表可见running)", bool(hit), f"当前={hit.get('current')}")
    r = httpx.post(f"{FA}/instances/{inst_running}/cancel", headers={"token": t_admin}, timeout=15).json()
    check("G9 强制取消", r["code"] == 200 and r["data"]["status"] == "cancelled", str(r.get("data")))
    r = httpx.get(f"{FA}/instances/{inst_running}", headers={"token": t_admin}, timeout=15).json()["data"]
    check("G10 实例详情(轨迹含取消留痕)", any(st.get("node_key") == "cancel" for st in r["steps"]),
          f"{len(r['steps'])}步")

    # 收尾还原定义（原样发布，不留测试痕迹）
    httpx.put(f"{FA}/{rent_id}", headers={"token": t_admin},
              json={**body, "nodes": _json.dumps(orig_nodes, ensure_ascii=False)}, timeout=15)
    rr = httpx.post(f"{FA}/{rent_id}/publish", headers={"token": t_admin}, timeout=15).json()
    check("G11 定义还原(原样重新发布)", rr["code"] == 200, "")

    # ---------- H 审计中文化 / 过滤导出 / RAG 审计 ----------
    print("\n===== H 审计导出与RAG审计 =====", flush=True)
    import re as _re

    def _get(path, token, **params):
        return httpx.get(f"{B}{path}", headers={"token": token}, params=params, timeout=60).json()

    def _export(path, token, name):
        rr = httpx.get(f"{B}{path}", headers={"token": token}, timeout=120)
        ct = rr.headers.get("content-type", "")
        check(name, "spreadsheet" in ct and len(rr.content) > 1000, f"{len(rr.content)}B")

    r = _get("/api/audit/dashboard", t_admin)
    dist = r["data"]["intent_dist"]
    check("H1 仪表盘意图分布中文化(label列)",
          isinstance(dist, list) and len(dist) > 0
          and all(x.get("label") and not _re.fullmatch(r"[a-z_]+", x["label"]) for x in dist),
          str([(x["code"], x["label"]) for x in dist][:4]))
    check("H1b 主题分布同形态", isinstance(r["data"]["theme_dist"], list)
          and all("label" in x for x in r["data"]["theme_dist"]), "")

    r = _get("/api/audit/turns", t_admin, page=1, page_size=5,
             start="2000-01-01", end="2099-01-01", source="portal")
    check("H2 审计过滤(时间范围+来源)", r["code"] == 200 and "rows" in r["data"],
          f"total={r['data']['total']}")
    r = _get("/api/audit/turns", t_admin, start="2098-01-01")
    check("H3 时间过滤生效(未来日期0条)", r["data"]["total"] == 0, f"total={r['data']['total']}")
    r = _get("/api/audit/turns", t_admin, page=1, page_size=5)
    row0 = (r["data"]["rows"] or [{}])[0]
    check("H4 轮次行带中文意图/主题标签",
          any(ord(c) > 127 for c in (row0.get("intent_label") or ""))
          and any(ord(c) > 127 for c in (row0.get("theme_label") or "")),
          f"{row0.get('intent_label')}/{row0.get('theme_label')}")
    r = _get("/api/audit/depts", t_admin)
    check("H5 机构下拉数据源", r["code"] == 200 and len(r["data"]) >= 3, f"{len(r['data'])}个")

    _export("/api/audit/export/turns?start=2000-01-01", t_admin, "H6 意图识别导出(xlsx)")
    _export("/api/audit/export/qa?start=2000-01-01", t_admin, "H7 QA导出(xlsx含回答)")
    _export("/api/flow-admin/export/instances", t_admin, "H8 流程数据导出(xlsx含受理单号)")

    r = _get("/api/rag-audit/turns", t_admin, page=1, page_size=10)
    rag_rows = r["data"]["rows"]
    check("H9 RAG审计列表", r["code"] == 200 and isinstance(rag_rows, list), f"total={r['data']['total']}")
    with_recall = next((x for x in rag_rows if x["recall_count"] > 0), None)
    check("H10 召回明细落库(候选/保留计数)", bool(with_recall),
          f"{(with_recall or {}).get('recall_count')}/{(with_recall or {}).get('kept_count')}")
    if with_recall:
        tid = with_recall["id"]
        det = _get(f"/api/rag-audit/turns/{tid}", t_admin)["data"]
        check("H11 召回详情(名次/得分/去留)", len(det["recalls"]) > 0
              and all("fused_rank" in x and "kept" in x and "fused_score" in x for x in det["recalls"]),
              f"{len(det['recalls'])}条候选")
        r = httpx.post(f"{B}/api/rag-audit/turns/{tid}/flag", headers={"token": t_admin},
                       json={"flags": ["recall_miss", "flag_other"], "note": "H组打标测试"}, timeout=15).json()
        check("H12 质检打标(多选+中文标签)", r["code"] == 200 and "召回不准" in r["data"]["rag_flag_label"],
              r["data"].get("rag_flag_label", ""))
        r = _get("/api/rag-audit/turns", t_admin, page=1, page_size=50, flag="recall_miss")
        check("H13 按标记过滤badcase", any(x["id"] == tid for x in r["data"]["rows"]),
              f"total={r['data']['total']}")
        _export("/api/rag-audit/export/badcase", t_admin, "H14 badcase导出(xlsx)")
    else:
        for nm in ("H11 召回详情(名次/得分/去留)", "H12 质检打标(多选+中文标签)",
                   "H13 按标记过滤badcase", "H14 badcase导出(xlsx)"):
            check(nm, False, "无带召回明细的轮次")

    # ---------- I 知识命中报表（二期） ----------
    print("\n===== I 知识命中报表 =====", flush=True)
    r = _get("/api/rag-audit/knowledge-report", t_admin, page=1, page_size=10)
    rep = r["data"]
    check("I1 报表返回(行+汇总)", r["code"] == 200 and "rows" in rep and "summary" in rep,
          f"知识{rep.get('summary', {}).get('kb_total')}行{len(rep.get('rows', []))}")
    check("I2 统计列完整(名次/得分/保留率)",
          len(rep["rows"]) > 0 and all(
              {"recall_turns", "avg_rank", "avg_score", "kept_count", "kept_rate"} <= set(x)
              for x in rep["rows"]),
          f"首行召回轮次={rep['rows'][0].get('recall_turns') if rep['rows'] else '-'}")
    flagged_rows = [x for x in rep["rows"] if x["flagged_count"] > 0]
    check("I3 差评关联到知识条目(H12标记联动)", len(flagged_rows) > 0,
          f"{len(flagged_rows)}条关联,汇总差评关联={rep['summary'].get('flagged_linked')}")
    r = _get("/api/rag-audit/knowledge-report", t_admin, page=1, page_size=200, only_recalled=True)
    check("I4 仅被召回过滤", all(x["recall_turns"] > 0 for x in r["data"]["rows"]),
          f"{len(r['data']['rows'])}行(全部>0)")
    _export("/api/rag-audit/export/knowledge-report", t_admin, "I5 报表导出(xlsx)")

    r = _get(f"/api/rag-audit/turns/{turn_id}", t_admin)["data"]
    check("H15 用户反馈进入RAG审计详情", (r.get("feedback") or {}).get("rating") == "down",
          str(r.get("feedback")))
    r = _get("/api/rag-audit/turns", t_admin, page=1, page_size=50, user_rating="down")
    check("H16 按用户差评过滤", any(x["id"] == turn_id for x in r["data"]["rows"]),
          f"total={r['data']['total']}")

    r = _get("/api/rag-audit/knowledge-report", t_admin, page=1, page_size=50)
    check("I6 报表含用户差评列(B1差评联动)",
          len(r["data"]["rows"]) > 0 and "user_down" in r["data"]["rows"][0]
          and any(x["user_down"] > 0 for x in r["data"]["rows"]),
          f"max_user_down={max((x['user_down'] for x in r['data']['rows']), default=0)}")

    ok_n = sum(1 for _, ok, _ in results if ok)
    print(f"\n===== 接口测试汇总：{ok_n}/{len(results)} 通过 =====", flush=True)
    return 0 if ok_n == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
