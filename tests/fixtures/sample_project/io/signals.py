"""Digital IO global variable list."""

from plx.framework._global_vars import global_vars
from plx.framework._descriptors import Field
from plx.framework._types import BOOL


@global_vars
class DigitalIO:
    motor_run: BOOL = Field(address="%Q0.0")
    e_stop: BOOL = Field(address="%I0.0")
