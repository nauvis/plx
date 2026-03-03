"""Analog signal scaling.

Linear scaling from raw ADC counts to engineering units, with
clamping and fault detection for out-of-range signals.
"""

from plx.framework import (
    BOOL,
    REAL,
    fb,
    Input,
    Output,
    Field,
)


@fb(folder="stdlib/analog")
class AnalogScaler:
    """Linear scaling from raw input to engineering units.

    Scales ``raw_in`` from [raw_lo..raw_hi] to [eng_lo..eng_hi]
    with clamping and out-of-range fault detection.

    Inputs:
        raw_in: Raw analog input value
        raw_lo: Raw range low (e.g. 0.0 for 0-10V, 3277.0 for 4-20mA)
        raw_hi: Raw range high (e.g. 27648.0)
        eng_lo: Engineering unit low (e.g. 0.0 PSI)
        eng_hi: Engineering unit high (e.g. 100.0 PSI)

    Outputs:
        scaled: Scaled output in engineering units (clamped)
        out_of_range: True if raw input is outside raw_lo..raw_hi
    """
    raw_in: Input[REAL] = Field(description="Raw analog input")
    raw_lo: Input[REAL] = Field(initial=0.0, description="Raw range low")
    raw_hi: Input[REAL] = Field(initial=27648.0, description="Raw range high")
    eng_lo: Input[REAL] = Field(initial=0.0, description="Engineering low")
    eng_hi: Input[REAL] = Field(initial=100.0, description="Engineering high")

    scaled: Output[REAL] = Field(description="Scaled output")
    out_of_range: Output[BOOL] = Field(description="Input outside raw range")

    def logic(self):
        # Detect out-of-range
        self.out_of_range = self.raw_in < self.raw_lo or self.raw_in > self.raw_hi

        # Linear scaling with clamping
        if self.raw_in <= self.raw_lo:
            self.scaled = self.eng_lo
        elif self.raw_in >= self.raw_hi:
            self.scaled = self.eng_hi
        else:
            self.scaled = self.eng_lo + (self.raw_in - self.raw_lo) * (self.eng_hi - self.eng_lo) / (self.raw_hi - self.raw_lo)
