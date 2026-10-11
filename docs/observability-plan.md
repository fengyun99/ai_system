# 全链路可观测性建设方案

> 状态：已拍板（2026-10-11 访谈定稿，Q1-Q13 全部决策见第 2 节）。
> 路线：**分阶段演进**——一期堵计量与溯源的洞（故事线核心），二期补精度与日志纵深；OTel/APM 暂缓（见第 5 节）。
> 领域词汇见根目录 CONTEXT.md；关键取舍见 docs/adr/0002、0003。

## 1. 现状基线

平台的可观测性走「业务审计表」路线（已定决策，README 迁移表）：`turn`（轮次汇总：
意图/token/TTFT/总耗时）→ `turn_stage`（阶段流水：14 类阶段 × 模型/输入输出/状态/
耗时/token）→ `turn_recall`（召回明细，ADR 0001）；流程引擎另有 `flow_instance.steps`
JSON 步进。管理端已有仪表盘/轮次审计/RAG 审计三页。**主链路（门户问答 → RAG 各阶段
→ LLM 网关）的每一步与 token 已可追踪、可回放。**

本方案要堵的洞（评估结论）：

| # | 缺口 | 位置 |
|---|------|------|
| G1 | 知识入库 embedding token 全部丢弃，且错标 stage="retrieve" | `fastapi-app/app/rag/ingest.py:27` |
| G2 | embeddings 不读响应 usage 真值，纯字符估算且 estimated 不落库 | `fastapi-app/app/rag/llm.py:209-212` |
| G3 | token 按 stage_type 聚合回填到该类型每一行，多行重复计；agent 循环 token 全归 tool 阶段 | `fastapi-app/app/api/chat.py:181-182` |
| G4 | rerank 失败回退路径不记 token | `fastapi-app/app/rag/llm.py:235-242` |
| G5 | 无成本维度（无单价、无 cost 字段、无按接入方汇总） | 全局 |
| G6 | 门户 chat 无 trace_id；trace_id 落库但前端无任何页面渲染 | `fastapi-app/app/api/chat.py:79-82` |
| G7 | turn_stage 无起止时间戳（并行 fanout 不可还原）、异常无详情落库、suggest/末端 generate 计时为 0 | `fastapi-app/app/rag/graph.py` |
| G8 | 全仓零 logging（loguru 声明未用），日志与审计流水无关联键 | 全局 |
| G9 | 无 OTel/APM/metrics | 全局（暂缓，见第 5 节） |

## 2. 已定决策（访谈 Q1-Q13）

| 决策点 | 结论 |
|--------|------|
| 方案定位 | 分阶段演进：一期计量+溯源闭环，二期精度+日志，重基建暂缓 |
| 计量补洞（G1-G4） | 全做 |
| trace 统一（G6） | 做：门户补 trace_id + 审计页展示，门户/开放同一套生成与透传规则 |
| 成本深度（G5） | 轻量版：model-config.json 单价 + cost 定格落库 + 仪表盘成本卡；**配额/账单归 OpenAPI 设计第二轮，本轮不混** |
| 单价口径 | 元 / 1K tokens，分输入/输出两口价，人民币，DECIMAL(12,6) |
| 成本计算时机 | 落库时按当时单价算死（ADR 0002） |
| 入库 token 去处 | 新表 ingest_log 独立登记（ADR 0003） |
| turn_stage 增强（G7） | 全做：started_at/finished_at/error_detail 三列 + 计时修复 |
| 时间线视图 | 做：轮次审计详情加横向阶段时间线 |
| 日志深度（G8） | 最小落地：loguru + turn/trace 上下文绑定 + access 中间件；不上集中式日志 |
| OTel/APM（G9） | 本轮不做，写暂缓决策与触发条件 |
| 交付 | spec（本文档）+ tracer-bullet tickets（.scratch/observability/issues/） |

## 3. 一期：计量与溯源闭环

共同主题：**token 从来源到金额全程可交代**。完成后「每一步消耗了多少 token、值多少
钱、这轮从哪来」三个问题在库里都有定格答案。

### PT1 计量网关补洞（G2、G4，llm.py 单文件）

1. `embed_texts` 优先读 `resp.usage.prompt_tokens` 真值；缺失时按现行字符估算并标
   `estimated=1`（`llm.py:209-212` 改造）。
2. `rerank_documents` 的两个失败分支（传输失败 `llm.py:235-236`、HTTP 非 200
   `llm.py:237-238`）在抛 `RerankError` 前按字符估算补记 token（estimated=1）——失败
   也是一次真实消耗。
3. `TokenRow.estimated` 语义固化为 0/1 标记（现为 int 兜底位，注释说明）。

验收：嵌入/重排调用后 meter 行的 estimated 只有在供应商未返回 usage 时为 1；rerank
超时后 turn_stage 的 rerank 行 tokens_in > 0。

### PT2 行级记账贯通（G3，llm.py → graph.py → chat.py）

1. `TokenRow` / `TokenMeter.add` 增加 `stage_no` 参数（`llm.py:97-122`）；graph 各
   节点调 meter 时传当前阶段号（`_stage()` 登记时分配，`graph.py:98-113`）。
2. agent 工具循环（`graph.py:564-576`）每次 `ainvoke` 的 usage 记到对应 tool 行
   stage_no，不再整段归 tool 类型。
3. `_persist` 回填从 `meter.by_stage(stage_type)` 改为按 stage_no 精确匹配
   （`chat.py:181-182`）；turn_stage 增加 `tokens_estimated` 列（该行任一组成计量
   为估算则 1）。
4. 前端轮次审计详情（`web/src/views/manager/Turns.tsx` 阶段流水）随新口径自然消除
   重复显示；估算口径行加「估」角标。

验收：agent 多工具轮次的每一行 tool stage 各自显示本行 token，逐行求和 == turn 汇总；
generate 行不再为 0（agent 路径下最终答案生成若有独立 ainvoke 则记入其 stage_no）。

### PT3 trace 全入口统一（G6）

1. `open.py` 的 `_trace_of`（`open.py:65-69`）上移到公共模块（app/common/），门户
   chat 创建 Turn 时同样：优先读请求头 `X-Trace-Id`，缺省 `uuid4().hex`
   （`chat.py:79-82`）。
2. 门户 SSE meta 事件携带 trace_id（对齐 open.py:198 的行为）。
3. 轮次审计列表加「TraceID」列、详情弹窗展示完整值（`web/src/views/manager/`
   `Turns.tsx`；契约 `web/src/types/api.ts` 已有 trace_id 字段）。

验收：门户提问一轮 → 审计列表可见该轮 trace_id；带自定义 X-Trace-Id 重放请求，
轮次记录同一 trace_id。

### PT4 模型单价与成本定格（G5，依赖 PT2）

1. `model-config.json` 每条目增加 `price`：`{"input": 元/1K, "output": 元/1K}`；
   `ModelEntry` 加载之（`llm.py:33-46`），提供 `price_of(model_name)` 查询。
2. turn / turn_stage 增加 `cost` DECIMAL(12,6)（元）；`_persist` 时按 ADR 0002 定格：
   行 cost = Σ(该行各笔 token × 所属模型单价)，turn cost = Σ 行。单价缺失记 0。
3. 仪表盘（`app/api/audit.py:165-202` + `web/src/views/manager/Dashboard.tsx`）增加
   成本卡：今日 / 累计成本（元，保留 4 位显示）。
4. 轮次审计列表与详情展示单轮成本。

验收：一轮深度问答的成本 = Σ 各阶段成本，改单价后该轮历史 cost 不变、新轮次用新价。

### PT5 入库计量 ingest_log（G1，ADR 0003）

1. 新表 `ingest_log`：id / knowledge_id / title / dept_no / chunk_count /
   tokens_in / tokens_out / tokens_estimated / cost / duration_ms / status
   (done/failed) / error / operator_user_id / created_at。
2. `sync_knowledge`（`ingest.py:11-36`）改为：独立 meter 传给 `embed_texts`（stage
   改 "ingest"，修正 G1 的错标）、整体计时、成功落一行；`mark_failed`（`ingest.py:39`）
   落 failed 行（error 截断 500）。cost 按单价定格（依赖 PT4 的 price_of，故顺序在
   PT4 后）。
3. 管理端知识库列表/详情可见该条目最近入库记录（消耗/耗时/状态）；仪表盘增加
   「入库成本」口径（与轮次成本分开聚合）。

验收：同步一条知识 → ingest_log 出现一行，chunk 数与 tokens 与实际一致；失败重试后
两行历史（failed + done）都在。

## 4. 二期：精度与日志纵深

三个包彼此独立，做一件是一件。

### ST1 turn_stage 时间与异常列（G7）

1. turn_stage 增加 `started_at` / `finished_at` DATETIME(6)、`error_detail` TEXT；turn 增加 `error_detail`（轮次级异常）。
2. `_stage()` 登记时记录起止（`graph.py:98-113`）；suggest（`graph.py:341-342`）与
   agent 末端 generate（`graph.py:629-630`）补计时，消灭 duration_ms=0。
3. 节点异常路径（rerank/web_search 已有 fallback 标记）与轮次级异常
   （`chat.py:130-136`）落 error_detail（堆栈截断 2000 字符）。
4. schema 变更走 `scripts/init_db.py` ALTER 补丁模式（对齐 `init_db.py:398-413`）。

验收：classify 与 decompose 两行 started_at 重叠（并行可还原）；制造一次模型 401，
turn.error_detail 非空且 turn_stage 对应行有堆栈。

### ST2 阶段时间线视图（依赖 ST1）

轮次审计详情弹窗增加横向时间线：各阶段条形（started_at→finished_at，相对轮起点），
并行 fanout 一眼可见；失败段红色、估算 token 角标保留。纯前端（Turns.tsx）。

验收：点开一轮 rag 问答，能看到 classify/decompose 并排、generate 最长的条形图。

### ST3 日志最小落地（G8）

1. 启用 loguru：结构化格式（时间/级别/turn_id/trace_id/阶段/消息），按天轮转
   `logs/app/`，保留 14 天。
2. contextvars 上下文：请求中间件置入/清理 turn_id、trace_id；`_stage()` 与 LLM 网关
   关键路径（调用开始/结束/失败）`logger.bind` 输出——实现「从审计流水反查日志」。
3. access 中间件：method/path/status/耗时/turn_id 一行一条（uvicorn access log 之外
   的应用层口径）。

验收：任取一轮 turn_id，能在日志中 grep 出该轮全部阶段调用记录与中间异常。

## 5. 暂缓决策：OTel / APM / metrics（G9）

**本轮不做**，与已定的「不建独立 trace 体系」路线一致：单机演示规模下，DB 审计流水
+ 结构化日志已覆盖排障与演示需求；Jaeger/Prometheus 全家桶对当前部署形态（start-all
脚本单机起停）是净复杂度。仪表盘维持 DB 聚合（15s 轮询）口径。

**重启触发条件**（满足其一即立二期+)：

- 多实例部署（水平扩容后单机日志/DB 聚合失效）；
- 跨服务排障成为常态痛点（主服务 ↔ search_service ↔ ES ↔ 模型网关的 span 级定位需求）；
- 需要实时告警（QPS/错误率/延迟阈值，DB 轮询粒度不够）。

届时优先 OTel SDK + 采trace 语义映射到 turn/stage（不新建表，与审计表路线兼容）。

## 6. Schema 变更汇总

| 表 | 变更 | 期 |
|----|------|----|
| turn | + `cost` DECIMAL(12,6) | 一期 PT4 |
| turn_stage | + `tokens_estimated` INT / `cost` DECIMAL(12,6) | 一期 PT2/PT4 |
| turn_stage | + `started_at` `finished_at` DATETIME(6)（对齐 tortoise 建表精度）/ `error_detail` TEXT | 二期 ST1 |
| turn | + `error_detail` TEXT（轮次级异常详情，票据 06 验收「轮次错误详情非空」所需） | 二期 ST1 |
| ingest_log（新表） | 见 PT5 | 一期 PT5 |

所有变更走 Tortoise 模型 + init_db.py ALTER 补丁；存量行新列取默认值（cost=0 /
tokens_estimated=0），不回填、不迁移历史（与 ADR 0001「存量无召回明细」同口径）。

## 7. 总验收口径

建成后，以下问题每个都有库内定格答案（演示动线在 demo-guide.md 主题 7/8 基础上补
「成本卡 + 时间线 + TraceID 列 + 入库消耗」四个点）：

1. 这轮问答从哪来？（trace_id 全入口）—— 任意轮次
2. 走了哪些步骤、每步多久、哪些并行？（阶段流水 + 时间线）
3. 每步烧了多少 token、真值还是估算？（行级记账 + estimated 口径）
4. 每步/每轮/养知识库各花了多少钱？（cost 定格 + 仪表盘双口径）
5. 失败发生在哪一步、为什么？（error_detail + failed 行）
6. 出了问题怎么排？（turn_id 反查结构化日志）
