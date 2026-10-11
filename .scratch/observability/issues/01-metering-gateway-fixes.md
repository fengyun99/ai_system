# 01: 计量网关补洞——embeddings 真值与 rerank 失败记账

**What to build:** LLM 网关的每一笔消耗都进记账器且口径可信：向量化调用优先采用供应商返回的 usage 真值（仅在缺失时字符估算并标记）；重排调用即使失败/回退，也已按估算把消耗记入账上。对应 spec 一期 PT1。

**Blocked by:** None (can start immediately).

**Status:** implemented 2026-10-11（tests/test_llm_metering.py 8 测试全绿）

- [x] embeddings 调用后，供应商返回 usage 时记账行为真值（estimated=0），未返回时才字符估算（estimated=1）
- [x] rerank 传输失败与非 200 两条失败路径在抛错前完成估算记账（estimated=1）；「响应缺 results」第三条失败分支一并记账
- [ ] 人为触发 rerank 超时后，轮次阶段流水的 rerank 行 tokens_in > 0 且带估算标记
  —— meter 层已由单测验证（RerankError 抛出前 meter 行已记录，estimated=1）；
  tokens_in > 0 落库由既有 `_persist` 的 by_stage 回填结构性保证；
  「带估算标记」依赖 PT2 的 turn_stage.tokens_estimated 列，随 PT2 完成时回归勾选。
