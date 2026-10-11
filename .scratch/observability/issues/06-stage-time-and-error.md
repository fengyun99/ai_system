# 06: 阶段时间与异常列——并行可还原、失败有详情

**What to build:** 每个阶段行记录起止时间（毫秒精度）与异常详情：并行执行的阶段在时间线上可还原先后与重叠；一切计时死角（追问推荐、agent 末端生成）补齐；轮次级与阶段级异常把错误详情/堆栈落库，排障不再只靠 SSE 短消息。对应 spec 二期 ST1。

**Blocked by:** None (can start immediately)（属二期，与一期票据无依赖冲突）。

**Status:** implemented 2026-10-11（tests/test_stage_timing.py 7 测试 + sqlite 落库回读 + 前端 tsc 通过）

- [x] turn_stage 新增起止时间 DATETIME(6)（对齐 tortoise 建表精度）与 error_detail TEXT；turn 新增 error_detail（轮次级）——存量默认空不回填，已有部署跑一次 scripts/init_db.py
- [x] 阶段登记记录起止时间（_timer 一体化耗时+墙钟，timer 参数贯通 12 个调用点）；追问推荐与 agent 末端生成行接计时，耗时不再为 0；rerank/web_search 失败行也获得真实耗时
- [x] 轮次异常与阶段回退路径落异常详情（stage_error_guard 包装全部 12 节点：失败登记含堆栈行、耗时到失败点后重抛；截断常量 MAX_ERROR_DETAIL=2000 全局共用）
- [x] 并行阶段（分类∥分化）起止重叠可验证（重叠区间单测锁定）
- [x] 模型认证失败：轮次 error_detail 非空 + 对应阶段行含堆栈（guard 单测以 401 场景模拟；真实 401 端到端待运行时回归）

审查修复：① guard 原实现 with 包 try——异常分支在 timer finally 前登记，finished_at=None/ms=0 违背「耗时到失败点」；重构为先退出计时再登记，测试补 finished_at 断言。
