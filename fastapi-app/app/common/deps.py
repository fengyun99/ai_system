# -*- coding: utf-8 -*-
"""鉴权依赖：请求头 token → 当前登录用户（含角色/权限/数据范围）。"""
from __future__ import annotations

from dataclasses import dataclass, field

import jwt as pyjwt
from fastapi import Depends, Request
from tortoise.exceptions import DoesNotExist

from app.common.response import BizError
from app.common.security import verify_token
from app.models import SysDept, SysMenu, SysRole, SysUser, SysUserRole, SysRoleMenu


@dataclass
class LoginUser:
    user_id: int
    user_name: str
    nick_name: str
    dept_id: int
    dept_no: str
    dept_name: str
    id_card: str = ""                                       # mock 身份（随登录态，查询/办理自动使用）
    phone: str = ""
    roles: list[str] = field(default_factory=list)          # role_key 列表
    permissions: set[str] = field(default_factory=set)      # perms 集合（*all* 表示全量）
    data_scope: int = 2                                     # 1全部 2本部门及以下（取角色最小值）

    @property
    def is_super_admin(self) -> bool:
        return "admin" in self.roles


async def build_login_user(user: SysUser) -> LoginUser:
    dept = await user.dept
    role_ids = [ur.role_id async for ur in SysUserRole.filter(user_id=user.id)]
    roles = await SysRole.filter(id__in=role_ids)
    lu = LoginUser(
        user_id=user.id, user_name=user.user_name, nick_name=user.nick_name,
        dept_id=dept.id, dept_no=dept.dept_no, dept_name=dept.dept_name,
        id_card=getattr(user, "id_card", "") or "", phone=user.phone or "",
        roles=[r.role_key for r in roles],
        data_scope=min([r.data_scope for r in roles], default=2),
    )
    if lu.is_super_admin:
        lu.permissions = {"*all*"}
    elif role_ids:
        menu_ids = [rm.menu_id async for rm in SysRoleMenu.filter(role_id__in=role_ids)]
        perms = await SysMenu.filter(id__in=menu_ids).exclude(perms="").values_list("perms", flat=True)
        lu.permissions = set(perms)
    return lu


def get_token(request: Request) -> str:
    token = request.headers.get("token") or ""
    if token.startswith("Bearer "):
        token = token[7:]
    if not token:
        raise BizError("未登录或令牌缺失", 401)
    return token


async def get_login_user(token: str = Depends(get_token)) -> LoginUser:
    try:
        payload = verify_token(token)
    except pyjwt.ExpiredSignatureError:
        raise BizError("登录已过期，请重新登录", 401)
    except pyjwt.PyJWTError:
        raise BizError("无效令牌", 401)
    try:
        user = await SysUser.get(id=payload["user_id"]).prefetch_related("dept")
    except DoesNotExist:
        raise BizError("用户不存在", 401)
    if user.status != "0":
        raise BizError("账号已停用", 401)
    return await build_login_user(user)


def require_perm(perm: str):
    """按钮级权限校验依赖：permissions 含 *all* 或精确 perms 才放行。"""
    async def _checker(lu: LoginUser = Depends(get_login_user)) -> LoginUser:
        if "*all*" not in lu.permissions and perm not in lu.permissions:
            raise BizError(f"没有操作权限: {perm}", 403)
        return lu
    return _checker


async def resolve_ancestor_chain(dept_no: str) -> list[str]:
    """祖先链（到根、不含自身）：下级可召回上级公开知识，兄弟互不可见。

    依据 sys_dept.ancestors（机构号路径）推导；对齐原 AncestorChainResolver 语义。
    """
    dept = await SysDept.filter(dept_no=dept_no).first()
    if not dept:
        return []
    chain: list[str] = []
    for ancestor_id in dept.ancestors.split(","):
        ancestor_id = ancestor_id.strip()
        if not ancestor_id or ancestor_id == "0":
            continue
        anc = await SysDept.filter(id=int(ancestor_id), status="0").first()
        if anc:
            chain.append(anc.dept_no)
    return chain
