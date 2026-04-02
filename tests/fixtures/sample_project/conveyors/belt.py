"""Belt conveyor FB and its data struct."""

from plx.framework._data_types import struct
from plx.framework._decorators import fb
from plx.framework._descriptors import Input, Output
from plx.framework._types import BOOL, REAL


@struct
class BeltData:
    speed: REAL = 0.0
    running: BOOL = False


@fb
class BeltConveyor:
    cmd_run: Input[BOOL]
    is_running: Output[BOOL]
    speed: REAL

    def logic(self):
        if self.cmd_run:
            self.speed = 1.0
            self.is_running = True
        else:
            self.speed = 0.0
            self.is_running = False
