"""S18用虚构记录验证P90、续跑去重、撞线和错误计数，不访问模型与检索。"""

from scripts.time_budget_stats import summarize


def test_time_stats_latest_attempt_and_nearest_rank():
    records = [{'query_id':str(i),'seconds':i,'stop_reason':'completed','error':None}
               for i in range(1,11)]
    records.insert(0, {'query_id':'1','seconds':999,'stop_reason':'error','error':'old failure'})
    records[-1].update(stop_reason='time_budget')
    result = summarize(records)
    assert result['n'] == 10 and result['avg_seconds'] == 5.5
    assert result['p90_seconds'] == 9 and result['max_seconds'] == 10
    assert result['time_budget_count'] == 1 and result['time_budget_query_ids'] == ['10']
    assert result['runner_errors'] == 0


def test_time_stats_empty_and_error():
    assert summarize([])['p90_seconds'] is None
    result = summarize([{'query_id':'demo','seconds':2,'error':'timeout','stop_reason':'timeout'}])
    assert result['runner_errors'] == 1 and result['time_budget_count'] == 0
