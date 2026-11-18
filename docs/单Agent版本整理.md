<!-- 记录单Agent版本合并、用户指定的历史运行删除范围及保留数据的追溯方式。 -->
# 单Agent版本整理

2026-11-18，按学员明确要求：

- 删除旧v0-single注册配置，将原v0-single-404fix的完整配置登记为v0-single，页面名称为“单 Agent”，启用recover_document_404=True。
- 移除v0-single-404fix注册项；两者原本共用app/agents/single.py，无独立旧实现文件需要删除。
- 学员要求删除runs/s05-v0-single-dev100和runs/s05-v0-single-404fix-dev100两份旧评测目录。已核对绝对路径，但自动审批以blocked by policy拒绝递归删除，尚未删除，需学员在本机操作。runs被Git忽略，该删除不由Git保存。
- 保留runs/s05-openrouter-single-404fix-dev100及其原始配置、逐题结果、判分与汇总，不改写历史版本号。该记录中的v0-single-404fix对应本次整理前的版本命名，其行为现由v0-single承接。
- 旧文档中的版本号和运行名保留为历史描述；S05等既有Git标签不改写。

后端进程重启后加载新注册表；页面刷新后版本下拉框更新。未发起新的付费评测。
