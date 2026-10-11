# 04: 模型单价与成本定格——token 流水折算为金额

**What to build:** 每轮问答、每个阶段都能回答「值多少钱」：模型配置维护分输入/输出的千 token 人民币单价；落库时按当时单价把 token 折算为成本定格进轮次与阶段流水（调价不改历史，决策见 ADR 0002）；管理端仪表盘与轮次审计展示成本。对应 spec 一期 PT4。

**Blocked by:** 02（行级记账——阶段行成本依赖逐行 token 口径）。

**Status:** implemented 2026-10-11（tests/test_cost.py 7 测试 + 前端 tsc 通过）

- [x] 模型配置条目支持单价（元/1K tokens，输入/输出两口价），加载后可按模型名查询（price_of，匹配 model/embeddings_model 两种记账名）
- [x] turn / turn_stage 新增成本列（DECIMAL(12,6)，元；存量默认 0 不回填；单价缺失记 0）——已有部署需跑一次 scripts/init_db.py
- [x] 落库时定格成本：单轮成本 == 各阶段行成本之和（门户与开放接口共用 _persist，同样定格）
- [x] 仪表盘新增成本卡（今日/累计，¥4 位小数），轮次审计列表与详情展示单轮成本、阶段行显示本行成本
- [x] 修改单价后：历史轮次成本不变，新轮次按新价（口径验证于 meter 定格语义单测；DB 层历史行不被 UPDATE 由 ALTER 无回填保证）

附注（回溯修复）：schemas.py 补齐票据 02/03 的 StageRow.tokens_estimated 与 TurnRow.trace_id 声明——
此前 audit.py 已序列化但 schema（extra=forbid）未声明，属运行时 500 潜伏缺陷，本票顺手修复并有契约测试锁定。
