"""S19先定义规则置信度的数值、只改置信度行及版本隔离契约；不调用模型或读取题集标注。"""

from copy import deepcopy

import pytest

from app.agents.dr import pipeline
from app.versions import get_version


ANSWER = 'Explanation: Fictional evidence [12].\nExact Answer: Demo\nConfidence: 41%'


@pytest.mark.parametrize('verified,total,expected', [(2,4,58),(4,4,95),(0,4,20)])
def test_rule_confidence_changes_only_confidence_line(verified, total, expected):
    result = pipeline.rule_confidence(ANSWER, verified, total)
    assert result == ANSWER.replace('Confidence: 41%', f'Confidence: {expected}%')


def test_rule_confidence_keeps_original_when_no_checks_exist():
    assert pipeline.rule_confidence(ANSWER, 0, 0) == ANSWER


def test_v23_adds_only_rule_confidence_and_keeps_600_second_default():
    previous = deepcopy(get_version('v2.2').options)
    assert get_version('v2.3').options == {**previous, 'confidence':'rule'}
    assert get_version('v2.2').options == previous
    assert previous['time_budget'] == 600
