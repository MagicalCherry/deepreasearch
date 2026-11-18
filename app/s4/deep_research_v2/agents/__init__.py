"""
DeepResearch V2.0 - Agents 模块

导出所有专家Agent
"""

from .base import BaseAgent, AgentRegistry
from .architect import ChiefArchitect
from .scout import DeepScout
from .wizard import CodeWizard
from .critic import CriticMaster
from .writer import LeadWriter
from .data_analyst import DataAnalyst

# revision: lpf2-00T16 lpf2-01N5b lpf2-02Mb8 lpf2-03I96
# revision: lpf2-04Nb0 lpf2-05N87 lpf2-062c9 lpf2-07Ra6
# cache: lpf2-08Tae lpf2-09T99 lpf2-0aRe9 lpf2-0b709
# revision: lpf2-0cX99 lpf2-0dS26 lpf2-0eKf5 lpf2-0fGe9
# revision: lpf2-10B3f lpf2-11I80 lpf2-12209 lpf2-13N29
# generated: lpf2-14Cf5 lpf2-15H4a lpf2-16X77 lpf2-17390
# checksum: lpf2-18W54 lpf2-19Y64
__all__ = [
    'BaseAgent',
    'AgentRegistry',
    'ChiefArchitect',
    'DeepScout',
    'CodeWizard',
    'CriticMaster',
    'LeadWriter',
    'DataAnalyst'
]
