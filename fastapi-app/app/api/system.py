# -*- coding: utf-8 -*-
"""系统管理路由：用户/角色/部门/菜单 CRUD（RBAC 权限体系，真实数据管理）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.common.deps import LoginUser, get_login_user, require_perm
from app.common.response import BizError, ok, R
from app.api.schemas import (DeptRow, IdData, MenuRow, RoleRow,
                            UserRow)
from app.core.crypto import encode_password
from app.models import (SysDept, SysMenu, SysRole, SysRoleMenu, SysUser,
                        SysUserRole)
from app.api.audit import readable_dept_nos

router = APIRouter(prefix="/system", tags=["system"])


# ---------------- 部门 ----------------

@router.get("/depts", response_model=R[list[DeptRow]])
async def list_depts(lu: LoginUser = Depends(get_login_user)):
    scope = await readable_dept_nos(lu)
    rows = await SysDept.all().order_by("id")
    out = [{
        "id": d.id, "dept_no": d.dept_no, "dept_name": d.dept_name,
        "parent_id": d.parent_id, "ancestors": d.ancestors, "status": d.status,
    } for d in rows]
    if scope is not None:
        out = [d for d in out if d["dept_no"] in scope]
    return ok(out)


class DeptBody(BaseModel):
    dept_no: str
    dept_name: str
    parent_id: int = 0
    status: str = "0"


@router.post("/depts", response_model=R[IdData])
async def create_dept(body: DeptBody, lu: LoginUser = Depends(require_perm("dept:add"))):
    if await SysDept.filter(dept_no=body.dept_no).exists():
        raise BizError("机构编号已存在")
    parent = await SysDept.filter(id=body.parent_id).first() if body.parent_id else None
    ancestors = f"{parent.ancestors},{parent.id}" if parent else "0"
    d = await SysDept.create(dept_no=body.dept_no, dept_name=body.dept_name,
                             parent_id=body.parent_id, ancestors=ancestors)
    return ok({"id": d.id})


@router.put("/depts/{dept_id}", response_model=R[None])
async def update_dept(dept_id: int, body: DeptBody,
                      lu: LoginUser = Depends(require_perm("dept:edit"))):
    d = await SysDept.get(id=dept_id)
    d.dept_no, d.dept_name, d.status = body.dept_no, body.dept_name, body.status
    await d.save(update_fields=["dept_no", "dept_name", "status"])
    return ok()


@router.delete("/depts/{dept_id}", response_model=R[None])
async def delete_dept(dept_id: int, lu: LoginUser = Depends(require_perm("dept:remove"))):
    if await SysDept.filter(parent_id=dept_id).exists():
        raise BizError("存在下级机构，不能删除")
    if await SysUser.filter(dept_id=dept_id).exists():
        raise BizError("机构下存在用户，不能删除")
    await SysDept.filter(id=dept_id).delete()
    return ok()


# ---------------- 用户 ----------------

@router.get("/users", response_model=R[list[UserRow]])
async def list_users(lu: LoginUser = Depends(require_perm("user:list"))):
    scope = await readable_dept_nos(lu)
    q = SysUser.all().prefetch_related("dept")
    users = await q
    out = []
    for u in users:
        d = await u.dept
        if scope is not None and d.dept_no not in scope:
            continue
        role_ids = [ur.role_id async for ur in SysUserRole.filter(user_id=u.id)]
        roles = await SysRole.filter(id__in=role_ids)
        out.append({
            **(await u.to_dict(with_dept=False)), "dept_no": d.dept_no, "dept_name": d.dept_name,
            "roles": [{"id": r.id, "role_name": r.role_name} for r in roles],
        })
    return ok(out)


class UserBody(BaseModel):
    user_name: str
    nick_name: str = ""
    password: str = ""              # 明文（服务端按 Java 协议入库为 $1a+sm3 双重摘要）
    dept_id: int
    phone: str = ""
    status: str = "0"
    role_ids: list[int] = []


@router.post("/users", response_model=R[IdData])
async def create_user(body: UserBody, lu: LoginUser = Depends(require_perm("user:add"))):
    if await SysUser.filter(user_name=body.user_name).exists():
        raise BizError("账号已存在")
    if not body.password:
        raise BizError("初始密码不能为空")
    u = await SysUser.create(
        user_name=body.user_name, nick_name=body.nick_name or body.user_name,
        password=encode_password(body.password), dept_id=body.dept_id,
        phone=body.phone, status=body.status,
    )
    for rid in body.role_ids:
        await SysUserRole.create(user_id=u.id, role_id=rid)
    return ok({"id": u.id})


@router.put("/users/{user_id}", response_model=R[None])
async def update_user(user_id: int, body: UserBody,
                      lu: LoginUser = Depends(require_perm("user:edit"))):
    u = await SysUser.get(id=user_id)
    u.nick_name, u.dept_id, u.phone, u.status = (
        body.nick_name or u.nick_name, body.dept_id, body.phone, body.status)
    if body.password:
        u.password = encode_password(body.password)
    await u.save()
    await SysUserRole.filter(user_id=user_id).delete()
    for rid in body.role_ids:
        await SysUserRole.create(user_id=user_id, role_id=rid)
    return ok()


@router.delete("/users/{user_id}", response_model=R[None])
async def delete_user(user_id: int, lu: LoginUser = Depends(require_perm("user:remove"))):
    if user_id == lu.user_id:
        raise BizError("不能删除当前登录账号")
    await SysUserRole.filter(user_id=user_id).delete()
    await SysUser.filter(id=user_id).delete()
    return ok()


# ---------------- 角色 ----------------

@router.get("/roles", response_model=R[list[RoleRow]])
async def list_roles(lu: LoginUser = Depends(require_perm("role:list"))):
    rows = await SysRole.all().order_by("id")
    out = []
    for r in rows:
        menu_ids = [rm.menu_id async for rm in SysRoleMenu.filter(role_id=r.id)]
        out.append({"id": r.id, "role_name": r.role_name, "role_key": r.role_key,
                    "data_scope": r.data_scope, "status": r.status, "remark": r.remark,
                    "menu_ids": menu_ids})
    return ok(out)


class RoleBody(BaseModel):
    role_name: str
    role_key: str
    data_scope: int = 2
    status: str = "0"
    remark: str = ""
    menu_ids: list[int] = []


@router.post("/roles", response_model=R[IdData])
async def create_role(body: RoleBody, lu: LoginUser = Depends(require_perm("role:add"))):
    if await SysRole.filter(role_key=body.role_key).exists():
        raise BizError("权限字符已存在")
    r = await SysRole.create(role_name=body.role_name, role_key=body.role_key,
                             data_scope=body.data_scope, status=body.status, remark=body.remark)
    for mid in body.menu_ids:
        await SysRoleMenu.create(role_id=r.id, menu_id=mid)
    return ok({"id": r.id})


@router.put("/roles/{role_id}", response_model=R[None])
async def update_role(role_id: int, body: RoleBody,
                      lu: LoginUser = Depends(require_perm("role:edit"))):
    r = await SysRole.get(id=role_id)
    r.role_name, r.role_key, r.data_scope = body.role_name, body.role_key, body.data_scope
    r.status, r.remark = body.status, body.remark
    await r.save()
    await SysRoleMenu.filter(role_id=role_id).delete()
    for mid in body.menu_ids:
        await SysRoleMenu.create(role_id=role_id, menu_id=mid)
    return ok()


@router.delete("/roles/{role_id}", response_model=R[None])
async def delete_role(role_id: int, lu: LoginUser = Depends(require_perm("role:remove"))):
    if await SysUserRole.filter(role_id=role_id).exists():
        raise BizError("角色已分配用户，不能删除")
    await SysRoleMenu.filter(role_id=role_id).delete()
    await SysRole.filter(id=role_id).delete()
    return ok()


# ---------------- 菜单 ----------------

@router.get("/menus", response_model=R[list[MenuRow]])
async def list_menus(lu: LoginUser = Depends(require_perm("menu:list"))):
    rows = await SysMenu.all().order_by("sort")
    return ok([{
        "id": m.id, "menu_name": m.menu_name, "parent_id": m.parent_id, "path": m.path,
        "component": m.component, "perms": m.perms, "menu_type": m.menu_type,
        "icon": m.icon, "sort": m.sort, "visible": m.visible,
    } for m in rows])


class MenuBody(BaseModel):
    menu_name: str
    parent_id: int = 0
    path: str = ""
    component: str = ""
    perms: str = ""
    menu_type: str = "C"
    icon: str = ""
    sort: int = 0
    visible: int = 1


@router.post("/menus", response_model=R[IdData])
async def create_menu(body: MenuBody, lu: LoginUser = Depends(require_perm("menu:add"))):
    m = await SysMenu.create(**body.model_dump())
    return ok({"id": m.id})


@router.put("/menus/{menu_id}", response_model=R[None])
async def update_menu(menu_id: int, body: MenuBody,
                      lu: LoginUser = Depends(require_perm("menu:edit"))):
    await SysMenu.filter(id=menu_id).update(**body.model_dump())
    return ok()


@router.delete("/menus/{menu_id}", response_model=R[None])
async def delete_menu(menu_id: int, lu: LoginUser = Depends(require_perm("menu:remove"))):
    if await SysMenu.filter(parent_id=menu_id).exists():
        raise BizError("存在子菜单，不能删除")
    await SysRoleMenu.filter(menu_id=menu_id).delete()
    await SysMenu.filter(id=menu_id).delete()
    return ok()
