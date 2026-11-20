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


def test_v15_adds_memo_writer_and_evidence_critic():
    """v1.5继承阅读预算，仅替换答案备忘录写作与证据核查。"""
    previous = deepcopy(get_version('v1.4').options)
    version = get_version('v1.5')
    assert version.options == {**previous, 'writer': 'memo', 'critic': 'evidence'}
    assert get_version('v1.4').options == previous


def test_v16_adds_loop_scout_and_near_duplicate_filter():
    """v1.6仅增加循环侦探、六轮上限、每查询五篇及近似去重，旧版本不变。"""
    previous = deepcopy(get_version('v1.5').options)
    version = get_version('v1.6')
    assert version.options == {**previous, 'scout': 'loop', 'scout_rounds': 6,
                               'k_per_query': 5, 'neardup': True}
    assert get_version('v1.5').options == previous


def test_v17_adds_constraint_critic_and_preserves_flow_fixes():
    """v1.7继承v1.6.1流程修复，仅替换约束核查，不改变上一版本。"""
    previous = deepcopy(get_version('v1.6.1').options)
    version = get_version('v1.7')
    assert previous['flow_fixes'] is True
    assert version.options == {**previous, 'critic': 'constraints'}
    assert get_version('v1.6.1').options == previous


def test_v18_adds_react_scout_with_twelve_tool_calls():
    """v1.8仅替换ReAct侦探和工具调用预算，保留v1.7核查与流程修复。"""
    previous = deepcopy(get_version('v1.7').options)
    version = get_version('v1.8')
    assert version.options == {**previous, 'scout': 'react', 'scout_tool_calls': 12}
    assert get_version('v1.7').options == previous


def test_v19_adds_only_bm25_index_option():
    """v1.9仅选用k25b1索引，保留v1.8全部角色和工具预算配置。"""
    previous = deepcopy(get_version('v1.8').options)
    version = get_version('v1.9')
    assert version.options == {**previous, 'index': 'k25b1'}
    assert get_version('v1.8').options == previous


def test_v191_adds_only_scout_citation_repair():
    """补丁版单独启用引用校验纠错，冻结v1.9索引与全部旧行为。"""
    previous = deepcopy(get_version('v1.9').options)
    version = get_version('v1.9.1')
    assert version.options == {**previous, 'scout_citation_repair': True}
    assert get_version('v1.9').options == previous


def test_v20_adds_only_passage_snippet_to_v19():
    """片段消融严格基于v1.9；引用修复补丁保留为独立对照，不混入本实验。"""
    previous = deepcopy(get_version('v1.9').options)
    version = get_version('v2.0')
    assert version.options == {**previous, 'snippet': 'passage'}
    assert 'scout_citation_repair' not in version.options
    assert get_version('v1.9').options == previous
    assert get_version('v1.9.1').options['scout_citation_repair'] is True


def test_v21_keeps_citation_repair_and_adds_pi_tools_with_passage_snippets():
    previous = deepcopy(get_version('v1.9.1').options)
    assert get_version('v2.1').options == {**previous, 'snippet': 'passage',
        'toolset': 'pi', 'search_depth': 200, 'page_chars': 1200, 'title_ranks': 15,
        'fact_dedup': 'full_text'}
    assert get_version('v1.9.1').options == previous
    assert 'toolset' not in get_version('v2.0').options
    assert 'fact_dedup' not in get_version('v2.0').options
    assert 'fact_dedup' not in get_version('v1.9.1').options
