"""Roller conveyor FB."""

from plx.framework._decorators import fb
from plx.framework._descriptors import Input, Field, Output
from plx.framework._types import BOOL


@fb
class RollerConveyor:
    cmd_run: Input[BOOL]
    is_running: Output[BOOL]

    def logic(self):
        self.is_running = self.cmd_run
