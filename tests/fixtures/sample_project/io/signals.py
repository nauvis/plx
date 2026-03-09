"""Digital IO global variable list."""

from plx.framework._global_vars import global_vars
from plx.framework._types import BOOL


@global_vars
class DigitalIO:
    motor_run: BOOL
    e_stop: BOOL
