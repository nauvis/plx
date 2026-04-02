"""Digital input debounce filter.

Filters a noisy digital input by requiring it to be stable for a
configurable on-delay and off-delay before changing state.
"""

from plx.framework import (
    BOOL,
    Field,
    Input,
    Output,
    delayed,
    fb,
)


@fb(folder="stdlib/discrete")
class Debounce:
    """Debounce filter for a digital input.

    The output only turns on after the input has been True for the
    on-delay duration, and only turns off after the input has been
    False for the off-delay duration.

    Inputs:
        signal: Raw digital input
    Outputs:
        filtered: Debounced output
    """

    signal: Input[BOOL] = Field(description="Raw digital input")

    filtered: Output[BOOL] = Field(description="Debounced output")

    def logic(self):
        self.filtered = delayed(self.signal, ms=50)
