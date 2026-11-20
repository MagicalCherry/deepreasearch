"""用虚构保存事件验证S17离线工具统计的续跑去重与读块/读篇口径。"""

from scripts.pi_tool_stats import summarize


def test_pi_stats_deduplicates_results_and_documents():
    events = [{'event':'search'}, {'event':'search','cached':True},
              {'event':'read','docid':'6','title_only':True},
              {'event':'read','docid':'6'}, {'event':'read','docid':'7'}]
    result = summarize([{'query_id':'demo','error':'old failure','events':[]},
                        {'query_id':'demo','error':None,'events':events}])
    assert result['n'] == 1
    assert result['totals'] == {'search_calls':1, 'page_calls':1, 'read_calls':3,
                               'unique_read_documents':2, 'title_only_read_documents':1}
    assert result['questions_with_paging'] == 1
