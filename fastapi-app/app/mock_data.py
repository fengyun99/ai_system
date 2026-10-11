# -*- coding: utf-8 -*-
"""统一 Mock 数据源——登录用户身份与公积金账户档案（演示环境唯一事实源）。

- 登录用户（sys_user）通过 user_name 绑定到这里的一档账户：身份证号/手机号/姓名；
- MCP 工具面（问答查询）与业务流程服务（办理校验）**共用本数据源**，但调用路径保持分离；
- 三要素（身份证号/手机号/姓名）由登录态携带，**不向用户索要、界面不明文展示**（仅掩码回显）。

替换真实系统时：本模块整体替换为「身份中台/账户系统查询」，调用方接口不变。
详见 docs/mock-data.md。
"""
from __future__ import annotations

#: user_name → 绑定的 mock 账户（登录即确定身份）
USER_BINDINGS: dict[str, str] = {
    "admin": "350001199002022345",
    "fzzx": "350102199001011234",
    "qzzx": "350103198505054321",
}

#: 身份证号 → 账户档案
MOCK_ACCOUNTS: dict[str, dict] = {
    "350001199002022345": {
        "name": "王管理员", "phone": "13900010002",
        "status": "正常", "balance": 512300.0, "months": 148,
        "bank_cards": ["6228480402564890018"],
        "loan": {"total": 600000.0, "remain": 412500.0, "rate": 2.85, "months_left": 156},
        "deposit_base": 3200.0, "unit": "福建省直住房公积金管理中心",
    },
    "350102199001011234": {
        "name": "陈测试", "phone": "13900020003",
        "status": "正常", "balance": 394550.0, "months": 110,
        "bank_cards": ["6222021234567890123"],
        "loan": None,   # 无公积金贷款记录
        "deposit_base": 2800.0, "unit": "福州某某科技有限公司",
    },
    "350103198505054321": {
        "name": "林演示", "phone": "13900030004",
        "status": "封存", "balance": 86120.5, "months": 63,
        "bank_cards": ["6217001234567890123"],
        "loan": {"total": 400000.0, "remain": 318000.0, "rate": 2.85, "months_left": 108},
        "deposit_base": 1900.0, "unit": "泉州某某建工有限公司",
    },
    # ---- 开放接口/接口测试专用 mock 用户（外部传三要素 → MCP 可解析）----
    "350105199503031236": {
        "name": "测试甲", "phone": "13911110001",
        "status": "正常", "balance": 188000.0, "months": 96,
        "bank_cards": ["6222021111222233345"],
        "loan": {"total": 300000.0, "remain": 210000.0, "rate": 2.85, "months_left": 120},
        "deposit_base": 3000.0, "unit": "福州测试科技有限公司",
    },
    "350106198812126633": {
        "name": "测试乙", "phone": "13922220002",
        "status": "封存", "balance": 52000.0, "months": 48,
        "bank_cards": ["6222022222333344445"],
        "loan": None,
        "deposit_base": 2100.0, "unit": "泉州测试贸易有限公司",
    },
}

#: 开放接口测试用 mock 用户清单（scripts/api_test.py 引用）
TEST_API_ACCOUNTS = {
    "a": {"id_card": "350105199503031236", "name": "测试甲", "phone": "13911110001",
          "bank_card": "6222021111222233345"},
    "b": {"id_card": "350106198812126633", "name": "测试乙", "phone": "13922220002",
          "bank_card": "6222022222333344445"},
}


def account_of(id_card: str) -> dict | None:
    """按身份证号取账户档案（未登记返回 None）。"""
    return MOCK_ACCOUNTS.get((id_card or "").strip())


def id_card_of_user(user_name: str) -> str:
    """登录账号 → 绑定的身份证号（未绑定返回空串）。"""
    return USER_BINDINGS.get(user_name, "")


def mask(value: str, head: int = 3, tail: int = 4) -> str:
    value = value or ""
    if len(value) <= head + tail:
        return "*" * len(value)
    return value[:head] + "*" * (len(value) - head - tail) + value[-tail:]
