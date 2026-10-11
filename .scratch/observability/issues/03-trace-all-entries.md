# 03: trace 全入口统一——门户轮次也有 TraceId 且审计可见

**What to build:** 问题溯源闭环覆盖全部入口：门户问答与开放接口使用同一套 TraceId 生成与透传规则（请求头优先、缺省系统生成），门户轮次落库 TraceId 并随 SSE 元事件下发；管理端轮次审计能按 TraceId 查看。对应 spec 一期 PT3。

**Blocked by:** None (can start immediately).

**Status:** implemented 2026-10-11（tests/test_trace.py 5 测试 + 前端 tsc 通过）

- [x] 门户创建轮次时登记 TraceId（请求头携带则透传，否则系统生成），与开放接口共用同一实现（app/common/trace.py，open.py 委托同一助手）
- [x] 门户 SSE meta 事件携带 TraceId（门户前端契约已有 trace_id? 字段，随流可得）
- [x] 轮次审计列表展示 TraceID 列（截 8 位 + title 全量），详情弹窗展示完整值
- [x] 携带自定义 X-Trace-Id 的门户请求，落库轮次与之一致
  —— 规则层已单测锁定（含大小写不敏感头、去空白、截断 64、缺省生成唯一）；
  端到端（真实门户请求 → 轮次审计核对同一 TraceId）待系统运行时回归
