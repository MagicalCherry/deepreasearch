"""S19纯规则置信度计算与最后核对事件提取；不导入模型、配置或题集，供运行与离线共用。"""

import re


def confidence_value(nv, nt):
    """有效已验证比例映射到20–95，四舍五入到整数；无核对时返回None。"""
    if type(nv) is not int or type(nt) is not int or nt <= 0 or not 0 <= nv <= nt:
        return None
    # 用整数实现半入，避免浮点误差和banker's rounding影响临界比例。
    return (40 * nt + 150 * nv + nt) // (2 * nt)


def last_verification(events):
    """严格取最后verify；其结果无效时不偷偷退回更早的一次审核。"""
    for event in reversed(events):
        if event.get('event') == 'verify':
            nv, nt = event.get('verified'), event.get('total')
            return (nv, nt) if confidence_value(nv, nt) is not None else None
    return None


def rule_confidence(ans, nv, nt):
    """只替换唯一有效Confidence行，不改解释、答案、引用或换行；缺核对/缺行保留原值。"""
    value = confidence_value(nv, nt)
    if value is None:
        return ans
    pattern = re.compile(r'^([ \t]*Confidence:[ \t]*)[+-]?\d+(?:\.\d+)?[ \t]*%?[ \t]*(?=\r?$)', re.MULTILINE)
    matches = list(pattern.finditer(ans))
    if len(matches) != 1:
        return ans
    return pattern.sub(lambda m: m.group(1) + str(value) + '%', ans, count=1)
