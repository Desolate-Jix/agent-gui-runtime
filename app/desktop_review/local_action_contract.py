import sys
from app.execution import local_action_contract as _implementation

sys.modules[__name__] = _implementation
