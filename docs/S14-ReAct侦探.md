<!-- 用途：记录S14（v1.8）ReAct侦探任务、预算和角色交接边界、测试及评测原始证据。 -->
# S14：v1.8 ReAct侦探

## 阶段任务

| 任务 | 具体内容 | 产出 | 验证方式 |
|---|---|---|---|
| 注册失败测试 | 继承v1.7，仅改scout=react、scout_tool_calls=12 | 版本差异测试 | 学员先观察未知版本v1.8 |
| ReAct Scout | 英文提示包含总问题、全部约束、其他侦探候选、本子问题与建议检索式；自行调用search/get_document；要求Findings与Candidates | react_section | 假模型工具调用测试 |
| 预算 | 子任务预算min(12,max(2,50-已用搜索))；整题搜满50次不再启动；并发共享预算防超限 | 预算与工具接入 | 边界、并发测试 |
| 循环异常 | react_loop支持shrink及raise_on_max_turns=False；到上限保留最后文字；content_filter放弃当前子任务 | 循环适配 | 离线测试，不修改旧版默认行为 |
| 报告交接 | parse_scout_report拆解带docid事实与候选；仅接纳真实工具来源；存_scout_reports，Writer接收报告 | 解析与角色交接 | 虚构报告、无效来源及完整流水线测试 |
| 回归 | 接入现有v1.6.1保留状态流程，避免ResilientScout覆盖入口导致react选项无效 | 实际可达的新Scout路径 | 专项及全量pytest |
| smoke20 | 先20题研究并判分；观察真实token、耗时及错误 | summary | 学员运行付费命令 |
| dev100 | 复用兼容的20题成功结果与判分，只补80题 | summary、对v1.7的+N/-M | 学员运行并贴原始输出 |
| 召回分档与复盘 | 两版按0、非零且不足50%、至少50%召回分档；查看改善题的实体追踪；比较token和耗时 | 离线对照及案例 | tutor原始证据验收 |
| 发布 | 代码与版本报告记录GitHub | 独立版本分支和标签 | 推送结果 |

## 边界

课程材料只读，答案与金标证据编号只供离线评测，不放进提示词或检索请求。不将S13排查建议全部混入v1.8，影响对照的额外修复需单独说明。

本阶段继续OpenRouter qwen/qwen3.7-flash、关闭思考、默认并发8。ReAct可能增加上下文输入与费用，先smoke20再dev100，以真实用量为准；目前没有美元硬上限，不自动启动模型请求。教案提及dev100约6000万输入token，仅作教案参考，不作为当前模型与实现的费用承诺或准确率保证。

## 当前进度

已添加注册失败测试，等待学员运行。尚未实现v1.8、未进行付费评测。S13已pass；S12保留partial。

## 实现记录

学员已观察失败测试：test_v18_adds_react_scout_with_twelve_tool_calls，ValueError: 未知版本：v1.8，1 failed, 8 passed in 0.88s。

已注册v1.8；ResilientScout初始及补搜实际分支均接ReAct，避免选项注册后仍走旧循环。英文提示包含总问题、全部约束、同伴候选、子任务及建议查询。工具使用react.Tools子类，事件保留scout-n泳道；每子任务最多12次工具调用，接近整题搜索上限时按教案缩小；搜索共享原子预算，阅读沿用8篇上限并共享缓存。子任务重试保留已用工具数和实际见过的结果，不恢复预算。

新路径让模型直接使用BM25搜索及正文工具，不再调用旧的“两条模型扩写+RRF”搜索路径；仍清理语法、拒绝未消解占位符并检查重复/近似查询。这些旧选项保留在继承配置内，但ReAct工具路径不使用自动扩写/RRF，是本阶段替换Scout带来的实际行为变化。

Findings/Candidates解析不接受无末尾docid的事实，入库还要求来源确为当前侦探工具返回过的文档。候选仅作为假设共享。原报告存_scout_reports并发scout_report事件，Writer收到原报告及“报告不是独立证据”的使用规则，前端支持查看。缺失内容仍不能用模型记忆补齐。

react_loop新增shrink与raise_on_max_turns=False可选参数，默认保持旧版调用语义；新Scout截短工具结果应对内容审核，到上限时收回工具并保持发现报告格式，若收尾无有效内容返回已有最后文字。持续content_filter仅结束当前子问题；欠费和取消继续传播。

新增scripts/compare_recall_bands.py，避免旧单Agent分档脚本依赖max_tool_calls而无法分析多Agent；比较两版各自的召回分档，不暗示档内始终是同一批题目。

虚构资料测试覆盖报告解析、无效来源、实际ReAct路径、工具事件、并发预算、阅读缓存、预算耗尽、内容审核、欠费/取消、上限收尾、重试和Writer报告交接；待学员执行专项与全量pytest。助手仅做Python语法检查，未运行pytest或真实评测；不提前承诺准确率或费用变化。

## 离线回归通过，准备smoke20

2026-11-20学员原始全量输出：189 passed in 2.06s。研究实现提交26163ad。下一批为s14-v18-qwen37-smoke20，版本v1.8、题集smoke20、默认并发8；仍使用OpenRouter economy配置与qwen/qwen3.7-flash，不改变模型和思考开关。先运行20题、判分并查看token/耗时，再准备复用同配置20题结果补dev100。此记录不表示真实评测已经完成；没有新增模型调用，当前没有美元硬上限。

## smoke20完成及离线对照

运行s14-v18-qwen37-smoke20，来源提交4ad3cb6aa1d88e0b30f2b0479d6f11a1990a5e3e，20/20，运行错误0。

原始summary：n=20，correct=7，accuracy=35.0，recall=34.67，calibration_error=19.84，calib_beta=5，avg_confidence=28.0，runner_errors=0，avg_search=25.8，avg_read=0.9，avg_prompt_tokens=653398，avg_completion_tokens=13980，avg_seconds=137.75，confidence_source=response_field_when_valid_else_original_judge，version=v1.8，dataset=smoke20，judge_model=qwen/qwen3.7-flash。

对v1.7 smoke20：+4/-0，改善331、934、906、1047，退步无。召回分档（每版按自己的召回分档，不一定同一批题）：

| 召回档 | v1.7题数/答对 | v1.8题数/答对 |
|---|---:|---:|
| 0 | 11/0 | 7/0 |
| 非零且不足50% | 3/0 | 6/0 |
| 至少50% | 6/3 | 7/7 |

高召回档7/7仅为20题小样本观察，不当作稳定100%正确率。零召回题数11→7，但仍7题完全未命中标注证据。最终答案Confidence与judge字段不一致0题，最多搜索44次、最多阅读3篇，共保存85份侦探报告。

相比v1.7，输入57737→653398 token/题，约11.32倍；输出13517→13980；耗时118.14→137.75秒，实际增加约16.6%，不能套用教案中“耗时反而下降”的预期。阅读1.6→0.9篇/题，不能把提升简单解释为读得更多。

按本批均值线性外推，dev100剩余80题研究约52271840输入token、1118400输出token，不含判分及额外重试，实际会随题目分布和停机情况变化；没有美元硬上限。告知学员用量后先提供不调用模型的复用准备命令，不自动启动收费评测。当前S14未提交正式验收，尚未完成dev100。

## dev100完成及验收partial

运行s14-v18-qwen37-dev100-reuse20完成100/100、运行错误0，来源提交58388837fe6d65636f84a740f72eba0c853d15f6。原summary、对照及分档见S14-dev100证据.json，版本报告见releases/v1.8/版本报告.md。

实际准确率29%、召回27.53%、校准误差9.69、平均置信度27.6%、输入620775/输出14259 token、142.90秒/题。对v1.7 +17/-2。输入约12.02倍，耗时增加33.89%；零召回48→49，未解决该瓶颈。高召回档14/28→22/28，各版档内题目不一定相同。置信度提取不一致0题。

Tutor result=partial，原文：“还差：dev100 ≥ 40%。请把对应命令的原始输出或文件原文原样贴上来再提交一次，不要转述。” missing=["dev100 ≥ 40%"]，next_step_id=S15。已提交完整原始输出，不重复提交相同29%碰门槛。get_hint返回matched=true，hint="正常，工具结果累积在每个侦探的上下文里。"，未解释40%或给出质量修复方案。保留S14未通过，不自动推进S15；后续方向需学员确认，不自动收费重跑。

GitHub已原子推送release/v1.8分支和v1.8标签，发布提交c36d0fc；基于dev100实际运行代码5838883追加版本报告。标签说明明确S14 partial、未达40%，不覆盖远端main/master。地址：https://github.com/MagicalCherry/deepreasearch/tree/release/v1.8 。
