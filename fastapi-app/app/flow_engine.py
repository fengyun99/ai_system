# -*- coding: utf-8 -*-
"""业务流程引擎——线性步进状态机（form → confirm → auto → end）。

设计取舍（对齐"轮次表即审计"的精简口径）：
  定义（flow_def）+ 实例（flow_instance）两张表；实例的 vars 保存已收集变量、
  steps 保存步进历史（谁在哪个节点提交了什么、自动节点执行结果），审计不新增表。

门控语义：实例 status=running 期间该会话禁止提问（chat 入口拦截），
完成（done）或取消（cancelled）后恢复问答。
"""
from __future__ import annotations

import json
from datetime import datetime

from app.biz_service import BizFormError, FLOW_ACTIONS, validate_field
from app.common.response import BizError
from app.models import FlowDef, FlowInstance

# 说明：办理流程的自动节点**只允许**调用 app.biz_service 暴露的业务动作（模拟业务系统），
# 与 MCP 工具面（app/rag/tools.py，供问答/大模型调用）完全分离，二者互不复用。


_FLOW_DEF_CACHE: dict[int, object] = {}


def _parse(raw: str, default):
    try:
        return json.loads(raw or "")
    except (json.JSONDecodeError, TypeError):
        return default


def load_nodes(flow_def: FlowDef) -> list[dict]:
    """引擎侧节点：只读**已发布**定义（草稿不影响线上）。"""
    published = (flow_def.published_nodes or "").strip()
    return _parse(published if published else "[]", [])


def load_draft_nodes(flow_def: FlowDef) -> list[dict]:
    """管理端草稿节点（编辑中版本）。"""
    return _parse(flow_def.nodes, [])


def invalidate_flow_def_cache(flow_def_id: int | None = None) -> None:
    """发布/删除后失效引擎定义缓存（下次访问重读数据库）。"""
    if flow_def_id is None:
        _FLOW_DEF_CACHE.clear()
    else:
        _FLOW_DEF_CACHE.pop(flow_def_id, None)


def current_node(instance: FlowInstance, flow_def: FlowDef) -> dict | None:
    # 快照优先：运行中的实例永远按发起时的发布版走，定义后续变更不影响
    snapshot = (instance.nodes_snapshot or "").strip()
    nodes = _parse(snapshot, None) if snapshot else None
    if nodes is None:
        nodes = load_nodes(flow_def)
    if instance.current_index >= len(nodes):
        return None
    return nodes[instance.current_index]


async def get_running(conversation_id: int) -> FlowInstance | None:
    return await FlowInstance.filter(conversation_id=conversation_id, status="running").first()


def _render_summary(template: str, vars_: dict) -> str:
    """渲染摘要模板；敏感字段（卡号/证件号/手机号）脱敏后展示。"""
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


def _user_step_pos(flow_def: FlowDef, instance: FlowInstance) -> tuple[int, int]:
    """用户可见步骤（form/confirm）的进度：系统节点（auto/end）不占步骤。"""
    nodes = load_nodes(flow_def)
    interactive = [n["key"] for n in nodes if n["type"] in ("form", "upload", "confirm")]
    cur = nodes[instance.current_index]["key"] if instance.current_index < len(nodes) else ""
    pos = interactive.index(cur) + 1 if cur in interactive else len(interactive)
    return pos, len(interactive)


def _node_card(node: dict, vars_: dict, instance: FlowInstance, total: int) -> dict:
    """把节点定义转为前端卡片事件（不含内部字段）。

    progress 以**用户交互步**计（填表/确认）：系统核验（auto）与完成（end）不计入。
    """
    flow_def = _FLOW_DEF_CACHE.get(instance.flow_def_id)
    if flow_def:
        pos, cnt = _user_step_pos(flow_def, instance)
    else:
        pos, cnt = instance.current_index + 1, total
    card = {
        "instance_id": instance.id,
        "node_key": node["key"],
        "node_type": node["type"],
        "title": node.get("title", ""),
        "progress": f"{pos}/{cnt}",
    }
    if node["type"] == "form":
        card["fields"] = [
            {k: f.get(k) for k in ("name", "label", "type", "options", "required", "placeholder") if k in f}
            for f in node.get("fields", [])
        ]
    elif node["type"] == "upload":
        uploaded = vars_.get("files") or {}
        card["files"] = [
            {"name": f["name"], "label": f.get("label", f["name"]), "required": bool(f.get("required")),
             "accept": f.get("accept", "image/*,application/pdf"),
             "uploaded": uploaded.get(f["name"]) or None}
            for f in node.get("files", [])
        ]
    elif node["type"] == "confirm":
        card["summary"] = _render_summary(node.get("summary_template", ""), vars_)
    elif node["type"] == "end":
        card["text"] = node.get("text", "办理完成")
    return card


async def start_flow(conversation_id: int, user, flow_key: str) -> dict:
    """开始办理：建实例 → 返回首个节点卡片与开场文案。"""
    running = await get_running(conversation_id)
    if running:
        raise BizError("当前会话已有进行中的业务流程，请先完成或取消", 409)
    flow_def = await FlowDef.filter(flow_key=flow_key, status=1).first()
    if not flow_def:
        raise BizError("流程不存在或已停用", 404)
    if (flow_def.mode or "embed") == "redirect":
        # 复杂业务：不走流程引擎，前端按 url 跳转业务页面
        raise BizError(f"该业务需前往业务系统办理：{flow_def.url}", 409)

    # 身份注入：身份证号/姓名/手机号随登录态带入流程变量（内置字段，不进表单、不明文展示）
    seed_vars = {
        "id_card": getattr(user, "id_card", "") or "",
        "name": getattr(user, "nick_name", "") or "",
        "phone": getattr(user, "phone", "") or "",
    }
    seed_vars = {k: v for k, v in seed_vars.items() if v}
    published_nodes = (flow_def.published_nodes or "").strip()
    if not published_nodes:
        raise BizError("该流程尚未发布，暂不能办理", 409)
    instance = await FlowInstance.create(
        flow_def_id=flow_def.id, conversation_id=conversation_id,
        user_id=user.user_id, dept_no=user.dept_no, status="running",
        nodes_snapshot=published_nodes,
        current_index=0, vars=json.dumps(seed_vars, ensure_ascii=False), steps=json.dumps(
            [{"node_key": "start", "node_type": "start", "at": _now(),
              "actor": user.user_name}], ensure_ascii=False),
    )
    _FLOW_DEF_CACHE[flow_def.id] = flow_def

    # 首节点为系统核验（auto）时服务端直接执行并推进到首个交互节点
    auto_events: list[dict] = []
    vars_now = dict(seed_vars)
    while True:
        node = current_node(instance, flow_def)
        if not node or node["type"] != "auto":
            break
        action = FLOW_ACTIONS.get(node.get("action", ""))
        import inspect
        accepted = set(inspect.signature(action).parameters) if action else set()
        args = {**(node.get("action_args") or {}),
                **{k: v for k, v in vars_now.items() if k in accepted}}
        result = action(**args) if action else f"业务动作 {node.get('action')} 未注册"
        steps = _parse(instance.steps, [])
        steps.append({"node_key": node["key"], "node_type": "auto", "at": _now(),
                      "actor": "system", "result": result})
        instance.steps = json.dumps(steps, ensure_ascii=False)
        instance.current_index += 1
        await instance.save(update_fields=["steps", "current_index"])
        auto_events.append({"type": "flow_auto", "node_key": node["key"],
                            "title": node.get("title", node["key"]), "result": result})

    intro = f"好的，已为您启动「{flow_def.name}」。办理过程中问答将暂停，完成或取消后可继续咨询。"
    return {"ok": True, "instance": instance, "flow_def": flow_def, "node": node,
            "intro": intro, "vars": seed_vars, "auto_events": auto_events,
            "card": _node_card(node, dict(seed_vars, **vars_now), instance, len(load_nodes(flow_def))) if node else None,
            "step_node": "start"}


async def submit_node(instance_id: int, user, node_key: str, data: dict) -> dict:
    """提交当前节点：校验 → 收集变量 → 推进（自动节点顺手执行动作）。"""
    instance = await FlowInstance.get_or_none(id=instance_id)
    if not instance or instance.user_id != user.user_id:
        raise BizError("流程实例不存在", 404)
    if instance.status != "running":
        raise BizError("流程已结束", 409)
    flow_def = await instance.flow_def
    _FLOW_DEF_CACHE[flow_def.id] = flow_def
    nodes = load_nodes(flow_def)
    node = current_node(instance, flow_def)
    if node is None:
        raise BizError("流程状态异常（无当前节点）", 500)
    if node_key != node["key"]:
        # 步进校验：禁止跳步/回退
        raise BizError(f"当前节点为「{node.get('title') or node['key']}」，不能提交其它节点", 409)

    vars_ = _parse(instance.vars, {})
    steps = _parse(instance.steps, [])
    events: list[dict] = []
    auto_result = ""

    if node["type"] == "form":
        errors: dict[str, str] = {}
        # 先合并历史变量，保证联动校验（如卡号校验依赖身份证号）拿到完整上下文
        merged = {**vars_, **(data or {})}
        for f in node.get("fields", []):
            name = f["name"]
            val = data.get(name)
            if f.get("required") and (val is None or str(val).strip() == ""):
                errors[name] = f"请填写「{f.get('label', name)}」"
                continue
            if val is None or str(val).strip() == "":
                # 空值也过一遍联动校验（如"已婚必填配偶"规则依赖空值触发）
                rule0 = f.get("validate")
                if rule0:
                    msg0 = validate_field(rule0, "", merged)
                    if msg0:
                        errors[name] = msg0
                        continue
                continue
            if f.get("type") == "number":
                try:
                    val = float(val)
                except (TypeError, ValueError):
                    errors[name] = f"「{f.get('label', name)}」必须为数字"
                    continue
            rule = f.get("validate")
            if rule:
                msg = validate_field(rule, val, merged)
                if msg:
                    errors[name] = msg
                    continue
            vars_[name] = val
        if errors:
            # 表单校验不通过：登记失败尝试（历史可还原报错）→ 不推进节点，错误回传前端红色提示
            steps.append({"node_key": node["key"], "node_type": node["type"], "at": _now(),
                          "actor": user.user_name, "data": data, "errors": errors,
                          "status": "invalid"})
            instance.steps = json.dumps(steps, ensure_ascii=False)
            await instance.save(update_fields=["steps"])
            return {"ok": False, "errors": errors, "node": node, "instance": instance,
                    "flow_def": flow_def, "text": "表单校验未通过，请按提示修改后重新提交。"}
    elif node["type"] == "upload":
        # 材料上传节点：data.files = {槽位: {filename, size}}（文件已先经 /flow/upload 上传）
        up_errors: dict[str, str] = {}
        files = {k: v for k, v in (data.get("files") or {}).items()
                 if isinstance(v, dict) and v.get("filename")}
        for f in node.get("files", []):
            if f.get("required") and f["name"] not in files:
                up_errors[f["name"]] = f"请上传「{f.get('label', f['name'])}」"
        if up_errors:
            steps.append({"node_key": node["key"], "node_type": node["type"], "at": _now(),
                          "actor": user.user_name, "data": data, "errors": up_errors,
                          "status": "invalid"})
            instance.steps = json.dumps(steps, ensure_ascii=False)
            await instance.save(update_fields=["steps"])
            return {"ok": False, "errors": up_errors, "node": node, "instance": instance,
                    "flow_def": flow_def, "text": "材料上传不完整，请按提示补齐后重新提交。"}
        # 材料清单入变量（终态展示/备案核验动作使用）
        vars_["files"] = files
    elif node["type"] == "confirm":
        if not data.get("agree"):
            # 确认节点拒绝 = 取消流程（对齐"取消业务流程后恢复问答"）
            return await cancel_flow(instance_id, user, reason="用户在确认页取消")

    steps.append({"node_key": node["key"], "node_type": node["type"], "at": _now(),
                  "actor": user.user_name, "data": data})

    # 推进到下一节点（连续 auto 节点在服务端直接执行）
    instance.current_index += 1
    while True:
        nxt = current_node(instance, flow_def)
        if nxt is None:
            break
        if nxt["type"] == "auto":
            action = FLOW_ACTIONS.get(nxt.get("action", ""))
            # 只透传动作签名接受的参数（避免把流程全部变量塞给工具）
            import inspect
            accepted = set(inspect.signature(action).parameters) if action else set()
            args = {**(nxt.get("action_args") or {}),
                    **{k: v for k, v in vars_.items() if k in accepted}}
            try:
                auto_result = action(**args) if action else f"业务动作 {nxt.get('action')} 未注册"
            except Exception as e:  # noqa: BLE001 自动节点失败不摧毁流程，显形并继续
                auto_result = f"业务校验执行失败: {e}"
            steps.append({"node_key": nxt["key"], "node_type": "auto", "at": _now(),
                          "actor": "system", "action": nxt.get("action"), "result": auto_result[:500]})
            events.append({"type": "flow_auto", "node_key": nxt["key"],
                           "title": nxt.get("title", ""), "result": auto_result[:600]})
            instance.current_index += 1
            continue
        break

    nxt = current_node(instance, flow_def)
    done = nxt is None or nxt.get("type") == "end"
    instance.vars = json.dumps(vars_, ensure_ascii=False)
    if done:
        instance.status = "done"
        steps.append({"node_key": "done", "node_type": "end", "at": _now(), "actor": "system"})
    instance.steps = json.dumps(steps, ensure_ascii=False)
    await instance.save()

    if done:
        end_node = nxt or {"key": "done", "type": "end", "title": "办理完成"}
        text = (end_node.get("text") or "您的申请已提交成功，办理流程结束。")
        if auto_result:
            text = f"{text}\n\n（自动核验结果：{auto_result[:300]}）" if "失败" in auto_result else text
        events.append({"type": "flow_complete", "instance_id": instance.id,
                       "flow_name": flow_def.name, "text": text})
        return {"ok": True, "instance": instance, "flow_def": flow_def, "node": None,
                "events": events, "done": True, "text": text, "auto_result": auto_result,
                "vars": vars_, "submitted": data}
    return {"ok": True, "instance": instance, "flow_def": flow_def, "node": nxt,
            "events": events, "done": False, "auto_result": auto_result,
            "vars": vars_, "submitted": data,
            "card": _node_card(nxt, vars_, instance, len(nodes))}


async def cancel_flow(instance_id: int, user, reason: str = "用户取消", force: bool = False) -> dict:
    # force=True：管理员强制取消（流程配置管理），跳过"本人实例"校验
    instance = await FlowInstance.get_or_none(id=instance_id)
    if not instance or (not force and instance.user_id != user.user_id):
        raise BizError("流程实例不存在", 404)
    if instance.status != "running":
        raise BizError("流程已结束", 409)
    flow_def = await instance.flow_def
    steps = _parse(instance.steps, [])
    steps.append({"node_key": "cancel", "node_type": "cancel", "at": _now(),
                  "actor": user.user_name, "reason": reason})
    instance.status = "cancelled"
    instance.steps = json.dumps(steps, ensure_ascii=False)
    await instance.save()
    text = f"已为您取消「{flow_def.name}」。现在可以继续向我提问了。"
    return {"instance": instance, "flow_def": flow_def, "node": None, "done": True,
            "events": [{"type": "flow_cancelled", "instance_id": instance.id, "text": text}],
            "text": text, "auto_result": ""}


async def current_state(conversation_id: int, user) -> dict:
    """会话当前流程状态（刷新页面后恢复 UI 用）。"""
    instance = await get_running(conversation_id)
    if not instance or instance.user_id != user.user_id:
        return {"running": False}
    flow_def = await instance.flow_def
    nodes = load_nodes(flow_def)
    node = current_node(instance, flow_def)
    return {
        "running": True,
        "instance_id": instance.id,
        "flow_key": flow_def.flow_key,
        "flow_name": flow_def.name,
        "card": _node_card(node, _parse(instance.vars, {}), instance, len(nodes)) if node else None,
    }


async def recommend_flows(dept_no: str, question: str) -> list[dict]:
    """办理推荐：关键词命中的启用流程（管理端可新增流程即时生效）。"""
    rows = await FlowDef.filter(status=1)
    hits = []
    for f in rows:
        if f.dept_no != dept_no and f.dept_no != "35000":
            continue
        words = [w for w in (f.keywords or "").split() if w]
        if any(w in question for w in words):
            hits.append({"flow_key": f.flow_key, "name": f.name, "description": f.description,
                         "mode": f.mode or "embed", "url": f.url or ""})
    return hits


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
