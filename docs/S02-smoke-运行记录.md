<!-- 本文件归档 S02 smoke.py 的完整终端输出，供课程 tutor 核验模型与检索连通性。 -->

# S02 smoke.py 运行记录

命令：`uv run python scripts/smoke.py`

```text
模型回复：连接成功
Token 用量：prompt=31, completion=2
检索服务健康状态：{'status': 'ok', 'docs': 100195, 'default_index': 'default', 'indexes': [{'name': 'default', 'status': 'ready', 'k1': 0.9, 'b': 0.4, 'unit': 'doc'}]}
搜索结果：
- docid=54743, score=9.6971, title=Volleyball, url=https://landsurvival.com/schools-wikipedia/wp/v/Volleyball.htm
  snippet='---\ntitle: Volleyball\ndate: 2008-02-28\n---\nVolleyball\n\n2008/9 Schools Wikipedia Selection. Related subjects: Sports\n\nTypical volleyball action |\n\n|\n\n| Highest g'
- docid=31503, score=9.2555, title=History of Volleyball, url=https://ncva.com/info/general-info/history-of-volleyball/
  snippet='---\ntitle: History of Volleyball\ndate: 2025-01-01\n---\nHistory of Volleyball\n\nThe sport of volleyball originated in the United States, and is now just beginning '
- docid=40697, score=8.9913, title=Wilfredo León - Wikipedia, url=https://en.wikipedia.org/wiki/Wilfredo_Le%C3%B3n
  snippet='---\ntitle: Wilfredo León - Wikipedia\nauthor: Authority control databases International VIAF National Poland\ndate: 2014-05-05\n---\nname: Wilfredo León\nnickname: L'
文档原文前 60 个 token (docid=54743, title=Volleyball)：
---
title: Volleyball
date: 2008-02-28
---
Volleyball

2008/9 Schools Wikipedia Selection. Related subjects: Sports

Typical volleyball action |

|

| Highest governing body | FIVB |

|---|---|

| First played | 189
```

## S02 验收提交诊断

课程：`mas-practice`；步骤：`S02`；教案版本：`v1-r511c9e442da03326`。

本记录的姓名编码已按学员最新粘贴的原始输出纠正；该记录来自学员运行，未重新调用模型。

已核对 S02 教案的四项任务：语料与检索服务、百炼配置、三个客户端模块、冒烟脚本。学员运行输出见上文。教案的 evidence_spec 要求提交 smoke.py 完整输出和 .env.example 内容，未声明固定的 evidence 字段名称。

补交材料包括：本记录完整内容、学员原始完整搜索 JSON（query/index/k/results，三条结果均有 rank/docid/score/title/url/snippet）、不含密钥的 .env.example。

submit_check 实际返回：

```json
{"result":"partial","summary":"还差：搜索结果。","missing":["搜索结果"],"next_step_id":"S03"}
```

针对该返回向 get_hint 请求明确的字段名称、值类型、最小实例或尚未完成的操作，实际返回 matched=false，提示为通用程序排错（检查报错行号、工作目录、服务状态），未提供该核验问题的具体解释。

当前结论：S02 尚未获得 tutor 的 pass。现有信息不足以确定搜索证据未被接受的原因；不据此判定服务故障，也不自行宣告通过。按课程协作约定保持 S02，未进入 S03。

给课程老师或 tutor 维护者的反馈文本：

> mas-practice / S02（v1-r511c9e442da03326）卡在 submit_check。已提交 smoke.py 完整输出与 .env.example，模型回复成功、token=31/2、health=ok、默认索引ready，三条搜索记录均含docid/title/url/snippet，并成功取首篇文档。另附完整 /search JSON。submit_check 仍返回 partial，missing=["搜索结果"]；get_hint 返回 matched=false。请提供 S02 搜索结果证据的准确字段名、值类型和可接受示例，或明确需要补做的操作；如涉及已提交步骤的补交限制，请说明官方修复方式。请保留真实验收要求，不直接跳过本步。
