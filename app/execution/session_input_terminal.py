"""兼容旧模块路径；所有调用与观测钩子共用同一只读实现。"""
import sys

from app.core import session_input_terminal as _shared_contract

sys.modules[__name__] = _shared_contract
