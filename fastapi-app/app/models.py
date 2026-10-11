# -*- coding: utf-8 -*-
"""Tortoise ORM 模型——RBAC 权限体系 + 对话/轮次/阶段审计 + 知识库 + 工具登记。

表结构设计原则（较原 Java 版精简）：
  - RBAC 六表沿用若依（RuoYi）语义：sys_dept/sys_user/sys_role/sys_menu/sys_user_role/sys_role_menu；
  - 对话域三表：conversation（整个会话容器）→ turn（轮次，一问一答 + 意图/区域/主题/token/耗时汇总）
    → turn_stage（阶段明细，意图识别/区域识别/问题分类/问题分化/检索/重排/生成/工具调用统一登记，
    标识符 = stage_type）——轮次表+阶段表即完整统计审计流水，不另设 trace 表；
  - 知识库单表 knowledge：问答/文档/常识统一 biz_type 区分，检索侧 ES 只存切块；
  - 工具登记 mcp_tool：按部门下发（本部门 + 共享部门），参数 schema 存 JSON。
"""
from tortoise import fields
from tortoise.models import Model


# ============================== RBAC ==============================

class SysDept(Model):
    """部门（多租户轴）：dept_no 为业务机构号，ancestors 为逗号分隔祖先链。"""

    id = fields.IntField(pk=True, description="部门ID")
    dept_no = fields.CharField(max_length=16, unique=True, description="机构编号")
    dept_name = fields.CharField(max_length=64, description="机构名称")
    parent_id = fields.IntField(default=0, description="父部门ID")
    ancestors = fields.CharField(max_length=255, default="0", description="祖级路径")
    status = fields.CharField(max_length=1, default="0", description="0正常 1停用")
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "sys_dept"


class SysUser(Model):

    id = fields.IntField(pk=True, description="用户ID")
    user_name = fields.CharField(max_length=32, unique=True, description="登录账号")
    nick_name = fields.CharField(max_length=32, default="", description="昵称")
    password = fields.CharField(max_length=128, description="口令密文 $1a+sm3双重摘要")
    dept = fields.ForeignKeyField("models.SysDept", related_name="users", description="主属部门")
    phone = fields.CharField(max_length=20, default="", description="手机号")
    id_card = fields.CharField(max_length=18, default="", description="身份证号（mock 身份，随登录态）")
    status = fields.CharField(max_length=1, default="0", description="0正常 1停用")
    last_login_at = fields.DatetimeField(null=True, description="最后登录时间")
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "sys_user"

    async def to_dict(self, with_dept: bool = True) -> dict:
        data = {
            "user_id": self.id, "user_name": self.user_name, "nick_name": self.nick_name,
            "phone": self.phone, "status": self.status,
            "last_login_at": self.last_login_at.strftime("%Y-%m-%d %H:%M:%S") if self.last_login_at else None,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
        }
        if with_dept:
            dept = await self.dept
            data["dept_id"] = dept.id
            data["dept_no"] = dept.dept_no
            data["dept_name"] = dept.dept_name
        return data


class SysRole(Model):

    id = fields.IntField(pk=True, description="角色ID")
    role_name = fields.CharField(max_length=32, description="角色名称")
    role_key = fields.CharField(max_length=64, unique=True, description="权限字符")
    data_scope = fields.IntField(default=2, description="数据范围 1全部 2本部门及以下")
    status = fields.CharField(max_length=1, default="0")
    remark = fields.CharField(max_length=255, default="")
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "sys_role"


class SysMenu(Model):

    id = fields.IntField(pk=True, description="菜单ID")
    menu_name = fields.CharField(max_length=32, description="菜单名称")
    parent_id = fields.IntField(default=0, description="父菜单ID")
    path = fields.CharField(max_length=128, default="", description="路由地址")
    component = fields.CharField(max_length=128, default="", description="前端组件")
    perms = fields.CharField(max_length=64, default="", description="权限标识")
    icon = fields.CharField(max_length=32, default="", description="图标")
    sort = fields.IntField(default=0)
    menu_type = fields.CharField(max_length=1, default="C", description="M目录 C菜单 F按钮")
    visible = fields.IntField(default=1, description="是否显示")

    class Meta:
        table = "sys_menu"


class SysUserRole(Model):

    id = fields.IntField(pk=True)
    user_id = fields.IntField()
    role_id = fields.IntField()

    class Meta:
        table = "sys_user_role"
        unique_together = (("user_id", "role_id"),)


class SysRoleMenu(Model):

    id = fields.IntField(pk=True)
    role_id = fields.IntField()
    menu_id = fields.IntField()

    class Meta:
        table = "sys_role_menu"
        unique_together = (("role_id", "menu_id"),)


# ============================== 对话域 ==============================

class Conversation(Model):
    """会话容器：归属=提问人机构（登记归属口径）。开放接口会话另记接入方。"""

    id = fields.BigIntField(pk=True, description="会话ID")
    user_id = fields.IntField(description="用户ID")
    dept_no = fields.CharField(max_length=16, description="归属机构号")
    open_client_id = fields.IntField(default=0, description="接入方ID（门户会话为0）")
    title = fields.CharField(max_length=128, default="新会话", description="会话标题")
    turn_count = fields.IntField(default=0, description="轮次数")
    status = fields.CharField(max_length=16, default="active", description="active/deleted")
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "conversation"


class Turn(Model):
    """轮次：一问一答的完整审计单元——意图/区域/主题结果、token 消耗、耗时汇总。"""

    id = fields.BigIntField(pk=True, description="轮次ID")
    conversation = fields.ForeignKeyField("models.Conversation", related_name="turns")
    user_id = fields.IntField()
    dept_no = fields.CharField(max_length=16, description="提问人机构号")
    question = fields.TextField(description="用户问题")
    answer = fields.TextField(default="", description="回答全文")
    intent = fields.CharField(max_length=16, default="", description="意图: rag/business/chitchat")
    region = fields.CharField(max_length=32, default="", description="区域识别结果（机构号或外地区标记）")
    theme = fields.CharField(max_length=16, default="", description="主题: deposit/loan/withdraw/other")
    snapshot_id = fields.CharField(max_length=64, default="", description="材料快照标识")
    flow_instance_id = fields.BigIntField(default=0, description="流程实例ID（历史兼容字段）")
    flow_snapshot = fields.TextField(default="", description="流程展示快照 JSON（历史兼容字段）")
    display_snapshot = fields.TextField(default="", description="展示快照 JSON（来源/相关推荐/办理推荐，历史原样恢复）")
    status = fields.CharField(max_length=16, default="generating",
                              description="generating/done/interrupted/error")
    error_detail = fields.TextField(default="", description="轮次异常详情/堆栈(截断2000)")
    tokens_in = fields.IntField(default=0, description="输入token合计")
    tokens_out = fields.IntField(default=0, description="输出token合计")
    cost = fields.DecimalField(max_digits=12, decimal_places=6, default=0,
                               description="成本(元,登记时单价定格,调价不改历史)")
    ttft_ms = fields.IntField(default=0, description="首字延迟(ms)")
    total_ms = fields.IntField(default=0, description="整轮耗时(ms)")
    source_type = fields.CharField(max_length=8, default="portal",
                                   description="入口: portal门户 / open开放接口")
    open_client_id = fields.IntField(default=0, description="接入方ID（门户轮次为0）")
    source_system = fields.CharField(max_length=64, default="", description="来源系统标识(X-Source-System)")
    trace_id = fields.CharField(max_length=64, default="", description="调用链标识(X-Trace-Id，缺省系统生成)")
    rag_flag = fields.CharField(max_length=128, default="",
                                description="RAG质检标记(逗号分隔: recall_miss/answer_wrong/kb_stale/flag_other)")
    rag_note = fields.CharField(max_length=512, default="", description="质检备注")
    rag_flag_by = fields.IntField(default=0, description="标记人用户ID")
    rag_flag_at = fields.DatetimeField(null=True, description="标记时间")
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "turn"


class TurnStage(Model):
    """阶段登记：一轮回答内每个流程阶段的输入输出/耗时/token 明细。

    stage_type 取值（标识符）：
      intent 意图识别 | region 区域识别 | classify 问题分类 | decompose 问题分化
      retrieve 检索 | rerank 重排 | generate 回答生成 | tool MCP工具调用
    """

    id = fields.BigIntField(pk=True)
    turn = fields.ForeignKeyField("models.Turn", related_name="stages")
    stage_no = fields.IntField(default=0, description="阶段序号")
    stage_type = fields.CharField(max_length=16, description="阶段标识")
    name = fields.CharField(max_length=64, default="", description="阶段名称")
    input_data = fields.TextField(default="", description="输入(JSON)")
    output_data = fields.TextField(default="", description="输出(JSON)")
    status = fields.CharField(max_length=16, default="done", description="done/failed/skipped")
    model = fields.CharField(max_length=64, default="", description="所用模型")
    tokens_in = fields.IntField(default=0)
    tokens_out = fields.IntField(default=0)
    tokens_estimated = fields.IntField(default=0, description="1=本行含字符估算口径的计量(行级记账)")
    cost = fields.DecimalField(max_digits=12, decimal_places=6, default=0,
                               description="本行成本(元,登记时单价定格)")
    duration_ms = fields.IntField(default=0)
    started_at = fields.DatetimeField(null=True, description="开始时间(微秒精度,时间线还原)")
    finished_at = fields.DatetimeField(null=True, description="结束时间(微秒精度)")
    error_detail = fields.TextField(default="", description="异常详情/堆栈(截断2000)")
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "turn_stage"


class TurnRecall(Model):
    """召回明细（RAG 审计）：检索型轮次的候选知识清单。

    仅在检索当时记录——ES chunk_id 为随机 uuid，事后无法由 chunk_id 关联知识条目；
    存量历史轮次无明细（决策见 docs/adr/0001）。
    """

    id = fields.BigIntField(pk=True)
    turn = fields.ForeignKeyField("models.Turn", related_name="recalls")
    knowledge_id = fields.IntField(default=0, description="归属知识条目ID")
    title = fields.CharField(max_length=128, default="", description="知识标题")
    fused_rank = fields.IntField(default=0, description="RRF 融合名次（1 起）")
    fused_score = fields.FloatField(default=0, description="RRF 融合得分")
    kept = fields.IntField(default=0, description="1=经重排保留进入生成")
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "turn_recall"


class TurnFeedback(Model):
    """用户反馈：门户用户对轮次回答的 点赞/差评 + 修改意见（每轮一条，重评覆盖）。

    与质检标记（Turn.rag_flag，管理者判断）互补——用户反馈是自下而上的质量信号，
    二者共同构成 RAG 审计的差评关联口径。
    """

    id = fields.BigIntField(pk=True)
    turn = fields.ForeignKeyField("models.Turn", related_name="feedback")
    user_id = fields.IntField(description="反馈用户（须为该轮提问人）")
    rating = fields.CharField(max_length=4, description="up=点赞 / down=差评")
    comment = fields.CharField(max_length=512, default="", description="修改意见")
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "turn_feedback"


# ============================== 知识库 ==============================

class Knowledge(Model):
    """知识条目：问答(qa)/文档(doc)/常识(common) 统一表，切块进 ES。"""

    id = fields.IntField(pk=True)
    dept_no = fields.CharField(max_length=16, description="归属机构号")
    biz_type = fields.CharField(max_length=8, default="qa", description="qa/doc/common")
    title = fields.CharField(max_length=128, description="标题")
    question = fields.CharField(max_length=512, default="", description="标准问法(qa)")
    answer = fields.TextField(default="", description="标准答案(qa)")
    content = fields.TextField(default="", description="正文(doc/common)")
    theme = fields.CharField(max_length=16, default="other", description="deposit/loan/withdraw/other")
    is_public = fields.IntField(default=0, description="1=对下级公开（祖先链可见）")
    sync_status = fields.IntField(default=0, description="0未同步 1已同步 2失败")
    sync_error = fields.CharField(max_length=512, default="")
    created_by = fields.IntField(default=0)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "knowledge"


class IngestLog(Model):
    """入库计量流水（ADR 0003）：知识入库向量化的消耗与结果登记。

    入库不是轮次，其消耗不进轮次审计（turn/turn_stage）；每次同步（成功或失败）各一行。
    """

    id = fields.BigIntField(pk=True)
    knowledge_id = fields.IntField(description="知识条目ID")
    title = fields.CharField(max_length=128, default="", description="知识标题（落行快照）")
    dept_no = fields.CharField(max_length=16, default="", description="归属机构号")
    chunk_count = fields.IntField(default=0, description="切块数")
    tokens_in = fields.IntField(default=0)
    tokens_out = fields.IntField(default=0)
    tokens_estimated = fields.IntField(default=0, description="1=字符估算口径")
    cost = fields.DecimalField(max_digits=12, decimal_places=6, default=0,
                               description="成本(元,登记时单价定格)")
    duration_ms = fields.IntField(default=0)
    status = fields.CharField(max_length=8, default="done", description="done/failed")
    error = fields.CharField(max_length=512, default="", description="失败原因（截断）")
    operator_user_id = fields.IntField(default=0, description="操作者；0=系统(启动对账/批量)")
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "ingest_log"


# ============================== 工具登记 ==============================

class McpTool(Model):
    """MCP 工具登记：按部门下发（本部门 + shared=1 共享），参数 schema 存 JSON。"""

    id = fields.IntField(pk=True)
    dept_no = fields.CharField(max_length=16, description="归属机构号")
    name = fields.CharField(max_length=64, unique=True, description="工具名")
    description = fields.CharField(max_length=255, default="", description="工具描述")
    parameters = fields.TextField(default="{}", description="JSON Schema(参数)")
    shared = fields.IntField(default=0, description="1=全部门共享")
    status = fields.IntField(default=1, description="1启用 0停用")
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "mcp_tool"


# ============================== 业务流程 ==============================

class FlowDef(Model):
    """流程定义：节点以 JSON 存（form/confirm/auto/end 四类节点 + 线性步进）。"""
    table = "flow_def"

    id = fields.IntField(pk=True)
    flow_key = fields.CharField(max_length=64, unique=True, description="流程标识")
    name = fields.CharField(max_length=64, description="流程名称")
    description = fields.CharField(max_length=255, default="")
    dept_no = fields.CharField(max_length=16, description="归属机构号")
    keywords = fields.CharField(max_length=128, default="", description="办理推荐触发词(空格分隔)")
    mode = fields.CharField(max_length=16, default="embed",
                            description="办理模式: embed=流程引擎嵌入会话 / redirect=复杂业务跳转页面")
    url = fields.CharField(max_length=255, default="", description="redirect 模式的业务页面地址")
    nodes = fields.TextField(default="[]", description="节点定义 JSON（草稿，编辑中）")
    published_nodes = fields.TextField(default="", description="已发布节点 JSON（引擎只读本列；空=未发布）")
    status = fields.IntField(default=1, description="1启用 0停用")
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "flow_def"


class FlowInstance(Model):
    """流程实例：办理中的状态机（current_index + vars + steps 历史）。

    status: running 办理中（门控问答） / done 已完成 / cancelled 已取消
    """
    table = "flow_instance"

    id = fields.BigIntField(pk=True)
    flow_def = fields.ForeignKeyField("models.FlowDef", related_name="instances")
    conversation = fields.ForeignKeyField("models.Conversation", related_name="flows")
    user_id = fields.IntField()
    dept_no = fields.CharField(max_length=16)
    status = fields.CharField(max_length=16, default="running")
    nodes_snapshot = fields.TextField(default="", description="发起时的已发布节点快照（运行中不随定义变更）")
    current_index = fields.IntField(default=0, description="当前节点下标")
    vars = fields.TextField(default="{}", description="已收集变量 JSON")
    steps = fields.TextField(default="[]", description="步进历史 JSON（审计用）")
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "flow_instance"


# ============================== 开放接口域 ==============================

class OpenClient(Model):
    """接入方：持有 API Key 的外部调用系统，绑定一个归属租户。

    三要素、租户视角均由接入方随请求提供/推导；key 演示环境明文存储可查。
    """

    id = fields.BigIntField(pk=True)
    name = fields.CharField(max_length=64, description="接入方名称")
    api_key = fields.CharField(max_length=80, unique=True, description="调用凭证(X-API-Key)")
    bind_dept_no = fields.CharField(max_length=16, description="归属租户机构号")
    status = fields.CharField(max_length=2, default="0", description="0正常 1停用")
    remark = fields.CharField(max_length=255, default="", description="备注")
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "open_client"
