<!-- 说明OpenRouter独立配置、模型调用参数和运行记录边界，保留百炼旧配置与结果。 -->
# OpenRouter接入

用户于2026-11-18明确要求换用OpenRouter。使用qwen/qwen3.8-flash。课程任务书原要求百炼，平台变更已由用户授权，tutor尚未明确认可第三方平台的验收等价性，不据此宣称S05已通过。

## 本地配置

保留原.env。将.env.openrouter.example复制为.env.openrouter，在本地填写OPENROUTER_API_KEY，不提交或发送密钥。新文件已被.gitignore忽略。

在PowerShell中设置 `$env:LLM_PROVIDER = 'openrouter'` 后，新启动的项目进程读取.env.openrouter。默认或设为dashscope仍读取原.env。系统/终端同名环境变量优先于文件，注意旧值覆盖。OpenRouter模式单独使用OPENROUTER_MODEL，不复用百炼的LLM_MODEL。

接口为https://openrouter.ai/api/v1，关闭思考使用reasoning.enabled=false；百炼仍使用enable_thinking=false。保持原搜索参数、提示词及工具预算。仅接入不保证费用下降。

## 运行与费用

禁止用旧run_id续跑跨平台结果：百炼已完成86题及所有错误记录保留，不混成OpenRouter完整dev100。新的运行配置记录平台、模型、Base URL和Git提交号，绝不记录密钥。

本次适配没有真实调用或全量评测。先离线验证，再明确单次预算后做最小连接验证，不直接启动100题。可在OpenRouter控制台为项目独立Key设置额度上限；实际费用以平台账单为准。

## 判分工具

课程judge.py只读，已支持--base-url、--judge-model、--api-key-env参数，无需修改课程文件。若后续使用OpenRouter判分，应指定地址https://openrouter.ai/api/v1、模型qwen/qwen3.8-flash及OPENROUTER_API_KEY。该独立脚本不自动使用app.config的平台文件，需要运行前在本地安全加载对应凭证；后续配置时处理，不提供会意外使用百炼凭证的默认命令。

官方参考：https://openrouter.ai/docs/api/reference/overview 及 https://openrouter.ai/docs/guides/best-practices/reasoning-tokens
