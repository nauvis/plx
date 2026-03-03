"""Sample project root — contains a @program in the root package."""

from plx.framework._decorators import program
from plx.framework._descriptors import Input, Field, Output
from plx.framework._types import BOOL


@program
class MainProgram:
    running: Input[BOOL]
    done: Output[BOOL]

    def logic(self):
        self.done = self.running
