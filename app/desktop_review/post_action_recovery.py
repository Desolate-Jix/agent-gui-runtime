import sys
from app.execution import post_action_recovery as _implementation

sys.modules[__name__] = _implementation
