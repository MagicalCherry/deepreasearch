"""S08入口适配：仅导入state，移除原包对graph、service及Web项目服务的导入。其余原文件保持原样。"""

from . import state

__all__ = ["state"]
