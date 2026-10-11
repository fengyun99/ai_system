# 部署手册（AI 智能客服系统）

> 基于本机（Windows Server / Windows 10+）从零部署的实战记录整理。
> 接口能力说明见 [docs/open-api.md](open-api.md)，Mock 数据见 [docs/mock-data.md](mock-data.md)。

## 一、架构与组件

```
外部调用方 ──┐                         ┌─ MySQL 8      （业务库：RBAC/对话/知识/流程）
             ├─ /api/open/v1/* 开放接口 │
浏览器 ──────┤                         ├─ Elasticsearch 8（知识向量+BM25 混合检索，HTTPS）
             ├─ /api/* 门户与管理端     ├─ Redis        （停止信号/在线态，可缺省降级）
             │        ↓                └─ 阿里 MaaS / DeepSeek（LLM 与向量化，外网）
             │   FastAPI 后端 :9310 ──── MCP 同进程 /mcp
             │   自建联网检索 :8888（SearXNG 协议兼容）
             └─ React 前端 :5173（dev）或 nginx 静态托管（生产）
```

| 组件 | 版本要求 | 默认端口 | 部署形态 |
|---|---|---|---|
| Python 后端 | 3.12 | 9310 | uvicorn（生产：NSSM/服务化 + 多进程） |
| 联网检索服务 | 同后端 venv | 8888 | uvicorn |
| 前端 | Node 18+ | 5173(dev) / 80(nginx) | Vite |
| MySQL | 8.x | 3306 | Windows 服务（自启） |
| Redis | ≥3.0 可用，建议 6+ | 6379 | Windows 服务（自启） |
| Elasticsearch | 8.19.x | 9200(HTTPS) | zip + Windows 服务（手动启动型） |

## 二、基础服务准备

### 2.1 MySQL

```sql
CREATE DATABASE ai_system DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
-- 应用账号（示例；root 也可，演示口径）
CREATE USER 'ai_app'@'%' IDENTIFIED BY '<密码>'; GRANT ALL ON ai_system.* TO 'ai_app'@'%';
```

### 2.2 Elasticsearch（重点，坑最多）

1. **zip 发行版**解压到不含空格与中文的路径（如 `C:\elasticsearch-8.19.22`）。
2. **安全与 TLS**（首次启动自动生成证书后确认）`config/elasticsearch.yml`：
   ```yaml
   xpack.security.enabled: true
   xpack.security.http.ssl:
     enabled: true
     keystore.path: certs/http.p12
   xpack.security.transport.ssl:
     enabled: true
     verification_mode: certificate
     keystore.path: certs/transport.p12
     truststore.path: certs/transport.p12
   cluster.initial_master_nodes: ["<主机名>"]
   http.host: 0.0.0.0
   ```
3. **内存**（`config/jvm.options.d/heap.options`）：`-Xms2g` / `-Xmx4g`（按机器调整，勿默认自动取半内存）。
4. **专用账号**（不动内置 elastic）：`bin\elasticsearch-users.bat useradd ai_system -p '<密码>' -r superuser`。
5. **启动方式：直接运行 `bin\elasticsearch.bat`（手动启动、不开机自启）**：
   - 双击或在终端运行 `bin\elasticsearch.bat`，ES 随该控制台运行，**关闭窗口即停止**；
   - ⚠️ 同一时间只能有一个实例：勿再以 Windows 服务方式启动（服务实例与 bat 实例会争抢 `data\node.lock`，后启动的一方直接退出）；
   - 项目根 `start-es.bat` 是等价的幂等封装（已在运行则跳过，并等待 9200 就绪）。

### 2.3 Redis

Windows 服务方式安装即可。**版本 < 6.0 时（如 3.0.x）不支持 RESP3**，本项目已在代码中固定 `protocol=2` 兼容；新版本无影响。

## 三、后端部署

依赖由 **uv** 管理（`pyproject.toml` + `uv.lock` 锁定 92 包；`requirements.txt` 同步保留作 pip 备选）：

```bat
cd fastapi-app
uv sync                             :: 按锁文件创建 .venv 并安装（清华源已配在 pyproject.toml）
uv run python scripts\init_db.py    :: uv run 自动用 .venv，也可直接 .venv\Scripts\python
```

无 uv 环境的备选：`python -m venv .venv && .venv\Scripts\pip install -r requirements.txt`（3.12；venv 不可跨机器拷贝）。

### 3.1 配置（config/）

- **app.yml**：mysql/es/redis 连接与 jwt 密钥。敏感值可**明文填写**，首次启动自动 SM4 加密回写为 `Enc[...]`；也可用 `.venv\Scripts\python -m app.core.config_cli <明文>` 生成密文后粘贴。**ES 段必须带 `scheme: https`**（自签证书免校验已内置）。
- **model-config.json**：两段式——
  - `deepseek`（聊天）：`base_url: https://api.deepseek.com/v1`，`model: deepseek-flash`，api_key 明文填入自动加密；
  - `embeddings`（向量）：阿里 MaaS `compatible-mode/v1` 端点，`model: qwen3.7-text-embedding`（**1024 维**）。
  - ⚠️ 向量维度必须与 `app.yml es.vector_dims` 一致（当前 1024）；换模型须同步改并重建 `ai_kb` 索引。

### 3.2 初始化与自检

```bat
.venv\Scripts\python scripts\init_db.py            :: 建表+种子（幂等；--reset 重置会清库）
.venv\Scripts\python scripts\check_models.py       :: 模型连通自检（三项全绿为准）
```

### 3.3 启动

```bat
:: 后端（9310；ES 需先手动启动，后端只等待就绪、不再自动拉起）
.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 9310
:: 联网检索服务（8888）
.venv\Scripts\python -m uvicorn search_service.main:app --host 127.0.0.1 --port 8888
```

生产建议：NSSM 将两个 uvicorn 注册为 Windows 服务（`--workers 2` 需配 Redis 供跨进程停止信号），或 Linux 下 systemd + gunicorn-uvicorn-worker。

## 四、前端部署

```bash
cd web && npm install
npm run dev            # 开发模式 5173，/api 与 /mcp 代理到 9310
npm run build          # 生产构建 → dist/，由 nginx 托管并把 /api /mcp 反代到 9310
```

## 五、验证（部署完成的判定标准）

```bat
.venv\Scripts\python scripts\check_models.py        :: 模型三项 ✅
.venv\Scripts\python scripts\intent_test.py         :: 40 条话术意图路由仿真（四意图+边界混合，零误判为准）
.venv\Scripts\python scripts\api_test.py            :: 88 项接口全绿（界面全部能力 + 审计导出/RAG 审计 H 组 + 知识命中报表 I 组）
.venv\Scripts\python scripts\integrity_check.py     :: 45+5 项进程完整性验收
```

浏览器登录 `http://127.0.0.1:5173`（admin / admin123）问答一轮即完成冒烟。

## 六、启动/停止速查（本机实例）

| 动作 | 命令 |
|---|---|
| 启动 ES（手动 bat） | 双击 `C:\elasticsearch-8.19.22\bin\elasticsearch.bat` 或运行 `start-es.bat` |
| 启动后端 | `uvicorn app.main:app --port 9310`（ES 需已在运行） |
| 启动检索服务 | `uvicorn search_service.main:app --port 8888` |
| 启动前端 | `cd web && npm run dev` |
| 停止应用 | 结束两个 uvicorn 与 node(vite) 进程 |
| 停止 ES | 关闭 ES 控制台窗口，或运行 `stop-all.bat`（一并结束 9200/9300） |
| MySQL / Redis | 系统服务（MySQL82 / Redis），开机自启，一般不动 |

## 七、Docker Compose 一键编排（推荐迁移路径）

仓库根目录提供完整容器化（**已在本机实测构建并跑通全链路**）：

| 文件 | 作用 |
|---|---|
| `docker-compose.yml` | 6 服务编排：mysql / redis / es / init(一次性) / backend / search / frontend(nginx) |
| `fastapi-app/Dockerfile` | 后端镜像（python:3.12-slim + uv sync 锁定安装；backend/search/init 共用，差异在 command） |
| `docker/frontend.Dockerfile` | 前端镜像（node 构建 + nginx 托管，`/api`、`/mcp` 反代后端，SSE 禁缓冲） |
| `docker/app.docker.yml` | 容器版配置（服务名主机 mysql/es/redis/search；ES 容器网内走 http 保留账号密码） |
| `docker/nginx.conf` | 前端反代规则（SPA + API + MCP WebSocket 升级） |

```bash
docker compose up -d --build     # 一键构建并启动（首次拉镜像约 10 分钟）
docker compose ps                # 查看状态（mysql/es/redis 带 healthcheck）
docker compose logs -f init      # 看初始化（建表+种子+知识入库，幂等）
docker compose down              # 停止（数据卷保留）；down -v 连数据一起清
```

启动后入口：前端 `http://127.0.0.1:8081`（8080 被占时改 compose ports）、后端 `http://127.0.0.1:9310`（开放接口/管理 API）。模型配置挂载宿主机 `fastapi-app/config/model-config.json`，改 key 后 `docker compose restart backend` 生效。

要点：
1. **配置切换**：容器内 `AI_APP_CONFIG=app.docker.yml`（代码已支持环境变量切配置文件）；ES 容器关闭 http TLS 但保留 elastic 密码认证；
2. **初始化**：init 一次性容器（`depends_on` 三个基础服务 healthy 后跑 `init_db.py`），backend `depends_on init: service_completed_successfully` 保证先建表后启动；
3. **国内网络**：Docker Hub 走加速器（daemon.json `registry-mirrors`）；elastic 官方源本机直连可达，慢时可改用代理前缀；
4. **内存**：ES 容器 `ES_JAVA_OPTS=-Xms1g -Xmx2g`（宿主机方式部署时为 2g/4g，按容器资源配额调整）。

## 八、Linux 迁移（sh 脚本）

项目根目录提供与 bat 一一对应的 **sh 脚本**（LF 换行，`bash -n` 已验证）：

| 脚本 | 说明 |
|---|---|
| `start-es.sh` | 探测 9200 → systemd 启动 elasticsearch（`sudo`）→ 等待就绪；无 systemd 时提示手动 `-d` 启动 |
| `start-backend.sh` / `start-search.sh` | 检查 `.venv/bin/python`（Linux 路径）→ uvicorn 前台启动（`exec`，Ctrl+C 直达） |
| `start-frontend.sh` | node_modules 缺失自动 `npm install` → Vite |
| `start-all.sh` | ES 就绪后以 **nohup 后台**拉起三服务，日志写 `logs/*.log`、PID 写 `run/*.pid` |
| `stop-all.sh` | 按 pidfile 停止（丢失时退化按端口：fuser/lsof/ss）+ `systemctl stop elasticsearch` |

```bash
chmod +x *.sh
bash start-all.sh          # 一键启动
tail -f logs/backend.log   # 看日志
bash stop-all.sh           # 一键停止
```

**与 Windows 的差异清单**：

1. **依赖安装**：`uv sync`（Linux 生成 `.venv/bin/python`，Windows 是 `.venv\Scripts\python.exe`）——venv 不可跨机器拷贝；无 uv 时 `python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt`
2. **ES 服务化**：tar 包安装后 `sudo bin/elasticsearch-service-tokens` 无需，直接注册 systemd（发行版自带 `elasticsearch.service` 单元）：`sudo systemctl daemon-reload && sudo systemctl enable elasticsearch`；或用 `ES_UNIT` 环境变量指定单元名。自建用户/证书/内存配置（jvm.options.d/heap.options）与 Windows 完全一致
3. **目录**：`mkdir -p logs run`（start-all 自动创建）
4. **验证同第五节**：`check_models.py` / `api_test.py` / `integrity_check.py` 与平台无关
5. **生产建议**：uvicorn 改 systemd unit 或 gunicorn（`-k uvicorn.workers.UvicornWorker -w 2`）；前端 `npm run build` 后交 nginx



## 九、常见问题（实战踩坑录）
| 现象 | 原因与处置 |
|---|---|
| ES 连接被拒/连接重置 | 未走 HTTPS——确认 `app.yml` 有 `es.scheme: https` |
| ES 服务启动报 `plugin-descriptor.properties 缺 name` | 发行版文件损坏（本机曾因异常关机磁盘串簇），重解压覆盖 modules 目录 |
| 手动 bat 启动的 ES 莫名退出 | 前台进程随控制台死亡——改用 Windows 服务 |
| redis-py 报 `unknown command 'HELLO'` | Redis < 6.0 无 RESP3；本项目已固定 protocol=2，升级 Redis 可根治 |
| init 后知识重复 | 重复执行 `--reset` 时序问题；用管理端"全量对账"或 `ingest.reconcile()` 修复 |
| 改了 model-config.json 不生效 | 后端进程内缓存，必须重启后端 |
| 知识同步失败 Connection timed out | ES 未启动或账号密码错；管理端"批量同步"重试 |
| 向量检索 0 命中 | 向量维度与索引不一致——核对 vector_dims 并重建索引 |

## 十、生产化清单（演示 → 生产必做）

- [ ] 全链路 HTTPS（nginx 终结或 ES 正式证书），开放接口加网关限流与 IP 白名单
- [ ] API Key 哈希存储 + 接入方管理页（当前明文表演示口径）
- [ ] `auth_ticket` 实名授权核验（当前仅落审计）
- [ ] 三要素传输加密（国密 SM4 信封或字段级加密）
- [ ] MySQL/Redis 独立实例与备份策略；ES 快照仓库
- [ ] 日志集中（loguru → 文件轮转/ELK）；uvicorn 服务化与多副本
