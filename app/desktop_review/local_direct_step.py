import sys
from app.execution import local_direct_step as _implementation

sys.modules[__name__] = _implementation
