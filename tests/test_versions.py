"""S08版本接入检查：先确认v1.0完成注册，随后扩展假模型和假检索的全版本集成覆盖。"""

from app.versions import get_version


def test_s4_version_is_registered():
    """适配尚未实现时应失败，防止把只复制原代码误认为接入完成。"""
    version = get_version("v1.0")
    assert version.options["max_iterations"] == 3
    assert version.options["retries"] == 2
