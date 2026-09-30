import sys
from app.execution import conditional_observation as _implementation

sys.modules[__name__] = _implementation
