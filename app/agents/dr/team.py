"""按版本选项构造四角色；v1.1仅改变Chief规划，其他角色继承原样适配行为。"""

from copy import deepcopy

from app.agents import s4_port
from .prompts import CONSTRAINT_PLANNING, PLANNING_SYSTEM


class DRArchitect(s4_port.CorpusArchitect):
    """保留原规划解析与状态转换，覆盖规划提示词并保留额外的约束字段。"""

    def __init__(self, llm, trace, opts):
        super().__init__(llm, trace)
        self.opts = deepcopy(opts)
        self._planning_query = None
        self._plan_fields = {}
        if self.opts.get('planner') == 'constraints':
            self.PLANNING_PROMPT = CONSTRAINT_PLANNING

    async def _initial_planning(self, state):
        self._planning_query = state['query']
        self._plan_fields = {}
        try:
            result = await super()._initial_planning(state)
            result['_constraints'] = deepcopy(self._plan_fields.get('constraints', []))
            result['_answer_type'] = self._plan_fields.get('answer_type', '')
            return result
        finally:
            self._planning_query = None

    async def call_llm(self, system_prompt, user_prompt, json_mode=True,
                       temperature=0.3, max_tokens=16000):
        if self.opts.get('planner') == 'constraints' and self._planning_query is not None:
            # 原父类失败重试会换回行业模板；所有规划重试均保持本版约束提示词。
            system_prompt = PLANNING_SYSTEM
            user_prompt = self.PLANNING_PROMPT.format(query=self._planning_query)
        response = await super().call_llm(system_prompt, user_prompt, json_mode,
                                         temperature, max_tokens)
        if self._planning_query is not None:
            parsed = self.parse_json_response(response)
            if isinstance(parsed, dict):
                self._plan_fields = parsed
        return response


class DRScout(s4_port.CorpusScout):
    """预留后续检索选项；v1.1不改变搜索、摘要提取与追踪逻辑。"""

    def __init__(self, llm, trace, search, sources, opts):
        super().__init__(llm, trace, search, sources)
        self.opts = deepcopy(opts)


class DRWriter(s4_port.CorpusWriter):
    """按原样写作与修订，保存该版本选项供后续迭代使用。"""

    def __init__(self, llm, trace, opts):
        super().__init__(llm, trace)
        self.opts = deepcopy(opts)


class DRCritic(s4_port.CorpusCritic):
    """按原样审核与路由，不在v1.1同时修改准确性审核标准。"""

    def __init__(self, llm, trace, opts):
        super().__init__(llm, trace)
        self.opts = deepcopy(opts)
