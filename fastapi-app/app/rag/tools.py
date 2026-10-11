# -*- coding: utf-8 -*-
"""MCP 工具面——官方 SDK（FastMCP）同进程 streamable-http 服务 + 部门下发。

对齐原系统的三条约定：
  1. 工具唯一事实源在登记表（mcp_tool）：按部门取用（本部门 + shared 共享）；
  2. Agent 侧经 langchain-mcp-adapters 以标准 MCP 客户端发现（list_tools）→ 过滤可见集
     → bind_tools 绑定会话内工具集；
  3. 敏感字段不外泄：返回值中的证件号/卡号一律前3后4脱敏；**身份证号由登录态绑定**
     （见 app/mock_data.py），用户无需口头提供，工具侧留空即按会话身份查询。

数据来源：app/mock_data.py（与业务流程服务共用同一套 mock 账户档案，调用路径彼此分离）。
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from app.mock_data import account_of, mask
from app.models import McpTool

# ------------------------------------------------------------------
# FastMCP 服务（挂载根路径 /mcp，streamable-http）
# ------------------------------------------------------------------

mcp = FastMCP("gjj-business-tools")


def _acct_or_msg(id_card: str) -> tuple[dict | None, str]:
    acct = account_of(id_card)
    if acct is None:
        return None, f"未查询到 {mask(id_card)} 对应的缴存账户，请确认身份信息"
    return acct, ""


@mcp.tool()
def query_account_balance(id_card: str = "", name: str = "") -> str:
    """查询公积金账户余额与账户状态。

    id_card 留空时按**当前登录账户**查询（演示环境身份已随登录绑定，无需向用户索要）。
    """
    acct, err = _acct_or_msg(id_card)
    if acct is None:
        return err
    return (f"账户信息（{mask(id_card)} {acct['name']}）：\n"
            f"- 账户状态：{acct['status']}\n"
            f"- 当前余额：{acct['balance']:,.2f} 元\n"
            f"- 累计缴存月数：{acct['months']} 个月\n"
            f"- 绑定手机号：{mask(acct['phone'], 3, 2)}")


@mcp.tool()
def query_loan_info(id_card: str = "") -> str:
    """查询本人公积金贷款信息（额度/利率/剩余本金/还款计划）。id_card 留空按当前登录账户查询。"""
    acct, err = _acct_or_msg(id_card)
    if acct is None:
        return err
    loan = acct.get("loan")
    if not loan:
        return f"查询结果（{mask(id_card)} {acct['name']}）：名下无公积金贷款记录。"
    return (f"贷款信息（{mask(id_card)} {acct['name']}）：\n"
            f"- 贷款总额：{loan['total']:,.2f} 元\n"
            f"- 剩余本金：{loan['remain']:,.2f} 元\n"
            f"- 执行利率：{loan['rate']:.2f}%（5年期以上首套）\n"
            f"- 剩余期数：{loan['months_left']} 个月（等额本息）")


@mcp.tool()
def query_deposit_detail(id_card: str = "", months: int = 6) -> str:
    """查询近 N 个月公积金缴存明细。id_card 留空按当前登录账户查询，months 默认 6。"""
    acct, err = _acct_or_msg(id_card)
    if acct is None:
        return err
    months = max(1, min(int(months), 24))
    base = acct["deposit_base"]
    rows = [f"- 第{i + 1}个月：个人 {base:,.0f} 元 + 单位 {base:,.0f} 元（{acct['unit']}）"
            for i in range(months)]
    return f"近 {months} 个月缴存明细（{mask(id_card)} {acct['name']}）：\n" + "\n".join(rows)


# ------------------------------------------------------------------
# 部门下发与发现
# ------------------------------------------------------------------

async def get_visible_tool_names(dept_no: str) -> list[dict]:
    """工具清单按部门下发：本部门 + 共享部门，主键升序端到端保序。"""
    rows = await McpTool.filter(status=1).order_by("id")
    return [
        {"id": r.id, "name": r.name, "description": r.description,
         "parameters": r.parameters}
        for r in rows if r.dept_no == dept_no or r.shared == 1
    ]


async def fetch_langchain_tools(base_url: str):
    """标准 MCP 客户端发现（list_tools）→ LangChain 工具对象。"""
    from langchain_mcp_adapters.client import MultiServerMCPClient
    client = MultiServerMCPClient({
        "gjj": {"url": base_url, "transport": "streamable_http"},
    })
    tools = await client.get_tools()
    return tools
