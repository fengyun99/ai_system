# -*- coding: utf-8 -*-
"""流程配置管理（管理端）：流程定义 CRUD + 草稿/发布两态 + 结构校验 + 实例监控。

模型语义（见 CONTEXT.md）：
  - 草稿（nodes）：编辑中版本，保存做基础校验，不影响线上；
  - 已发布（published_nodes）：流程引擎唯一读取的版本；发布做全量结构校验；
  - 定义快照（flow_instance.nodes_snapshot）：发起办理时固化，运行中不随定义变更。
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.biz_service import FLOW_ACTIONS
from app.common.deps import LoginUser, require_perm
from app.common.response import BizError, ok, R
from app.api.schemas import (FlowAdminMeta, FlowCreateData, FlowDefDetail,
                            FlowDefRow, FlowPublishData, FlowSaveData,
                            InstanceCancelData, InstanceDetail,
                            InstancePage)
from app.flow_engine import invalidate_flow_def_cache, load_nodes
from app.models import FlowDef, FlowInstance

router = APIRouter(prefix="/flow-admin", tags=["flow-admin"])

NODE_TYPES = ("form", "upload", "confirm", "auto", "end")
FIELD_TYPES = ("input", "number", "select")
VALIDATE_RULES = ("id_card", "bank_card", "amount", "spouse_name", "spouse_id_card")
UPLOAD_EXTS = ("jpg", "jpeg", "png", "pdf")


# ------------------------------------------------------------------ 校验

def _validate_nodes(raw: str, full: bool) -> tuple[list[dict], list[str]]:
    """节点校验：基础（草稿）/全量（发布）。返回 (节点列表, 错误清单，定位到序号)。"""
    errs: list[str] = []
    try:
        nodes = json.loads(raw or "[]")
    except (json.JSONDecodeError, TypeError) as e:
        return [], [f"节点 JSON 解析失败：{e}"]
    if not isinstance(nodes, list):
        return [], ["节点必须是数组"]
    keys: set[str] = set()
    seen_interactive_after_confirm = False
    has_end = has_confirm = False
    for i, n in enumerate(nodes, 1):
        no = f"第{i}节点"
        if not isinstance(n, dict):
            errs.append(f"{no}：必须是对象"); continue
        key, ntype = n.get("key", ""), n.get("type", "")
        if not key:
            errs.append(f"{no}：缺少 key")
        elif key in keys:
            errs.append(f"{no}：key「{key}」重复")
        keys.add(key)
        if ntype not in NODE_TYPES:
            errs.append(f"{no}「{key}」：类型 {ntype} 不合法（{'/'.join(NODE_TYPES)}）")
            continue
        if not str(n.get("title", "")).strip():
            errs.append(f"{no}「{key}」：缺少标题")
        if ntype == "form":
            if seen_interactive_after_confirm:
                errs.append(f"{no}「{key}」：confirm 之后不能再挂交互节点（form/upload）")
            if full:
                fields = n.get("fields") or []
                if not fields:
                    errs.append(f"{no}「{key}」：form 节点缺少字段定义")
                for f in fields:
                    if not f.get("name") or not f.get("label"):
                        errs.append(f"{no}「{key}」：字段缺少 name/label")
                    rule = f.get("validate")
                    if rule and rule not in VALIDATE_RULES:
                        errs.append(f"{no}「{key}」：校验规则 {rule} 未注册（{'/'.join(VALIDATE_RULES)}）")
        elif ntype == "upload":
            if seen_interactive_after_confirm:
                errs.append(f"{no}「{key}」：confirm 之后不能再挂交互节点（form/upload）")
            if full and not (n.get("files") or []):
                errs.append(f"{no}「{key}」：upload 节点缺少材料槽定义")
        elif ntype == "confirm":
            has_confirm = True
            seen_interactive_after_confirm = True
            if full and not str(n.get("summary_template", "")).strip():
                errs.append(f"{no}「{key}」：缺少确认摘要模板")
        elif ntype == "auto":
            action = n.get("action", "")
            if full and action not in FLOW_ACTIONS:
                errs.append(f"{no}「{key}」：动作 {action or '(空)'} 未注册（{'/'.join(FLOW_ACTIONS)}）")
        elif ntype == "end":
            has_end = True
    if full:
        if nodes and nodes[0].get("type") == "auto":
            pass  # 合法：首节点系统核验，发起时服务端自动执行
        if not has_end:
            errs.append("缺少 end 节点")
        if has_confirm and not any(n.get("type") in ("form", "upload") for n in nodes):
            errs.append("只有 confirm 没有信息采集节点（form/upload），确认页无内容可确认")
    return nodes, errs


# ------------------------------------------------------------------ 定义 CRUD

class FlowDefBody(BaseModel):
    flow_key: str
    name: str
    description: str = ""
    dept_no: str
    keywords: str = ""
    mode: str = "embed"
    url: str = ""
    nodes: str = "[]"          # 草稿 JSON 字符串（前端 JSON 编辑器产出）


@router.get("/meta", response_model=R[FlowAdminMeta])
async def flow_admin_meta(_: LoginUser = Depends(require_perm("flow:list"))):
    """配置器枚举：节点类型/已注册动作/校验规则/字段类型（下拉数据源）。"""
    return ok({
        "node_types": list(NODE_TYPES),
        "actions": [{"key": k, "doc": (v.__doc__ or "").strip().splitlines()[0] if v.__doc__ else ""}
                    for k, v in FLOW_ACTIONS.items()],
        "validate_rules": list(VALIDATE_RULES),
        "field_types": list(FIELD_TYPES),
        "upload_exts": list(UPLOAD_EXTS),
    })


@router.get("/list", response_model=R[list[FlowDefRow]])
async def flow_admin_list(_: LoginUser = Depends(require_perm("flow:list"))):
    rows = []
    for f in await FlowDef.all().order_by("id"):
        _, draft_errs = _validate_nodes(f.nodes, full=False)
        _, pub_errs = _validate_nodes(f.published_nodes, full=False) if f.published_nodes else ([], [])
        draft = json.loads(f.nodes or "[]")
        published = json.loads(f.published_nodes or "[]") if f.published_nodes else []
        rows.append({
            "id": f.id, "flow_key": f.flow_key, "name": f.name, "description": f.description,
            "dept_no": f.dept_no, "keywords": f.keywords, "mode": f.mode, "url": f.url,
            "status": f.status,
            "published": bool(f.published_nodes),
            "dirty": (f.nodes or "[]") != (f.published_nodes or ""),
            "draft_nodes": len(draft), "published_nodes": len(published),
            "draft_invalid": bool(draft_errs) or bool(pub_errs),
        })
    return ok(rows)


@router.post("", response_model=R[FlowCreateData])
async def flow_admin_create(body: FlowDefBody, _: LoginUser = Depends(require_perm("flow:add"))):
    if await FlowDef.filter(flow_key=body.flow_key).exists():
        raise BizError(f"流程标识 {body.flow_key} 已存在")
    nodes, errs = _validate_nodes(body.nodes, full=False)
    if errs:
        raise BizError("；".join(errs[:5]), 422)
    f = await FlowDef.create(flow_key=body.flow_key, name=body.name, description=body.description,
                             dept_no=body.dept_no, keywords=body.keywords,
                             mode=body.mode, url=body.url, nodes=body.nodes)
    return ok({"id": f.id, "published": False})


@router.put("/{flow_id}", response_model=R[FlowSaveData])
async def flow_admin_save(flow_id: int, body: FlowDefBody,
                          _: LoginUser = Depends(require_perm("flow:edit"))):
    f = await FlowDef.get_or_none(id=flow_id)
    if not f:
        raise BizError("流程不存在", 404)
    nodes, errs = _validate_nodes(body.nodes, full=False)
    if errs:
        raise BizError("；".join(errs[:5]), 422)
    await FlowDef.filter(id=flow_id).update(
        name=body.name, description=body.description, dept_no=body.dept_no,
        keywords=body.keywords, mode=body.mode, url=body.url, nodes=body.nodes)
    return ok({"id": flow_id, "dirty": (body.nodes or "[]") != (f.published_nodes or "")})


@router.delete("/{flow_id}", response_model=R[None])
async def flow_admin_delete(flow_id: int, _: LoginUser = Depends(require_perm("flow:remove"))):
    running = await FlowInstance.filter(flow_def_id=flow_id, status="running").count()
    if running:
        raise BizError(f"存在 {running} 个办理中的实例，请先处理（完成/强制取消）再删除", 409)
    await FlowDef.filter(id=flow_id).delete()
    invalidate_flow_def_cache(flow_id)
    return ok()


@router.post("/{flow_id}/publish", response_model=R[FlowPublishData])
async def flow_admin_publish(flow_id: int, _: LoginUser = Depends(require_perm("flow:publish"))):
    """发布：全量结构校验 → 草稿拷入 published → 失效引擎缓存。运行中实例按快照走完不受影响。"""
    f = await FlowDef.get_or_none(id=flow_id)
    if not f:
        raise BizError("流程不存在", 404)
    nodes, errs = _validate_nodes(f.nodes, full=True)
    if errs:
        raise BizError("发布校验未通过：" + "；".join(errs[:6]), 422)
    await FlowDef.filter(id=flow_id).update(published_nodes=f.nodes)
    invalidate_flow_def_cache(flow_id)
    return ok({"published_nodes": len(nodes)})


# ------------------------------------------------------------------ 实例监控

async def _instance_query(lu, *, status: str = "", dept_no: str = "", start: str = "", end: str = ""):
    """实例查询构造器：数据范围（readable_dept_nos）+ 状态/机构/时间过滤。列表与导出共用。"""
    from app.api.audit import readable_dept_nos, _day
    q = FlowInstance.all()
    scope = await readable_dept_nos(lu)
    if dept_no:
        scope = [dept_no] if (scope is None or dept_no in scope) else []
    if scope is not None:
        q = q.filter(dept_no__in=scope)
    if status:
        q = q.filter(status=status)
    if _day(start):
        q = q.filter(created_at__gte=_day(start))
    if _day(end, end_of_day=True):
        q = q.filter(created_at__lte=_day(end, end_of_day=True))
    return q


_INSTANCE_STATUS_LABELS = {"running": "办理中", "done": "已完成", "cancelled": "已取消"}


def _receipt_no(steps: list[dict]) -> str:
    """受理单号：auto 节点结果里含"受理单号"的行（取冒号后部分）。"""
    for st in reversed(steps):
        for line in str(st.get("result") or "").splitlines():
            if "受理单号" in line:
                part = line.strip().lstrip("- ").strip()
                for sep in ("：", ":"):
                    if sep in part:
                        part = part.split(sep, 1)[1].strip()
                return part
    return ""


def _vars_summary(raw: str) -> str:
    """办理变量摘要（敏感字段脱敏）。"""
    from app.mock_data import mask
    sens = {"bank_card": (4, 4), "repay_card": (4, 4), "id_card": (3, 4), "phone": (3, 2)}
    try:
        vars_ = json.loads(raw or "{}")
    except (json.JSONDecodeError, TypeError):
        return ""
    parts = []
    for k, v in vars_.items():
        text = "" if v in (None, "") else str(v)
        if not text:
            continue
        if k in sens:
            h, t = sens[k]
            text = mask(text, h, t)
        parts.append(f"{k}={text}")
    return "；".join(parts)[:500]


def _instance_rows(rows: list, defs: dict, users: dict, dept_names: dict) -> list[dict]:
    out = []
    for r in rows:
        f = defs.get(r.flow_def_id)
        try:
            steps = json.loads(r.steps or "[]")
        except Exception:  # noqa: BLE001
            steps = []
        cur = steps[-1].get("node_key", "") if steps else ""
        out.append({
            "id": r.id, "flow_key": f.flow_key if f else str(r.flow_def_id),
            "flow_name": f.name if f else "", "user": users.get(r.user_id, str(r.user_id)),
            "dept_no": r.dept_no, "dept_name": dept_names.get(r.dept_no, ""),
            "status": r.status, "status_label": _INSTANCE_STATUS_LABELS.get(r.status, r.status),
            "current": cur, "steps": len(steps),
            "receipt_no": _receipt_no(steps),
            "created_at": r.created_at.strftime("%Y-%m-%d %H:%M:%S") if r.created_at else "",
            "finished_at": r.updated_at.strftime("%Y-%m-%d %H:%M:%S")
            if (r.status in ("done", "cancelled") and r.updated_at) else "",
        })
    return out


async def _instance_refs(rows: list) -> tuple[dict, dict, dict]:
    from app.models import SysDept, SysUser
    defs = {f.id: f for f in await FlowDef.filter(id__in=[r.flow_def_id for r in rows])}
    users = {u.id: u.nick_name for u in await SysUser.filter(id__in=[r.user_id for r in rows])}
    dept_names = {d.dept_no: d.dept_name
                  for d in await SysDept.filter(dept_no__in={r.dept_no for r in rows})}
    return defs, users, dept_names


@router.get("/instances", response_model=R[InstancePage])
async def flow_instances(
    lu: LoginUser = Depends(require_perm("flow:instance:list")),
    status: str = "", dept_no: str = "", start: str = "", end: str = "",
    page: int = 1, size: int = 20,
):
    qs = await _instance_query(lu, status=status, dept_no=dept_no, start=start, end=end)
    total = await qs.count()
    rows = await qs.order_by("-id").offset((page - 1) * size).limit(size)
    defs, users, dept_names = await _instance_refs(rows)
    return ok({"total": total, "rows": _instance_rows(rows, defs, users, dept_names)})


@router.get("/export/instances")
async def export_instances(
    lu: LoginUser = Depends(require_perm("flow:instance:list")),
    status: str = "", dept_no: str = "", start: str = "", end: str = "",
):
    """流程办理数据导出（xlsx）：与实例列表过滤一致；含受理单号与脱敏变量摘要。"""
    import datetime

    from app.common.xlsx_export import EXPORT_ROW_LIMIT, build_xlsx, xlsx_response
    qs = await _instance_query(lu, status=status, dept_no=dept_no, start=start, end=end)
    rows = await qs.order_by("-id").limit(EXPORT_ROW_LIMIT + 1)
    truncated = len(rows) > EXPORT_ROW_LIMIT
    rows = rows[:EXPORT_ROW_LIMIT]
    defs, users, dept_names = await _instance_refs(rows)
    data = _instance_rows(rows, defs, users, dept_names)
    headers = ["实例ID", "流程标识", "流程名称", "办理人", "机构号", "机构名称", "状态",
               "当前/最后节点", "步数", "发起时间", "完成时间", "受理单号", "办理变量摘要(脱敏)"]
    body = [[d["id"], d["flow_key"], d["flow_name"], d["user"], d["dept_no"], d["dept_name"],
             d["status_label"], d["current"], d["steps"], d["created_at"], d["finished_at"],
             d["receipt_no"], _vars_summary(getattr(r, "vars", "") or "")]
            for d, r in zip(data, rows)]
    name = f"流程办理数据_{datetime.date.today().strftime('%Y%m%d')}.xlsx"
    return xlsx_response(name, build_xlsx("流程办理", headers, body), truncated)


@router.get("/instances/{instance_id}", response_model=R[InstanceDetail])
async def flow_instance_detail(instance_id: int,
                               _: LoginUser = Depends(require_perm("flow:instance:list"))):
    r = await FlowInstance.get_or_none(id=instance_id)
    if not r:
        raise BizError("实例不存在", 404)
    f = await r.flow_def
    from app.api.flow import build_flow_display
    display = build_flow_display(f, r)
    try:
        steps = json.loads(r.steps or "[]")
    except Exception:
        steps = []
    return ok({"id": r.id, "status": r.status, "steps": steps,
               "display": display, "vars_public": {
                   k: v for k, v in json.loads(r.vars or "{}").items()
                   if k in ("marriage", "rent_type", "frequency")}})


@router.post("/instances/{instance_id}/cancel", response_model=R[InstanceCancelData])
async def flow_instance_force_cancel(instance_id: int,
                                     _: LoginUser = Depends(require_perm("flow:instance:cancel"))):
    """管理员强制取消：登记系统侧取消留痕，解除该会话问答门控。"""
    from app.flow_engine import cancel_flow
    class _SysUser:
        user_id, user_name = 0, "admin-force"
    r = await FlowInstance.get_or_none(id=instance_id)
    if not r:
        raise BizError("实例不存在", 404)
    if r.status != "running":
        raise BizError("该实例已结束", 409)
    result = await cancel_flow(instance_id, _SysUser(),
                               reason="管理员强制取消（流程配置管理）", force=True)
    return ok({"status": result["instance"].status})


@router.get("/{flow_id}", response_model=R[FlowDefDetail])
async def flow_admin_detail(flow_id: int, _: LoginUser = Depends(require_perm("flow:list"))):
    f = await FlowDef.get_or_none(id=flow_id)
    if not f:
        raise BizError("流程不存在", 404)
    return ok({"id": f.id, "flow_key": f.flow_key, "name": f.name, "description": f.description,
               "dept_no": f.dept_no, "keywords": f.keywords, "mode": f.mode, "url": f.url,
               "status": f.status, "nodes": f.nodes,
               "published_nodes": f.published_nodes or ""})
