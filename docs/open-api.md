# 对外开放接口文档（Open API）

> 本文档所有响应均为**真实环境实测数据**（2026-09-26 采集），可直接作为对接参考。
> 领域术语（接入方/区域路由/租户祖先链/问题溯源）见根目录 `CONTEXT.md`。

## 一、能力总览

| 能力 | 接口 | 说明 |
|---|---|---|
| 智能问答（同步） | `POST /api/open/v1/chat/ask` | 一次性返回回答全文 + 引用来源 + 推荐问题 |
| 智能问答（流式） | `POST /api/open/v1/chat/stream` | SSE 逐事件推送（阶段进度/文本/来源），与门户体验一致 |
| 账户数据查询 | `POST /api/open/v1/account/query` | 余额 / 贷款 / 缴存明细（MCP 工具的 HTTP 形态，返回脱敏） |
| 公开知识查询 | `GET /api/open/v1/knowledge` | 只读公开知识条目（is_public=1），支持机构/主题/关键词过滤 |
| 轮次审计查询 | `GET /api/open/v1/turns` | 查询**本接入方**产生的问答轮次（支持 TraceId 反查） |

## 二、基础信息

| 项 | 值 |
|---|---|
| 服务地址 | `http://127.0.0.1:9310`（演示环境；生产应走 HTTPS 网关） |
| 鉴权方式 | 请求头 `X-API-Key`（接入方凭证，`open_client` 表登记） |
| 溯源头（可选） | `X-Source-System`（来源系统标识）、`X-Trace-Id`（调用链标识，缺省系统生成并回写响应头） |
| 响应形态 | 统一 `{code, msg, data}`；`code=200` 成功，`401/403/404/422` 为业务错误码 |
| 内容类型 | `application/json`（问答流式接口为 `text/event-stream`） |

**演示凭证**（`scripts/init_db.py` 种子）：

```
X-API-Key: sk-open-demo0123456789abcdef0123456789
```

**演示 Mock 用户**（`app/mock_data.py`，外部传三要素 → MCP 工具可解析）：

| 用户 | 身份证号（请求体 id_card） | 账户情况 | 登记卡号 |
|---|---|---|---|
| 测试甲 | `350105199503031236` | 正常户 · 余额 188,000.00 · 贷款 30 万 · 缴存 96 个月 | 6222021111222233345 |
| 测试乙 | `350106198812126633` | 封存户 · 余额 52,000.00 · 无贷款 · 缴存 48 个月 | 6222022222333344445 |

未登记证件号返回"未查询到 … 对应的缴存账户"。门户演示账号（admin/fzzx/qzzx）另见 `docs/mock-data.md`。

## 三、快速开始

```bash
# 同步问答（归属 35001 的接入方，问福州问题 → 自动路由到福州 35002 知识）
curl -X POST http://127.0.0.1:9310/api/open/v1/chat/ask \
  -H "X-API-Key: sk-open-demo0123456789abcdef0123456789" \
  -H "X-Source-System: erp-demo" -H "X-Trace-Id: demo-001" \
  -H "Content-Type: application/json" \
  -d '{"question":"福州公积金贷款最高能贷多少","id_card":"350105199503031236","name":"测试甲"}'
```

## 四、接口明细

### 4.1 同步问答 `POST /open/v1/chat/ask`

**请求体**：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| question | string | 是 | 用户问题（公积金域内） |
| conversation_id | int | 否 | 续问时回传（首次响应返回，仅可续本接入方会话） |
| id_card | string | 是 | 身份证号（18 位，工具查询自动注入） |
| name | string | 否 | 姓名 |
| phone | string | 否 | 手机号（11 位） |
| auth_ticket | string | 否 | 用户授权凭据（预留，仅落审计） |

**实测响应**（问"福州公积金贷款最高能贷多少"，接入方归属 35001）：

```json
{
  "code": 200,
  "msg": "操作成功",
  "data": {
    "conversation_id": 39,
    "turn_id": 47,
    "trace_id": "doc-demo-001",
    "answer": "**福州住房公积金贷款最高额度：**\n\n- 双职工家庭：**100万元**\n- 单职工：**60万元**\n- 多孩家庭：在上述基础上**上浮20%**\n\n具体以福州住房公积金中心最新公告为准。（来源：福州贷款最高额度）\n\n如涉及贷款额度具体测算，可拨打 12329 咨询。",
    "sources": [
      { "title": "福州贷款最高额度", "dept_no": "", "public": false, "score": null },
      { "title": "贷款额度通用口径", "dept_no": "", "public": false, "score": null },
      { "title": "福州冲还贷业务", "dept_no": "", "public": false, "score": null }
    ],
    "questions": [],
    "error": null
  }
}
```

响应头含 `X-Trace-Id: doc-demo-001`（透传回显）。上例体现了**区域路由跨租户**：接入方归属 35001（省直），问题提及福州 → 检索自动切换福州 35002 的知识作答。

### 4.2 流式问答 `POST /open/v1/chat/stream`（SSE）

请求体同 4.1。响应为 `text/event-stream`，每帧 `data: {JSON}`。

**事件类型**：`meta`（轮次元信息，含 conversation_id/trace_id）→ `stage`（管线阶段进度）→ `tool`（工具调用卡片，业务查询类问题）→ `text`（回答增量，字段 `content`）→ `sources`（引用来源）→ `questions`（推荐问题）→ `done`。

**实测帧序列**（问"泉州公积金贷款利率是多少"，归属 35001 接入方 → 区域路由泉州 35003）：

```
data: {"type":"meta","conversation_id":40,"turn_id":48,"title":"泉州公积金贷款利率是多少","trace_id":"doc-sse-001"}

data: {"type":"stage","stage_type":"intent","name":"意图识别","status":"done","duration_ms":837,
       "summary":{"intent":"rag","reason":"用户咨询泉州公积金贷款利率，属于公积金政策知识查询。"}}

data: {"type":"stage","stage_type":"region","name":"区域识别","status":"done","duration_ms":684,
       "summary":{"region_name":"泉州","is_external":false,"target_dept_no":"35003"}}

data: {"type":"stage","stage_type":"classify","name":"问题分类","status":"done","duration_ms":1221,
       "summary":{"theme":"loan"}}

data: {"type":"stage","stage_type":"decompose","name":"问题分化","status":"done","duration_ms":1221,
       "summary":{"sub_queries":["泉州公积金贷款利率是多少"]}}

data: {"type":"stage","stage_type":"retrieve","name":"混合检索(BM25+kNN→RRF)","status":"done","duration_ms":201,
       "summary":{"routes":[{"sub_query":"泉州公积金贷款利率是多少","bm25_hits":2,"knn_hits":2}],
                  "fused":2,"materials":2,"snapshot_id":"cde48df4a1644087"}}

data: {"type":"stage","stage_type":"rerank","name":"重排序","status":"failed","duration_ms":0, ...}
...（judge 材料充分性判断 / generate 回答生成 / text 增量 / sources / questions / done）
```

> 重排序 `status:"failed"` 表示重排服务不可用自动回退融合序（设计语义，不阻塞回答）。

**工具调用类问题**（如"帮我查一下我的公积金账户余额"）额外产生 `tool` 帧：模型工具调用实参留空时，系统自动注入请求体传入的 `id_card`（三要素注入链路见 4.3 说明）。

### 4.3 账户数据查询 `POST /open/v1/account/query`

**请求体**：`action`（`balance`/`loan`/`deposit`）、`id_card`（必填 18 位）、`name`（可选，balance 用）、`months`（可选，deposit 用，默认 6）。

**实测响应（balance，测试甲）**：

```json
{
  "code": 200, "msg": "操作成功",
  "data": {
    "action": "balance",
    "id_card": "350***********1236",
    "result": "账户信息（350***********1236 测试甲）：\n- 账户状态：正常\n- 当前余额：188,000.00 元\n- 累计缴存月数：96 个月\n- 绑定手机号：139******01"
  }
}
```

**实测响应（loan，测试甲，有贷款）**：

```json
{ "data": { "action": "loan", "id_card": "350***********1236",
  "result": "贷款信息（350***********1236 测试甲）：\n- 贷款总额：300,000.00 元\n- 剩余本金：210,000.00 元\n- 执行利率：2.85%（5年期以上首套）\n- 剩余期数：120 个月（等额本息）" } }
```

**实测响应（deposit，测试甲，近 3 个月）**：

```json
{ "data": { "action": "deposit", "id_card": "350***********1236",
  "result": "近 3 个月缴存明细（350***********1236 测试甲）：\n- 第1个月：个人 3,000 元 + 单位 3,000 元（福州测试科技有限公司）\n- 第2个月：个人 3,000 元 + 单位 3,000 元（福州测试科技有限公司）\n- 第3个月：个人 3,000 元 + 单位 3,000 元（福州测试科技有限公司）" } }
```

> 脱敏规则：证件号前 3 后 4、手机号前 3 后 2，其余以 `*` 占位；所有展示面一致。

### 4.4 公开知识查询 `GET /open/v1/knowledge`

**Query**：`dept_no`（机构号过滤）、`theme`（deposit/loan/withdraw/other）、`q`（标题关键词）、`page`、`size`（≤100）。

**实测响应（theme=loan）**：

```json
{
  "code": 200, "msg": "操作成功",
  "data": {
    "total": 1,
    "rows": [
      { "id": 2, "dept_no": "35000", "biz_type": "qa",
        "title": "贷款额度通用口径", "question": "公积金贷款额度怎么算", "theme": "loan" }
    ]
  }
}
```

> 仅返回 `is_public=1` 的公开知识；各机构私有知识不对外（防枚举）。

### 4.5 轮次审计查询 `GET /open/v1/turns`

**Query**：`trace_id`（精确反查）、`page`、`size`。仅返回**本接入方**产生的轮次。

**实测响应**：

```json
{
  "code": 200, "msg": "操作成功",
  "data": {
    "total": 10,
    "rows": [
      { "id": 46, "conversation_id": 38, "question": "那单职工呢", "intent": "rag",
        "region": "", "theme": "loan", "status": "done",
        "trace_id": "dfd5fb0154834acf88c6febd7ea2efc3", "source_system": "",
        "tokens_in": 1993, "tokens_out": 2446, "total_ms": 19580,
        "created_at": "2026-09-26 03:38:51" },
      { "id": 45, "conversation_id": 38, "question": "福州公积金贷款最高能贷多少", "intent": "rag",
        "region": "福州", "theme": "loan", "status": "done",
        "trace_id": "apitest-final", "source_system": "api-test",
        "tokens_in": 1554, "tokens_out": 1487, "total_ms": 10856,
        "created_at": "2026-09-26 03:38:40" }
    ]
  }
}
```

> `source_system`/`trace_id` 即调用方透传的溯源信息——接入方可用 TraceId 串联自己的业务链路与问答审计。

## 五、错误码（真实文案）

| code | 场景 | 实测 msg |
|---|---|---|
| 401 | 缺少 X-API-Key | `缺少 X-API-Key 请求头` |
| 401 | Key 无效 | `API Key 无效` |
| 403 | 接入方停用 | `接入方已停用，请联系管理员` |
| 404 | 越权延续他人会话 | `会话不存在或不属于该接入方` |
| 422 | question 为空 | `question 不能为空` |
| 422 | 身份证号格式错 | `id_card 必须为 18 位身份证号` |
| 422 | 手机号格式错 | `phone 必须为 11 位手机号` |
| 422 | action 非法 | `action 须为 balance/loan/deposit` |

## 六、行为语义与数据说明

1. **区域路由（跨租户）**：检索租户由**问题内容**决定，不可显式指定。问题提及的城市存在对应机构（如福州 35002、泉州 35003）→ 按该机构可见性检索（本机构全量 ∪ 其祖先链公开）；未命中机构的外地区问题（如北京）→ 自建联网检索兜底（与门户同管线同开关）。
2. **三要素处理**：`id_card/name/phone` 仅用于本次请求的工具查询与审计；落库展示全部脱敏；`auth_ticket` 仅透传落审计不做核验（预留实名授权）。
3. **会话延续**：`conversation_id` 由调用方管理——首次不传，响应返回后回传即延续上下文（限本接入方）。
4. **审计落库**：每轮问答在 `turn` 表登记 `source_type=open / open_client_id / source_system / trace_id`，阶段流水（每阶段模型/token/耗时）在 `turn_stage` 表，管理端"轮次审计"可见回放。
5. **性能参考（实测）**：知识问答整轮 8-20 秒（含意图/区域/分类/分化/检索/判官/生成/推荐 8-9 个模型调用）；账户查询 <1 秒；知识/审计查询 <100ms。

## 七、验收与自检

- 全量接口回归：`.venv/Scripts/python.exe scripts/api_test.py`（50 项，含开放接口 8 项）
- 进程完整性验收：`.venv/Scripts/python.exe scripts/integrity_check.py`（第 15-19 项为开放接口专项）
- 边界（演示口径）：Key 与三要素明文传输仅限内网演示；生产需 HTTPS、Key 哈希存储与限流。
