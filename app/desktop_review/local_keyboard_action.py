import sys
from app.execution import local_keyboard_action as _implementation

sys.modules[__name__] = _implementation
