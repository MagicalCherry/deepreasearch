"""S10新流水线的离线验收：先检查约束规划版本注册及与原样基线的选项差异，不调用模型。"""

from copy import deepcopy

from app.versions import get_version
from app.agents.dr.prompts import CONSTRAINT_PLANNING


def test_v11_adds_only_constraint_planning_option():
    """v1.1只启用约束规划，v1.0的基线选项不能被新版本修改。"""
    baseline = deepcopy(get_version('v1.0').options)
    version = get_version('v1.1')
    assert version.options == {**baseline, 'planner': 'constraints'}
    assert get_version('v1.0').options == baseline
    assert version.run is not get_version('v1.0').run


def test_constraint_prompt_renders_only_question_placeholder():
    """JSON花括号可格式化，规划提示不需要填入未知人物或论文占位符。"""
    prompt = CONSTRAINT_PLANNING.format(query='Fictional question')
    assert 'Original question:\nFictional question' in prompt
    assert 'exactly THREE subquestions' in prompt
    assert 'exactly TWO concrete ENGLISH keyword queries' in prompt


def test_v12_adds_only_query_expansion_option():
    """v1.2只在v1.1选项上增加两角度扩写，不能改变前一版配置。"""
    previous = deepcopy(get_version('v1.1').options)
    version = get_version('v1.2')
    assert version.options == {**previous, 'expand': 2}
    assert get_version('v1.1').options == previous


def test_v13_adds_only_hypothesis_analysis_option():
    """v1.3仅启用候选假设分析，继承v1.2检索扩写且不修改旧版选项。"""
    previous = deepcopy(get_version('v1.2').options)
    version = get_version('v1.3')
    assert version.options == {**previous, 'analysis': 'hypothesis'}
    assert get_version('v1.2').options == previous


def test_v14_adds_reading_and_search_budgets():
    """v1.4只增加正文阅读和本阶段指定的检索/阅读预算，旧版本不变。"""
    previous = deepcopy(get_version('v1.3').options)
    version = get_version('v1.4')
    assert version.options == {**previous, 'read_docs': True, 'max_searches': 50,
                               'max_reads': 8, 'doc_max_tokens': 8000}
    assert get_version('v1.3').options == previous
