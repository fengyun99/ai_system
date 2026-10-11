# -*- coding: utf-8 -*-
"""MCP 工具管理路由：登记清单（按部门）/ 启停 / 共享。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.common.deps import LoginUser, get_login_user, require_perm
from app.common.response import BizError, ok, R
from app.api.schemas import IdData, ToolRow
from app.models import McpTool

router = APIRouter(prefix="/tools", tags=["tools"])


@router.get("/list", response_model=R[list[ToolRow]])
async def list_tools(lu: LoginUser = Depends(get_login_user)):
    rows = await McpTool.all().order_by("id")
    return ok([{
        "id": r.id, "dept_no": r.dept_no, "name": r.name, "description": r.description,
        "parameters": r.parameters, "shared": r.shared, "status": r.status,
    } for r in rows])


class ToolBody(BaseModel):
    dept_no: str
    name: str
    description: str = ""
    parameters: str = "{}"
    shared: int = 0
    status: int = 1


@router.post("", response_model=R[IdData])
async def create_tool(body: ToolBody, lu: LoginUser = Depends(require_perm("tool:add"))):
    if await McpTool.filter(name=body.name).exists():
        raise BizError("工具名已存在")
    t = await McpTool.create(**body.model_dump())
    return ok({"id": t.id})


@router.put("/{tool_id}", response_model=R[None])
async def update_tool(tool_id: int, body: ToolBody,
                      lu: LoginUser = Depends(require_perm("tool:edit"))):
    await McpTool.filter(id=tool_id).update(**body.model_dump())
    return ok()


@router.delete("/{tool_id}", response_model=R[None])
async def delete_tool(tool_id: int, lu: LoginUser = Depends(require_perm("tool:remove"))):
    await McpTool.filter(id=tool_id).delete()
    return ok()
