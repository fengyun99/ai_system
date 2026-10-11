# -*- coding: utf-8 -*-
"""业务流程服务层（模拟业务系统）——办理流程专用，与 MCP 工具面完全分离。

职责边界：
  - MCP 工具面（app/rag/tools.py）：面向**问答/查询**场景，由大模型发现与调用；
  - 本模块：面向**办理流程**场景，由流程引擎按节点定义直接调用，不经过 MCP/大模型。

数据来源：与工具面共用 app/mock_data.py 的同一套 mock 账户档案（调用路径彼此分离）。
接口形态按真实业务系统设计（校验 → 查询 → 受理），替换为真实业务系统 = 换实现不改调用方。
详见 docs/mock-data.md。
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime

from app.mock_data import MOCK_ACCOUNTS, account_of, mask as _mask

_ID_RE = re.compile(r"^\d{17}[\dXx]$")
_CARD_RE = re.compile(r"^\d{16,19}$")


class BizFormError(Exception):
    """表单业务校验失败：携带字段级错误（前端逐字段红色提示，不推进流程）。"""

    def __init__(self, errors: dict[str, str]):
        self.errors = errors
        super().__init__("; ".join(f"{k}: {v}" for k, v in errors.items()))


# ------------------------------------------------------------------ 字段级校验

def validate_field(rule: str, value, vars_: dict) -> str:
    """按字段规则做模拟后端校验，返回错误文案；通过返回空串。"""
    text = "" if value is None else str(value).strip()

    if rule == "id_card":
        if not _ID_RE.match(text):
            return "身份证号格式不正确（应为 18 位，末位可为 X）"
        if account_of(text) is None:
            return "未查询到该身份证号对应的缴存账户，请核对后重新填写"
        return ""

    if rule == "bank_card":
        if not _CARD_RE.match(text):
            return "银行卡号应为 16-19 位数字，请检查后重新填写"
        id_card = str(vars_.get("id_card", "")).strip()
        account = account_of(id_card)
        if account and text not in account["bank_cards"]:
            return (f"卡号与缴存人 {account['name']} 的登记账户不一致"
                    "（演示：请使用本人名下 I 类卡，见 mock 数据文档）")
        if not account:
            return "请先填写正确的身份证号，再填写收款卡号"
        return ""

    if rule == "amount":
        try:
            amount = float(text)
        except (TypeError, ValueError):
            return "金额必须为数字"
        if amount <= 0:
            return "提取金额必须大于 0"
        id_card = str(vars_.get("id_card", "")).strip()
        account = account_of(id_card)
        if account and amount > account["balance"]:
            return f"提取金额超过账户余额（当前可提取 {account['balance']:,.2f} 元）"
        return ""

    if rule == "spouse_name":
        # 联动校验：已婚时配偶信息必填（对齐真实流程"已婚按家庭核验"）
        if vars_.get("marriage") == "已婚" and not text:
            return "已婚家庭办理需填写配偶姓名（提取额度按家庭计算）"
        return ""

    if rule == "spouse_id_card":
        if vars_.get("marriage") != "已婚":
            return ""
        if not _ID_RE.match(text):
            return "配偶身份证号格式不正确（18 位，末位可为 X）"
        if account_of(text) is None:
            return "未查询到配偶身份证号对应的登记信息，请核对"
        return ""

    return ""


# ------------------------------------------------------------------ 自动节点动作（业务流程专用）

def query_account_snapshot(id_card: str = "", **_) -> str:
    """账户核验（业务系统接口模拟）：返回账户状态/余额/可提取额度。"""
    account = account_of(str(id_card))
    if not account:
        return f"账户核验失败：未查询到 {id_card} 对应的缴存账户"
    return (f"账户核验通过：{account['name']}（{_mask(id_card)}）\n"
            f"- 账户状态：{account['status']}\n"
            f"- 账户余额：{account['balance']:,.2f} 元\n"
            f"- 可提取额度：{account['balance']:,.2f} 元\n"
            f"- 累计缴存：{account['months']} 个月")


def verify_extract_amount(amount=0, id_card: str = "", **_) -> str:
    """金额校验（业务系统接口模拟）：额度规则校验。"""
    account = account_of(str(id_card))
    if not account:
        return "额度校验失败：账户信息缺失"
    amt = float(amount or 0)
    if amt > account["balance"]:
        return f"额度校验不通过：申请金额 {amt:,.2f} 元超过可提取额度 {account['balance']:,.2f} 元"
    return f"额度校验通过：申请金额 {amt:,.2f} 元 ≤ 可提取额度 {account['balance']:,.2f} 元"


def submit_application(flow_key: str = "", scene: str = "", **_) -> str:
    """受理提交（业务系统接口模拟）：返回受理单号与预期办结时间。"""
    no = f"SL{datetime.now().strftime('%Y%m%d')}{uuid.uuid4().hex[:6].upper()}"
    return (f"业务系统受理成功\n- 受理单号：{no}\n- 业务类型：{scene or flow_key}\n"
            f"- 预期办结：3 个工作日")


def verify_deposit_eligibility(id_card: str = "", **_) -> str:
    """缴存资格核验（对接缴存登记系统接口模拟）：连续正常缴存满 3 个月。"""
    account = account_of(str(id_card))
    if not account:
        return "缴存资格核验失败：未查询到缴存记录"
    if account["months"] < 3:
        return f"缴存资格核验不通过：连续缴存 {account['months']} 个月，不足 3 个月（租房提取要求连续正常缴存满 3 个月）"
    return (f"缴存资格核验通过（缴存登记系统）\n- 缴存人：{account['name']}（{_mask(id_card)}）\n"
            f"- 连续正常缴存：{account['months']} 个月 ≥ 3 个月\n- 缴存单位：{account['unit']}")


def verify_no_house(id_card: str = "", marriage: str = "", spouse_id_card: str = "", **_) -> str:
    """无房核验（对接不动产登记中心接口模拟）：本人（已婚含配偶）名下无自有住房。

    真实口径：福州已实现数据联网核查，线上办理免提交纸质无房证明。
    """
    account = account_of(str(id_card))
    who = account["name"] if account else _mask(id_card)
    lines = [f"不动产登记中心联网核验通过\n- {who}（{_mask(id_card)}）：名下无自有住房记录"]
    if marriage == "已婚" and spouse_id_card:
        sp = account_of(str(spouse_id_card))
        sp_name = sp["name"] if sp else _mask(spouse_id_card)
        lines.append(f"- {sp_name}（{_mask(spouse_id_card)}）：名下无自有住房记录（家庭口径）")
    lines.append("- 核验方式：数据联网核查（免提交纸质无房证明）")
    return "\n".join(lines)


def verify_rent_record(rent_type: str = "", files: dict | None = None, **_) -> str:
    """租赁备案核验（对接住建租赁备案系统接口模拟）：上传材料与备案信息比对。"""
    files = files or {}
    uploaded = [f.get("filename", "") for f in files.values() if isinstance(f, dict)]
    contract = next((v for k, v in files.items() if k == "lease_contract"), None)
    if not contract:
        return "租赁备案核验失败：未检测到租赁合同材料"
    if rent_type == "公租房":
        return (f"租赁备案核验通过（公租房管理机构）\n- 租赁类型：公租房\n"
                f"- 材料：{contract.get('filename', '')}（租金缴纳凭证与管理系统一致）")
    return (f"租赁备案核验通过（住建租赁备案系统）\n- 租赁类型：商品房\n"
            f"- 材料：{contract.get('filename', '')}（合同要素与备案信息一致）\n"
            f"- 已上传材料 {len(uploaded)} 份")


#: 流程自动节点可调用的动作（限定在本模块内——业务流程与 MCP 工具面分离）
FLOW_ACTIONS = {
    "query_account_snapshot": query_account_snapshot,
    "verify_extract_amount": verify_extract_amount,
    "submit_application": submit_application,
    "verify_deposit_eligibility": verify_deposit_eligibility,
    "verify_no_house": verify_no_house,
    "verify_rent_record": verify_rent_record,
}
