import sys
from app.execution import input_sequence as _implementation

sys.modules[__name__] = _implementation
