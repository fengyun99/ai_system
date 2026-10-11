# -*- coding: utf-8 -*-
"""初始化数据库：建库 → 建表（Tortoise）→ 种子数据（RBAC/知识/工具）→ 知识入库 ES。

用法：.venv/Scripts/python.exe scripts/init_db.py [--reset]
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import aiomysql

from app.core.config_loader import AppConfig
from app.core.crypto import encode_password
from app.mock_data import MOCK_ACCOUNTS, USER_BINDINGS
from app.models import (Conversation, FlowDef, FlowInstance, Knowledge, McpTool,
                        OpenClient, SysDept, SysMenu, SysRole, SysRoleMenu, SysUser,
                        SysUserRole)
from app.rag import ingest
from tortoise import Tortoise

RESET = "--reset" in sys.argv


async def ensure_database(cfg: dict) -> None:
    conn = await aiomysql.connect(host=cfg["host"], port=int(cfg["port"]),
                                   user=cfg["user"], password=cfg["password"])
    cur = await conn.cursor()
    await cur.execute(
        f"CREATE DATABASE IF NOT EXISTS `{cfg['database']}` "
        "DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
    if RESET:
        for table in ("turn_stage", "turn", "ingest_log", "flow_instance", "flow_def",
                      "conversation", "knowledge", "mcp_tool",
                      "sys_user_role", "sys_role_menu", "sys_menu", "sys_role",
                      "sys_user", "sys_dept"):
            await cur.execute(f"DROP TABLE IF EXISTS `{cfg['database']}`.`{table}`")
    await conn.commit()
    conn.close()


# ---------------- 种子 ----------------

async def seed_depts() -> dict[str, SysDept]:
    rows = [
        # (dept_no, name, parent_no)
        ("00000", "住房和城乡建设部", None),
        ("35000", "福建省住房和城乡建设厅", "00000"),
        ("35001", "福建省直住房公积金中心", "35000"),
        ("35002", "福州市住房公积金中心", "35000"),
        ("35003", "泉州市住房公积金中心", "35000"),
    ]
    by_no: dict[str, SysDept] = {}
    for dept_no, name, parent_no in rows:
        parent = by_no.get(parent_no)
        d = await SysDept.create(
            dept_no=dept_no, dept_name=name,
            parent_id=parent.id if parent else 0,
            ancestors=f"{parent.ancestors},{parent.id}" if parent else "0",
        )
        by_no[dept_no] = d
    return by_no


async def seed_menus() -> dict[str, int]:
    """管理端菜单树：目录(M)/页面(C)/按钮(F)。"""
    spec = [
        # (name, parent_key, path, component, perms, type, icon, sort)
        ("智能问答", "", "/portal", "portal/Chat", "", "C", "chat", 0),
        ("系统管理", "", "/system", "Layout", "", "M", "settings", 90),
        ("用户管理", "系统管理", "users", "system/Users", "user:list", "C", "user", 1),
        ("用户新增", "用户管理", "", "", "user:add", "F", "", 1),
        ("用户编辑", "用户管理", "", "", "user:edit", "F", "", 2),
        ("用户删除", "用户管理", "", "", "user:remove", "F", "", 3),
        ("角色管理", "系统管理", "roles", "system/Roles", "role:list", "C", "role", 2),
        ("角色新增", "角色管理", "", "", "role:add", "F", "", 1),
        ("角色编辑", "角色管理", "", "", "role:edit", "F", "", 2),
        ("角色删除", "角色管理", "", "", "role:remove", "F", "", 3),
        ("部门管理", "系统管理", "depts", "system/Depts", "dept:list", "C", "dept", 3),
        ("部门新增", "部门管理", "", "", "dept:add", "F", "", 1),
        ("部门编辑", "部门管理", "", "", "dept:edit", "F", "", 2),
        ("部门删除", "部门管理", "", "", "dept:remove", "F", "", 3),
        ("菜单管理", "系统管理", "menus", "system/Menus", "menu:list", "C", "menu", 4),
        ("菜单新增", "菜单管理", "", "", "menu:add", "F", "", 1),
        ("菜单编辑", "菜单管理", "", "", "menu:edit", "F", "", 2),
        ("菜单删除", "菜单管理", "", "", "menu:remove", "F", "", 3),
        ("运营审计", "", "/audit", "Layout", "", "M", "audit", 10),
        ("轮次审计", "运营审计", "turns", "audit/Turns", "audit:list", "C", "list", 1),
        ("仪表盘", "运营审计", "dashboard", "audit/Dashboard", "audit:list", "C", "chart", 2),
        ("知识库管理", "", "/kb", "Layout", "", "M", "book", 20),
        ("知识条目", "知识库管理", "knowledge", "kb/Knowledge", "kb:list", "C", "doc", 1),
        ("知识新增", "知识条目", "", "", "kb:add", "F", "", 1),
        ("知识编辑", "知识条目", "", "", "kb:edit", "F", "", 2),
        ("知识删除", "知识条目", "", "", "kb:remove", "F", "", 3),
        ("业务配置", "", "/biz", "Layout", "", "M", "workflow", 25),
        ("流程定义", "业务配置", "flows", "biz/FlowDefs", "flow:list", "C", "flow", 1),
        ("流程新增", "流程定义", "", "", "flow:add", "F", "", 1),
        ("流程编辑", "流程定义", "", "", "flow:edit", "F", "", 2),
        ("流程删除", "流程定义", "", "", "flow:remove", "F", "", 3),
        ("流程发布", "流程定义", "", "", "flow:publish", "F", "", 4),
        ("流程实例", "业务配置", "flow-instances", "biz/FlowInstances", "flow:instance:list", "C", "list", 2),
        ("实例强制取消", "流程实例", "", "", "flow:instance:cancel", "F", "", 1),
        ("工具管理", "", "/tools", "Layout", "", "M", "tool", 30),
        ("MCP 工具", "工具管理", "registry", "tools/Registry", "tool:list", "C", "wrench", 1),
        ("工具新增", "MCP 工具", "", "", "tool:add", "F", "", 1),
        ("工具编辑", "MCP 工具", "", "", "tool:edit", "F", "", 2),
        ("工具删除", "MCP 工具", "", "", "tool:remove", "F", "", 3),
    ]
    by_name: dict[str, SysMenu] = {}
    for name, parent, path, component, perms, mtype, icon, sort in spec:
        p = by_name.get(parent)
        m = await SysMenu.create(
            menu_name=name, parent_id=p.id if p else 0, path=path, component=component,
            perms=perms, menu_type=mtype, icon=icon, sort=sort,
        )
        by_name[name] = m
    return {name: m.id for name, m in by_name.items()}


async def seed_flows() -> None:
    """业务流程种子（幂等）：form → confirm → auto → end 线性步进。"""
    import json as _json
    existing = {f.flow_key for f in await FlowDef.all()}
    flows_spec = [
        {
            "flow_key": "rent_withdraw", "name": "租房提取办理",
            "mode": "embed", "url": "",
            "description": "无房职工租房提取公积金（线上办理·对齐真实流程：缴存资格核验→婚姻声明→无房联网核验→租赁信息→材料上传→备案核验→收款账户→受理）",
            "keywords": "租房提取 提取办理 我要提取 办理提取 申请提取",
            "nodes": [
                {
                    "key": "eligibility",
                    "type": "auto",
                    "title": "缴存资格核验（缴存登记系统）",
                    "action": "verify_deposit_eligibility"
                },
                {
                    "key": "marriage",
                    "type": "form",
                    "title": "婚姻状况声明",
                    "fields": [
                        {
                            "name": "marriage",
                            "label": "婚姻状况",
                            "type": "select",
                            "required": True,
                            "options": [
                                "未婚",
                                "已婚"
                            ]
                        },
                        {
                            "name": "spouse_name",
                            "label": "配偶姓名（已婚必填）",
                            "type": "input",
                            "placeholder": "已婚时提取额度按家庭计算",
                            "validate": "spouse_name"
                        },
                        {
                            "name": "spouse_id_card",
                            "label": "配偶身份证号（已婚必填）",
                            "type": "input",
                            "placeholder": "已婚时联网核验配偶名下房产",
                            "validate": "spouse_id_card"
                        }
                    ]
                },
                {
                    "key": "no_house",
                    "type": "auto",
                    "title": "无房核验（不动产登记中心联网）",
                    "action": "verify_no_house"
                },
                {
                    "key": "rent_info",
                    "type": "form",
                    "title": "租赁信息填报",
                    "fields": [
                        {
                            "name": "rent_type",
                            "label": "租赁类型",
                            "type": "select",
                            "required": True,
                            "options": [
                                "商品房",
                                "公租房"
                            ]
                        },
                        {
                            "name": "rent_amount",
                            "label": "月租金（元）",
                            "type": "number",
                            "required": True,
                            "placeholder": "如 2500"
                        },
                        {
                            "name": "frequency",
                            "label": "提取频次",
                            "type": "select",
                            "required": True,
                            "options": [
                                "按月提取",
                                "按年提取"
                            ]
                        },
                        {
                            "name": "amount",
                            "label": "本次提取金额（元）",
                            "type": "number",
                            "required": True,
                            "placeholder": "不超过年度提取限额",
                            "validate": "amount"
                        }
                    ]
                },
                {
                    "key": "materials",
                    "type": "upload",
                    "title": "上传申请材料",
                    "files": [
                        {
                            "name": "lease_contract",
                            "label": "租赁合同（备案凭证）",
                            "required": True,
                            "accept": "image/*,application/pdf"
                        },
                        {
                            "name": "rent_voucher",
                            "label": "租金缴纳凭证（公租房必传）",
                            "required": False,
                            "accept": "image/*,application/pdf"
                        }
                    ]
                },
                {
                    "key": "rent_verify",
                    "type": "auto",
                    "title": "租赁备案核验（住建租赁备案系统）",
                    "action": "verify_rent_record"
                },
                {
                    "key": "account",
                    "type": "form",
                    "title": "填写收款账户",
                    "fields": [
                        {
                            "name": "bank_card",
                            "label": "本人一类银行卡号",
                            "type": "input",
                            "required": True,
                            "placeholder": "演示卡号 6222021234567890123",
                            "validate": "bank_card"
                        }
                    ]
                },
                {
                    "key": "confirm",
                    "type": "confirm",
                    "title": "信息确认",
                    "summary_template": "缴存人：{name}（身份已核验）\n婚姻状况：{marriage}\n租赁类型：{rent_type} · 月租金 {rent_amount} 元\n提取方式：{frequency} · 本次提取 {amount} 元\n申请材料：已上传（详见办理信息）\n收款卡号：{bank_card}"
                },
                {
                    "key": "verify",
                    "type": "auto",
                    "title": "账户状态核验（业务系统）",
                    "action": "query_account_snapshot"
                },
                {
                    "key": "amount_check",
                    "type": "auto",
                    "title": "提取额度校验（业务系统）",
                    "action": "verify_extract_amount"
                },
                {
                    "key": "accept",
                    "type": "auto",
                    "title": "业务系统受理",
                    "action": "submit_application",
                    "action_args": {
                        "scene": "租房提取"
                    }
                },
                {
                    "key": "end",
                    "type": "end",
                    "title": "办理完成",
                    "text": "✅ 租房提取申请已提交成功！款项将在 3 个工作日内到账，请留意短信通知。办理流程已结束，您可以继续咨询其它问题。"
                }
            ],
        },
        {
            "flow_key": "chonghuandai_sign", "name": "冲还贷签约",
            "mode": "embed", "url": "",
            "description": "委托按月冲还贷签约（省直/福州）",
            "keywords": "冲还贷 冲抵 签约冲还 对冲",
            "nodes": [
                {"key": "account", "type": "form", "title": "填写签约信息", "fields": [
                    {"name": "repay_card", "label": "还款银行卡号", "type": "input", "required": True,
                     "placeholder": "演示卡号 6222021234567890123", "validate": "bank_card"},
                ]},
                {"key": "confirm", "type": "confirm", "title": "签约确认",
                 "summary_template": "缴存人：{name}（身份已核验）\n还款卡号：{repay_card}\n签约类型：按月冲还贷（自动扣划）"},
                {"key": "check", "type": "auto", "title": "账户信息核验（业务系统）",
                 "action": "query_account_snapshot"},
                {"key": "accept", "type": "auto", "title": "业务系统受理", "action": "submit_application",
                 "action_args": {"scene": "冲还贷签约"}},
                {"key": "end", "type": "end", "title": "签约完成",
                 "text": "✅ 按月冲还贷签约成功！每月还款日将自动从公积金账户扣划，账户余额不足时从还款银行卡补扣。流程已结束，可继续提问。"},
            ],
        },
        {
            "flow_key": "house_withdraw", "name": "购房提取办理（需提交材料）",
            "description": "购房提取涉及合同/发票等材料核验，需前往业务系统提交（复杂业务·页面跳转）",
            "keywords": "购房提取 买房提取 购建房提取",
            "mode": "redirect", "url": "https://zfgjj.fuzhou.gov.cn/wsbs/",
            "nodes": [],
        },
    ]
    for spec in flows_spec:
        nodes_json = _json.dumps(spec["nodes"], ensure_ascii=False)
        if spec["flow_key"] in existing:
            # 定义同步：已存在的流程按最新种子刷新（节点/关键词/模式），保证演示与代码一致
            await FlowDef.filter(flow_key=spec["flow_key"]).update(
                name=spec["name"], description=spec["description"], keywords=spec["keywords"],
                mode=spec.get("mode", "embed"), url=spec.get("url", ""), nodes=nodes_json,
            )
            continue
        await FlowDef.create(
            flow_key=spec["flow_key"], name=spec["name"], description=spec["description"],
            dept_no="35000", keywords=spec["keywords"],
            mode=spec.get("mode", "embed"), url=spec.get("url", ""),
            nodes=_json.dumps(spec["nodes"], ensure_ascii=False),
        )



async def seed_all() -> None:
    depts = await seed_depts()
    menu_ids = await seed_menus()

    admin_role = await SysRole.create(role_name="超级管理员", role_key="admin",
                                      data_scope=1, remark="全部数据权限")
    manager_role = await SysRole.create(role_name="运营管理员", role_key="manager",
                                        data_scope=2, remark="本部门及以下")
    user_role = await SysRole.create(role_name="普通用户", role_key="user",
                                     data_scope=2, remark="仅问答门户")

    # 角色-菜单：manager 给管理页（除菜单管理），user 只给问答门户
    manager_menus = [mid for name, mid in menu_ids.items()
                     if not name.startswith("菜单") and name != "系统管理"]
    for mid in manager_menus:
        await SysRoleMenu.create(role_id=manager_role.id, menu_id=mid)
    await SysRoleMenu.create(role_id=user_role.id, menu_id=menu_ids["智能问答"])

    # 用户（口令=Java 同款 $1a+sm3 双重摘要）
    users = [
        ("admin", "系统管理员", "admin123", "35001", [admin_role]),
        ("fzzx", "福州小陈", "fz123456", "35002", [manager_role, user_role]),
        ("qzzx", "泉州小林", "qz123456", "35003", [user_role]),
    ]
    for user_name, nick, pwd, dept_no, roles in users:
        # 三要素随登录态绑定（mock）：身份证号 + 手机号（姓名取账户档案姓名）
        id_card = USER_BINDINGS.get(user_name, "")
        acct = MOCK_ACCOUNTS.get(id_card, {})
        u = await SysUser.create(
            user_name=user_name, nick_name=acct.get("name") or nick,
            password=encode_password(pwd), dept_id=depts[dept_no].id,
            id_card=id_card, phone=acct.get("phone", ""))
        for r in roles:
            await SysUserRole.create(user_id=u.id, role_id=r.id)

    # MCP 工具登记（省级共享）
    tools_spec = [
        ("35000", "query_account_balance", "查询公积金账户余额与状态",
         '{"type":"object","properties":{"id_card":{"type":"string","description":"身份证号"},"'
         'name":{"type":"string","description":"姓名"}},"required":["id_card"]}', 1),
        ("35000", "query_loan_info", "查询本人公积金贷款信息",
         '{"type":"object","properties":{"id_card":{"type":"string","description":"身份证号"}},'
         '"required":["id_card"]}', 1),
        ("35002", "query_deposit_detail", "查询近N个月缴存明细",
         '{"type":"object","properties":{"id_card":{"type":"string","description":"身份证号"},'
         '"months":{"type":"integer","description":"月数，默认6"}},"required":["id_card"]}', 0),
    ]
    for dept_no, name, desc, params, shared in tools_spec:
        await McpTool.create(dept_no=dept_no, name=name, description=desc,
                             parameters=params, shared=shared)

    await seed_flows()


async def ensure_open_columns() -> None:
    """溯源列迁移（幂等）：Tortoise generate_schemas 只建表不加列，需显式 ALTER。"""
    from tortoise import Tortoise
    DDL = [
        "ALTER TABLE conversation ADD COLUMN open_client_id INT NOT NULL DEFAULT 0",
        "ALTER TABLE turn ADD COLUMN source_type VARCHAR(8) NOT NULL DEFAULT 'portal'",
        "ALTER TABLE turn ADD COLUMN open_client_id INT NOT NULL DEFAULT 0",
        "ALTER TABLE turn ADD COLUMN source_system VARCHAR(64) NOT NULL DEFAULT ''",
        "ALTER TABLE turn ADD COLUMN trace_id VARCHAR(64) NOT NULL DEFAULT ''",
        "CREATE INDEX idx_turn_open_client ON turn (open_client_id, id)",
        "CREATE INDEX idx_turn_trace ON turn (trace_id)",
        "ALTER TABLE flow_def ADD COLUMN published_nodes LONGTEXT NULL",
        "ALTER TABLE flow_instance ADD COLUMN nodes_snapshot LONGTEXT NULL",
        "ALTER TABLE turn ADD COLUMN rag_flag VARCHAR(128) NOT NULL DEFAULT ''",
        "ALTER TABLE turn ADD COLUMN rag_note VARCHAR(512) NOT NULL DEFAULT ''",
        "ALTER TABLE turn ADD COLUMN rag_flag_by INT NOT NULL DEFAULT 0",
        "ALTER TABLE turn ADD COLUMN rag_flag_at DATETIME NULL",
        "CREATE INDEX idx_turn_recall_turn ON turn_recall (turn_id, fused_rank)",
        "CREATE INDEX idx_turn_feedback_turn ON turn_feedback (turn_id)",
        "CREATE INDEX idx_turn_rag_flag ON turn (rag_flag(8))",
        "ALTER TABLE turn_stage ADD COLUMN tokens_estimated INT NOT NULL DEFAULT 0",
        "ALTER TABLE turn ADD COLUMN cost DECIMAL(12,6) NOT NULL DEFAULT 0",
        "ALTER TABLE turn_stage ADD COLUMN cost DECIMAL(12,6) NOT NULL DEFAULT 0",
        "ALTER TABLE turn_stage ADD COLUMN started_at DATETIME(6) NULL",
        "ALTER TABLE turn_stage ADD COLUMN finished_at DATETIME(6) NULL",
        "ALTER TABLE turn_stage ADD COLUMN error_detail TEXT NULL",
        "ALTER TABLE turn ADD COLUMN error_detail TEXT NULL",
        "UPDATE flow_def SET published_nodes = nodes WHERE (published_nodes IS NULL OR published_nodes = '') AND nodes <> '[]'",
    ]
    conn = Tortoise.get_connection("default")
    for ddl in DDL:
        try:
            await conn.execute_query(ddl)
        except Exception:  # noqa: BLE001 列/索引已存在时跳过
            pass


async def seed_open_clients(depts: dict[str, SysDept] | None = None) -> None:
    """开放接口种子（幂等）：接入方虚拟用户 + 演示接入方。"""
    dept_id = (depts or {}).get("35000").id if depts else \
        (await SysDept.filter(dept_no="35000").first()).id
    if not await SysUser.filter(user_name="openapi_svc").exists():
        from app.core.crypto import encode_password as _enc
        await SysUser.create(user_name="openapi_svc", nick_name="开放接口",
                             password=_enc("svc-no-login-2026"), dept_id=dept_id)
        print("[seed] 开放接口虚拟用户 openapi_svc 已创建")
    if not await OpenClient.filter(name="演示接入方").exists():
        await OpenClient.create(
            name="演示接入方", api_key="sk-open-demo0123456789abcdef0123456789",
            bind_dept_no="35001", remark="演示用接入方：归属福建省直(35001)")
        print("[seed] 演示接入方已创建，API Key: sk-open-demo0123456789abcdef0123456789")

    # 知识种子：省级公开(35000) + 福州(35002) + 泉州(35003) 各主题
    kb_spec = [
        ("35000", "缴存比例通用口径", "qa", "公积金缴存比例是多少", 
         "住房公积金缴存比例下限为5%，上限为12%（单位和个人比例须一致）。具体比例由各中心在区间内确定，单位可与职工协商选定。", "deposit", 1),
        ("35000", "贷款额度通用口径", "qa", "公积金贷款额度怎么算",
         "公积金贷款额度=（账户余额+从申请日至退休预计缴存额）×倍数，且不超过当地最高限额。多数城市双职工最高额度100万元、单职工60万元，具体以当地中心规定为准。", "loan", 1),
        ("35000", "销户提取通用条件", "qa", "什么情况可以销户提取公积金",
         "满足以下情形之一可申请销户提取：离休退休；完全丧失劳动能力并与单位终止劳动关系；出境定居；职工死亡（由继承人或受遗赠人提取）。", "withdraw", 1),
        ("35000", "异地转移接续", "common", "全国住房公积金异地转移接续操作指引", 
         "职工到新城市就业的，可通过全国住房公积金小程序或当地线上渠道申请异地转移接续，原缴存地中心在接到申请后5个工作日内办结资金划转，缴存年限合并计算。", "other", 1),
        ("35002", "福州贷款最高额度", "qa", "福州公积金贷款最高能贷多少",
         "福州住房公积金贷款最高额度：双职工家庭100万元，单职工60万元；多孩家庭在上述基础上上浮20%。具体以福州住房公积金中心最新公告为准。", "loan", 0),
        ("35002", "福州租房提取", "qa", "福州租房提取公积金一年能提多少",
         "福州无房职工租房提取：市辖区每年最高提取额度24000元（每月2000元），其他县（市）每年最高18000元；多孩家庭可上浮30%。需提供无房证明（线上核验）。", "withdraw", 0),
        ("35002", "福州冲还贷业务", "doc", "福州公积金委托按月冲还贷办理指南",
         "办理条件：在福州办理公积金贷款且还款满一期。材料：身份证、还款账户。渠道：福州公积金APP-冲还贷签约或柜台办理。生效后每月还款日自动从公积金账户扣划月还款额，账户余额不足时从还款银行卡补扣。已办理冲还贷的，办理其他提取业务前需先终止冲还贷协议。", "loan", 0),
        ("35003", "泉州贷款利率", "qa", "泉州公积金贷款利率是多少",
         "泉州住房公积金贷款利率：5年期以下（含5年）2.35%，5年期以上2.85%（首套）。二套房利率上浮1.1倍。具体以人民银行最新公布的利率为准。", "loan", 0),
        ("35003", "泉州离职提取", "qa", "泉州离职后怎么提取公积金",
         "与单位终止劳动关系且账户封存满半年、未在新单位继续缴存的，可申请销户提取全部余额。线上渠道：闽政通APP-公积金-离职提取；线下：泉州各县区公积金服务大厅。", "withdraw", 0),
    ]
    for dept_no, title, biz_type, q, a, theme, is_public in kb_spec:
        if await Knowledge.filter(dept_no=dept_no, title=title).exists():
            continue        # 幂等：同机构同标题已存在则跳过（无此保护曾致种子被重复插入多轮）
        await Knowledge.create(
            dept_no=dept_no, biz_type=biz_type, title=title,
            question=q if biz_type == "qa" else "", answer=a if biz_type == "qa" else "",
            content="" if biz_type == "qa" else a, theme=theme, is_public=is_public,
        )


async def seed_biz_menus() -> None:
    """业务配置菜单幂等补种（存量库升级）+ manager 角色授权。"""
    spec = [  # (名称, 父级, 类型, 路径, 权限)
        ("业务配置", "", "M", "", ""),  # 顶层目录
        ("流程定义", "业务配置", "C", "", ""),
        ("流程新增", "流程定义", "F", "", "flow:add"), ("流程编辑", "流程定义", "F", "", "flow:edit"),
        ("流程删除", "流程定义", "F", "", "flow:remove"), ("流程发布", "流程定义", "F", "", "flow:publish"),
        ("流程实例", "业务配置", "C", "flow-instances", "flow:instance:list"),
        ("实例强制取消", "流程实例", "F", "", "flow:instance:cancel"),
    ]
    by_name = {m.menu_name: m for m in await SysMenu.all()}
    PERMS = {"流程新增": "flow:add", "流程编辑": "flow:edit", "流程删除": "flow:remove",
             "流程发布": "flow:publish", "实例强制取消": "flow:instance:cancel"}
    for name, parent, mtype, mpath, mperms in spec:
        if name in by_name:
            continue
        p = by_name.get(parent)
        await SysMenu.create(menu_name=name, parent_id=p.id if p else 0,
                             path=mpath, component="", perms=mperms or PERMS.get(name, ""),
                             menu_type=mtype, icon="", sort=1)
        by_name = {m.menu_name: m for m in await SysMenu.all()}
    manager = await SysRole.filter(role_key="manager").first()
    if manager:
        have = {rm.menu_id for rm in await SysRoleMenu.filter(role_id=manager.id)}
        for name, _pt, _mt, _mp, _pp in spec:
            m = by_name.get(name)
            if m and m.id not in have:
                await SysRoleMenu.create(role_id=manager.id, menu_id=m.id)
    print("[seed] 业务配置菜单已就绪（幂等）")


async def main() -> None:
    cfg = AppConfig().sub("mysql")
    await ensure_database(cfg)
    await Tortoise.init(
        db_url=(f"mysql://{cfg['user']}:{cfg['password']}"
                f"@{cfg['host']}:{cfg['port']}/{cfg['database']}"),
        modules={"models": ["app.models"]},
    )
    await Tortoise.generate_schemas()
    await ensure_open_columns()   # 溯源列（generate_schemas 只建表不加列，需显式迁移）

    if RESET or not await SysDept.all().exists():
        if RESET:
            await FlowInstance.all().delete()
            await FlowDef.all().delete()
            await Conversation.all().delete()
            await Knowledge.all().delete()
            await McpTool.all().delete()
            await SysUser.all().delete()
            await SysRole.all().delete()
            await SysMenu.all().delete()
        await seed_all()
        print("[seed] RBAC/工具/知识种子完成")
    else:
        print("[seed] 已有数据，跳过（--reset 可重置）")

    await seed_flows()   # 流程定义幂等补种
    await seed_open_clients()   # 开放接口：虚拟用户 + 演示接入方（幂等）
    await seed_biz_menus()      # 业务配置（流程定义/实例）菜单与授权（幂等）

    # 全部知识入库 ES
    from app.rag import vectorstore
    vectorstore.ensure_index()
    result = await ingest.sync_all_pending()
    print(f"[ingest] 同步完成: {result}")

    from app.rag import vectorstore
    print(f"[es] 索引 {vectorstore.index_name()} 文档数: {vectorstore.count_docs()}")
    await Tortoise.close_connections()


if __name__ == "__main__":
    asyncio.run(main())
