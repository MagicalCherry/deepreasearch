<!-- 用途：解释前端覆盖文件的交付范围及应用方法。 -->
# 评测前端覆盖文件

仅保存已修改的Lanes.tsx与RunsPage.tsx，包括阶段产出、缺失记录提示和正确答案显示。原课程材料只读。新建副本时prepare_frontend.py自动应用；已有副本运行`uv run python -X utf8 scripts/apply_frontend_overrides.py`。目标文件必须匹配原版或当前归档的SHA256，未知修改会拒绝覆盖。应用后需重新构建前端。nginx/Vite端口替换仍由原准备脚本负责。
