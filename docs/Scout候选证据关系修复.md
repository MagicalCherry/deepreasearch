<!-- 用途：记录v2.3.5证据语义与独立候选隔离修复、测试及smoke20原始结果。 -->
# v2.3.5：候选证据与关系核查

用户明确授权修正422诊断的第2、3项，并自动执行测试、smoke20及判分。本次不修Scout零工具空报告或重写检索策略，不追加dev100。

新增candidate_evidence_guard选项；候选supported/refuted必须带逐字quote，程序检查其来自该Scout实际见过的摘要或已读正文，缺失或不匹配则降为unresolved并记录原因。保留quote供Critic在原审核调用内检查主体、事件和条件是否真的被支持。字符串匹配仅证明引文存在，不能证明语义；没有宣称自动解决全部幻觉。语义不确定仍应unresolved。

进度中的多个独立候选默认不能组合搜索；显式关系须引用实际观察的原文、包含双方姓名与关系词，否定或独立研究表述不作为合作凭据。Critic补搜组合查询被拆成各候选已有的安全next_query；无安全替代则过滤并审计。Scout直接请求组合查询时拒绝并返回独立查询建议。该检查按已记录完整候选名匹配，别名和只写姓氏仍是局限；关系关键词也不保证语义，Critic仍须审查。不从金标补人物、条件或来源。

旧版本选项不变，模型仍OpenRouter economy，默认600秒，并发8。本次smoke20不含dev100；重试可能增加费用，没有美元硬上限。

失败测试：缺少app.agents.dr.evidence_guard，1 error in 0.19s。实现后自动专项：38 passed in 0.92s；全量：331 passed in 3.15s。

后续研究运行：s20-v235-qwen37-smoke20。原始config/results/events/judged/summary保留在runs目录，本文后续追加结果，不覆盖历史版本成绩。
