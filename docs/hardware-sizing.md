# 硬件规格评估（整机全栈启动需要多大的机器）

> 评估对象：ai_system 全栈 = 后端 FastAPI(:9310) + 联网检索服务(:8888) + 前端 Vite(:5173)/nginx(:8081) + MySQL 8 + Redis(Memurai) + Elasticsearch 8.19。
> 方法：组件清单与显式配置逐条核对（文件:行号）+ 本机实测（2026-09-30，全栈运行中采样）。
> 结论先行，证据在后。本文为研究性评估，实测数据来自单机演示负载，非压测。

## 一、结论（最低 / 推荐配置）

| 维度 | 最低配置（能全跑起来、轻负载） | 推荐配置（含余量） |
|---|---|---|
| **CPU** | 4 核 4 线程 x86_64（ES 冷启动用满 1-2 核约 1-3 分钟） | **8 核 16 线程**及以上（冷启动快、构建/测试/浏览器并行不卡） |
| **内存** | **8 GB**（ES 堆须按 1-2 GB 配，即 Docker 口径） | **16-32 GB**（宿主口径 ES 堆 4 GB 时取 32 GB；容器口径 2 GB 堆时 16 GB 即舒适） |
| **磁盘** | **60 GB**（其中数据盘建议 SSD） | **100-200 GB SSD**（Docker 镜像 + 数据增长 + 日志余量） |
| **对应部署形态** | Docker Compose（ES 堆 1g/2g）或宿主部署（堆调 1-2g） | 宿主 Windows 单机（堆 2g/4g）或 Docker Compose 均可 |

两种口径的差异说明：

| 口径 | ES 堆 | 全栈稳态内存（实测/推算） | 说明 |
|---|---|---|---|
| **本机 Windows 单机**（bat 脚本） | -Xms2g / -Xmx4g | 实测 ≈ **3.0 GB**（工作集）/ 3.6 GB（提交） | ES 堆吃到上限时 RSS 峰值 ≈ 5-6 GB，需按此留预算 |
| **Docker Compose** | -Xms1g / -Xmx2g | 推算 ≈ **2.0-2.5 GB**（不含 Docker Desktop 自身） | Docker Desktop(WSL2) 另占 2-4 GB，8 GB 机器需用 `.wslconfig` 限制 |

一句话结论：**这套系统是演示/轻负载规模，瓶颈只在 ES 的堆配置**。4 核 8 GB 是地板（ES 堆压到 2 GB），8 核 16 GB 是舒适区，32 GB 是"宿主口径 4 GB 堆 + 开发机全家桶"的推荐值。磁盘消耗极小（当前全栈数据合计 < 3 MB），60 GB 盘就能装下一切，给 SSD 是为了 ES 冷启动与索引速度。

---

## 二、组件清单（要跑的全部东西）

来源：项目根启动脚本、docker-compose.yml、docs/deploy.md 第一章组件表（`docs/deploy.md:19-26`）。

| # | 组件 | 启动方式 | 进程数 | 端口 |
|---|---|---|---|---|
| 1 | Elasticsearch 8.19.22 | `start-es.bat` → `bin\elasticsearch.bat` 前台（`start-es.bat:14`） | 1 个 JVM | 9200/9300 |
| 2 | 后端 FastAPI | `start-backend.bat:15`：`python -m uvicorn app.main:app --host 127.0.0.1 --port 9310` | **1 进程**（无 `--workers`） | 9310 |
| 3 | 联网检索服务 | `start-search.bat:10`：`python -m uvicorn search_service.main:app --port 8888` | **1 进程**（无 `--workers`） | 8888 |
| 4 | 前端 Vite dev | `start-frontend.bat:9`：`npm run dev` | node 1-2 进程 | 5173 |
| 5 | MySQL 8.2.0 | Windows 服务 MySQL82，开机自启（`docs/deploy.md:24,133`） | 1 进程 | 3306 |
| 6 | Redis 兼容（Memurai） | Windows 服务，开机自启 | 1 进程 | 6379 |
| 7 | （Docker 口径）nginx 前端 | `docker/frontend.Dockerfile`，宿主 8081 | 1 容器 | 8081 |

关键事实：

- 两个 uvicorn 均**未设 workers**（`start-backend.bat:15`、`start-search.bat:10`；sh 版同样无：`start-backend.sh:16`、`start-search.sh:12`），即各 1 个 Python 进程。`docs/deploy.md:102` 提到生产可加 `--workers 2`（需配 Redis），但当前部署形态是单进程。
- Docker Compose 共 **6 个服务容器**（mysql/redis/es/init(一次性)/backend/search/frontend，`docker-compose.yml:9-107`），**未设任何 `mem_limit`/`cpus`**（全文件无该字段），资源靠宿主自然分配。
- 外部依赖（不占本机资源）：LLM/向量化走外网 API（DeepSeek / 阿里 MaaS，`docs/deploy.md:13`）。

## 三、显式资源配置核对（文件:行号）

| 组件 | 配置项 | 值 | 来源 |
|---|---|---|---|
| ES（宿主） | JVM 堆 | `-Xms2g` / `-Xmx4g` | `C:\elasticsearch-8.19.22\config\jvm.options.d\heap.options:1-2` |
| ES（容器） | JVM 堆 | `-Xms1g -Xmx2g`（`ES_JAVA_OPTS`） | `docker-compose.yml:43`；另见 `docs/deploy.md:160` |
| MySQL | innodb_buffer_pool_size | **128M**（MySQL 默认值，未调大） | `C:\ProgramData\MySQL\MySQL Server 8.2\my.ini:258` |
| MySQL | max_connections | 151（默认） | `my.ini:174` |
| MySQL | tmp_table_size / innodb_log_buffer_size | 444M / 16M | `my.ini:188` / `my.ini:248` |
| Memurai | maxmemory | **未设置**（配置中该行为注释 `# maxmemory <bytes>`，即不设上限、按需使用） | `C:\Program Files\Memurai\memurai.conf:1039` |
| 后端/检索 | uvicorn workers | 未设置 = 单进程 | `start-backend.bat:15`、`start-search.bat:10` |
| 后端依赖 | Python 3.12，uv 锁定 92 包（fastapi/uvicorn/elasticsearch/pyredis 等） | — | `fastapi-app/pyproject.toml:8-34`；包数见 `docs/deploy.md:68` |
| Docker | mem_limit / cpus | 均未设置 | `docker-compose.yml`（全文无） |

## 四、本机实测（2026-09-30，最重要的第一手证据）

### 4.1 机器规格

```
CPU:    13th Gen Intel Core i5-13490F，10 核 / 16 线程
内存:   68,520,095,744 B ≈ 64 GB（可见 66,914,156 KB；采样时空闲 53,080,676 KB ≈ 50.6 GB，
        即整机已用 ≈ 13.8 GB——含 IDE/浏览器等全部其他应用）
磁盘:   C: 953.9 GB，剩余 203.8 GB（D:/E: 物理盘已坏不可用，全栈均在 C:）
OS:     Windows 11 专业版
```

命令：`Get-CimInstance Win32_Processor / Win32_ComputerSystem / Win32_LogicalDisk`。

### 4.2 全栈运行中的进程实测内存（全栈 7 个端口全部在跑）

端口→PID 用 `netstat -ano` 确认；内存用 `Get-Process` 采样：

| 进程 | PID | 端口 | 工作集 RSS (MB) | 提交内存 (MB) | 累计 CPU 时间 |
|---|---|---|---|---|---|
| java (**Elasticsearch**) | 16836 | 9200/9300 | **2436** | 2485 | 14 秒 |
| java（ES server-cli 辅助进程） | 4888 | — | 90 | 89 | — |
| mysqld (**MySQL82**) | 8296 | 3306 | 78 | **629** | 3.4 秒 |
| memurai (**Redis**) | 4184 | 6379 | 76 | 57 | 2.9 秒 |
| python (**后端 uvicorn**) | 4112 | 9310 | **148** | 132 | 1.0 秒 |
| python (**检索 uvicorn**) | 9232 | 8888 | 49 | 38 | 0.4 秒 |
| node (**Vite dev**) | 19536 | 5173 | 118 | 215 | 0.5 秒 |
| **合计（核心 7 进程）** | | | **≈ 2995 MB ≈ 3.0 GB** | ≈ 3645 MB ≈ 3.6 GB | |

补充观察：

- ES 自 12:09 启动至采样（约 55 分钟）仅累计 **14 CPU 秒**（<0.5% 单核），其余服务均 <4 CPU 秒——**演示负载下 CPU 几乎空转，内存才是规格的决定因素**。
- ES RSS 2436 MB 对应 `-Xms2g` 预分配堆 + 约 400 MB 堆外；若堆吃到 `-Xmx4g` 上限，RSS 峰值按堆外 1.5-2 GB 预算 ≈ **5.5-6 GB**。
- 存在两组冗余残留进程：两个 3.6 MB 的 `.venv` python（PID 19568/17068，端口已被系统 Python 启动的实例占用，属启动失败残留）和一个 1.7 MB 的 mysqld（PID 6992）。忽略不计，上表取端口持有者。
- **Docker daemon 未运行**（named pipe 不存在），Docker 口径无法实测，第 5 节按镜像公开大小推算。

### 4.3 数据与安装目录占用

| 目录 | 实测大小 | 说明 |
|---|---|---|
| MySQL `ai_system` 库 | **1.1 MB** | `SELECT table_schema, ROUND(SUM(data_length+index_length)/1024/1024,1) FROM information_schema.tables GROUP BY 1`（root 直连实测）；演示种子数据规模 |
| ES 数据目录 `C:\elasticsearch-8.19.22\data` | **596 KB**（4 个索引） | `du -sh` 实测；知识库为演示规模 |
| ES 安装本体 `C:\elasticsearch-8.19.22` | **826 MB** | 含内置 JDK |
| `web/node_modules` | 125 MB | `du -sh` 实测 |
| `fastapi-app/.venv` | 174 MB | 同上 |
| 项目根合计 | 302 MB | 同上 |

## 五、规格推导

### 5.1 内存（逐项加总）

**最低配置（8 GB 的账，Docker 口径/ES 堆压到 2 GB）：**

| 项 | 预算 |
|---|---|
| ES：堆 2 GB + 堆外 ~1 GB | 3.0 GB |
| MySQL（buffer_pool 128M，实测提交 0.6 GB） | 0.8 GB |
| Memurai（无 maxmemory，实测 76 MB） | 0.3 GB |
| 后端 + 检索 uvicorn（实测 0.2 GB） | 0.4 GB |
| 前端（nginx ≈ 50 MB；Vite dev ≈ 0.3 GB） | 0.3 GB |
| Windows Server/11 基线 | 2.5 GB |
| **合计** | **≈ 7.3 GB → 8 GB 机器贴线可跑** |

若 8 GB 机器走 Docker Compose，还需为 Docker Desktop(WSL2) VM 预留 2-4 GB——此时必须用 `.wslconfig` 限制 VM 内存并把 ES 堆压到 1 GB（`docker-compose.yml:43` 的 `-Xms1g -Xmx2g` 即为此设计），或宿主直装各服务绕开 Docker 开销。

**推荐配置（含余量）：**

| 项 | 宿主口径（堆 2g/4g） | Docker 口径（堆 1g/2g） |
|---|---|---|
| ES（堆上限 + 堆外 2 GB） | 6.0 GB | 3.0 GB |
| MySQL / Memurai / 双 uvicorn / 前端 | 1.8 GB | 1.8 GB |
| Docker Desktop 自身 | — | 3.0 GB |
| Windows 基线 | 4.0 GB | 4.0 GB |
| 余量：浏览器(1-2 GB) + ES 冷启动 + `api_test`/`integrity_check` 验收脚本 + IDE/编辑器(2-4 GB) | 8.0 GB | 8.0 GB |
| **合计** | **≈ 19.8 GB → 32 GB 稳妥（24 GB 紧凑可用）** | **≈ 15.8 GB → 16 GB 即舒适** |

> 注：`docs/deploy.md:55` 明确 ES 堆"按机器调整，勿默认自动取半内存"——8 GB 机器切勿用默认（会抢 4 GB 堆）。

### 5.2 CPU

- 实测：全栈稳态 55 分钟内核心进程累计 CPU 均 <15 秒（4.2 节），任意 2 核即可维持运行负载。
- 需求峰值来自四件事：① ES 冷启动（1-3 分钟内吃满 1-2 核，`start-es.bat:16` 注明"冷启动 1-3 分钟属正常"）；② `npm run build` 前端构建（单核为主，数十秒）；③ `scripts/api_test.py`（88 项）/`integrity_check.py`（45 项）验收（单进程串行）；④ 开发时浏览器 + IDE。
- ES 官方最低要求 2 核。综合：**最低 4 核**（保证冷启动时系统不冻结），**推荐 8 核 16 线程**（本机 10C/16T 全程余量充足，同档 i5/Ryzen 5 级别即可，无需服务器 CPU）。

### 5.3 磁盘（Windows 单机 / Docker 合计估算）

| 项 | 大小 | 依据 |
|---|---|---|
| Windows 系统 + 页面文件 | 40 GB | 常规预算 |
| 项目代码 + node_modules + .venv | 0.4 GB | 实测 302 MB（4.3 节） |
| ES 安装（zip 发行版） | 1 GB | 实测 826 MB |
| ES/MySQL 数据（演示规模） | <10 MB，**预留 5-10 GB** 增长 | 实测 596 KB / 1.1 MB |
| Docker 口径：镜像（mysql:8 ≈0.6G + redis:alpine ≈0.05G + es:8.19.22 ≈1.4G + 后端镜像 ≈0.6G + 前端镜像 ≈0.2G）+ 卷 | **≈ 3-4 GB** | 公开镜像大小推算（**本机 Docker daemon 未运行，未能实测**） |
| 日志/临时/浏览器缓存 | 5 GB | 常规预算 |
| **合计** | **最低 ≈ 50 GB（60 GB 盘）；推荐 100-200 GB SSD** | |

磁盘结论：当前数据规模（MySQL 1.1 MB + ES 596 KB）对容量几乎无要求，**任何 60 GB 以上磁盘都能跑**；给到 SSD 与 100 GB+ 是为 ES 冷启动/索引速度与知识库增长留余量，而非当前刚需。

## 六、未实测项声明

1. **Docker Compose 全栈**：Docker daemon 未运行（未获授权启动），容器口径内存/磁盘为按 `docker-compose.yml` 配置与公开镜像大小的推算值。
2. **ES 冷启动峰值 CPU/内存**：ES 正在运行，不允许重启，启动峰值按堆配置（Xmx 上限）与 `start-es.bat:16` 的 1-3 分钟冷启动说明推算。
3. **压测负载**：所有实测为演示/空闲负载；并发用户数上升时，先到瓶颈的是后端单进程 uvicorn（无 workers）与 ES 堆，届时规格需另行评估。

*实测命令均在本机只读执行（Get-CimInstance / Get-Process / netstat / mysql information_schema / du），未启停任何服务。*
