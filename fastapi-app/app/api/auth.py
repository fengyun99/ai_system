# -*- coding: utf-8 -*-
"""认证路由：登录（SM3 口令协议）/ 用户信息 / 路由菜单 / 登出。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from tortoise.exceptions import DoesNotExist

from app.common.deps import LoginUser, build_login_user, get_login_user
from app.common.response import BizError, ok, R
from app.api.schemas import InfoData, LoginData, RouterNode
from app.core.crypto import matches
from app.mock_data import mask
from app.common.security import create_token
from app.models import SysDept, SysMenu, SysRole, SysRoleMenu, SysUser, SysUserRole

router = APIRouter(tags=["auth"])


class LoginBody(BaseModel):
    username: str
    password: str          # 前端已做 sm3(明文) 摘要（对齐原前端协议，明文不出浏览器）


@router.post("/login", response_model=R[LoginData])
async def login(body: LoginBody):
    try:
        user = await SysUser.get(user_name=body.username).prefetch_related("dept")
    except DoesNotExist:
        raise BizError("用户不存在或密码错误", 401)
    if user.status != "0":
        raise BizError("账号已停用", 401)
    if not matches(body.password, user.password):
        raise BizError("用户不存在或密码错误", 401)

    await SysUser.filter(id=user.id).update(last_login_at=__import__("datetime").datetime.now())
    token = create_token(user.id, user.user_name, (await user.dept).dept_no)
    return ok({"token": token})


@router.get("/getInfo", response_model=R[InfoData])
async def get_info(lu: LoginUser = Depends(get_login_user)):
    dept = await SysDept.get(id=lu.dept_id)
    role_ids = [ur.role_id async for ur in SysUserRole.filter(user_id=lu.user_id)]
    roles = await SysRole.filter(id__in=role_ids)
    return ok({
        "user": {
            "user_id": lu.user_id, "user_name": lu.user_name, "nick_name": lu.nick_name,
            "dept_id": lu.dept_id, "dept_no": lu.dept_no, "dept_name": lu.dept_name,
            # 三要素随登录态（掩码回显，不向用户索要/不明文提示）
            "id_card_masked": mask(lu.id_card), "phone_masked": mask(lu.phone, 3, 2),
            "identity_bound": bool(lu.id_card),
        },
        "roles": [r.role_key for r in roles],
        "role_names": [r.role_name for r in roles],
        "permissions": sorted(lu.permissions),
        "data_scope": lu.data_scope,
    })


def _menu_tree(menus: list[SysMenu], parent_id: int = 0) -> list[dict]:
    nodes = []
    for m in menus:
        if m.parent_id != parent_id:
            continue
        node = {
            "menu_id": m.id, "menu_name": m.menu_name, "path": m.path,
            "component": m.component, "icon": m.icon, "sort": m.sort,
            "menu_type": m.menu_type, "perms": m.perms,
        }
        children = _menu_tree(menus, m.id)
        if children:
            node["children"] = children
        nodes.append(node)
    return sorted(nodes, key=lambda n: n["sort"])


@router.get("/getRouters", response_model=R[list[RouterNode]])
async def get_routers(lu: LoginUser = Depends(get_login_user)):
    """管理端动态路由（按角色过滤；超管全量）。"""
    if lu.is_super_admin:
        menus = await SysMenu.all().order_by("sort")
    else:
        role_ids = [ur.role_id async for ur in SysUserRole.filter(user_id=lu.user_id)]
        menu_ids = [rm.menu_id async for rm in SysRoleMenu.filter(role_id__in=role_ids)]
        menus = await SysMenu.filter(id__in=menu_ids).order_by("sort")
    return ok(_menu_tree([m for m in menus if m.menu_type in ("M", "C") and m.visible]))


@router.post("/logout", response_model=R[None])
async def logout(_: LoginUser = Depends(get_login_user)):
    return ok(msg="退出成功")
