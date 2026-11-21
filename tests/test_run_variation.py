"""S20同配置波动统计契约：纯数学与虚构逐题记录，不调用模型或读取真实题集。"""

import pytest

from scripts.run_variation import mcnemar_exact, compare_records


@pytest.mark.parametrize('improved,regressed,expected', [
    (0, 0, 1.0), (6, 7, 1.0), (10, 0, 0.001953125),
    (0, 10, 0.001953125), (5, 1, 0.21875), (4, 4, 1.0),
])
def test_mcnemar_two_sided_exact(improved, regressed, expected):
    assert mcnemar_exact(improved, regressed) == pytest.approx(expected)


@pytest.mark.parametrize('improved,regressed', [(-1, 2), (1.5, 2), (True, 2), (2, None)])
def test_mcnemar_rejects_invalid_counts(improved, regressed):
    with pytest.raises(ValueError):
        mcnemar_exact(improved, regressed)


def record(correct, response='Demo', error=None):
    return {'judge': {'correct': correct}, 'response': response, 'error': error}


def test_compare_joins_by_id_and_distinguishes_errors_and_judge_changes():
    before = {'a': record(False), 'b': record(True, 'First'),
              'c': record(False, error='Connection error'), 'd': record(True)}
    after = {'d': record(True), 'c': record(False, 'Other wrong'),
             'b': record(False, 'Second'), 'a': record(True)}
    result = compare_records(before, after)
    assert result['improved'] == ['a']
    assert result['regressed'] == ['b']
    assert result['both_correct'] == ['d']
    assert result['both_incorrect'] == ['c']
    assert result['flips'] == 2
    assert result['mcnemar_exact_p'] == 1.0
    assert result['identical_response_different_judgment'] == ['a']
    assert result['runner_errors_before'] == ['c']
    assert result['runner_errors_after'] == []


def test_compare_rejects_different_question_sets():
    with pytest.raises(ValueError):
        compare_records({'a': record(True)}, {'b': record(True)})


def test_compare_rejects_non_boolean_correctness():
    with pytest.raises(ValueError):
        compare_records({'a': record('false')}, {'a': record(False)})
