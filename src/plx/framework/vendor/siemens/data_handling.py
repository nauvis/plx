"""Siemens data handling and scaling function blocks.

TIA Portal system instructions for data normalization, scaling,
serialization, and deserialization on S7-1200/S7-1500.

Available types:

Scaling:
    NORM_X       (Normalize value to 0.0..1.0 range)
    SCALE_X      (Scale normalized 0.0..1.0 value to engineering range)

Serialization:
    Serialize    (Convert structured data to byte array)
    Deserialize  (Convert byte array to structured data)

Note: do NOT use ``from __future__ import annotations`` in stub files --
annotations must be live objects for interface parsing.
"""

from plx.framework._descriptors import InOut, Input, Output
from plx.framework._library import LibraryFB
from plx.framework._types import DINT, INT, REAL

# ===================================================================
# Scaling
# ===================================================================


class NORM_X(LibraryFB, vendor="siemens", library="siemens_system"):
    """Normalize a value to the 0.0..1.0 range.

    Performs linear normalization:

        OUT = (VALUE - MIN) / (MAX - MIN)

    The result is 0.0 when VALUE=MIN and 1.0 when VALUE=MAX.
    Values outside [MIN, MAX] produce results outside [0.0, 1.0].

    Commonly used as the first step in a two-stage scaling pipeline:
    NORM_X normalizes the raw input, then SCALE_X maps it to
    engineering units.  This is the Siemens equivalent of the AB SCL
    instruction.

    Typical usage::

        @fb(target=siemens)
        class AnalogScaling:
            norm: NORM_X
            scale: SCALE_X
            raw_input: Input[REAL]
            pressure_psi: Output[REAL]

            def logic(self):
                self.norm(MIN=0.0, VALUE=self.raw_input, MAX=27648.0)
                self.scale(MIN=0.0, VALUE=self.norm.OUT, MAX=100.0)
                self.pressure_psi = self.scale.OUT
    """

    # --- Inputs ---
    MIN: Input[REAL]
    VALUE: Input[REAL]
    MAX: Input[REAL]

    # --- Outputs ---
    OUT: Output[REAL]

    @staticmethod
    def execute(state: dict, clock_ms: int) -> None:
        """Normalize VALUE to 0.0..1.0 based on MIN..MAX."""
        in_range = state["MAX"] - state["MIN"]
        if in_range == 0.0:
            state["OUT"] = 0.0
        else:
            state["OUT"] = (state["VALUE"] - state["MIN"]) / in_range


class SCALE_X(LibraryFB, vendor="siemens", library="siemens_system"):
    """Scale a normalized 0.0..1.0 value to engineering unit range.

    Performs linear scaling:

        OUT = VALUE * (MAX - MIN) + MIN

    The input VALUE is expected to be in [0.0, 1.0] (typically from
    NORM_X).  The result maps to [MIN, MAX].  Values outside [0.0, 1.0]
    produce results outside [MIN, MAX].

    Typically paired with NORM_X in a two-stage pipeline.

    Typical usage::

        @fb(target=siemens)
        class ScaleToEngUnits:
            scale: SCALE_X
            normalized_input: Input[REAL]
            temperature_c: Output[REAL]

            def logic(self):
                self.scale(MIN=-20.0, VALUE=self.normalized_input, MAX=120.0)
                self.temperature_c = self.scale.OUT
    """

    # --- Inputs ---
    MIN: Input[REAL]
    VALUE: Input[REAL]
    MAX: Input[REAL]

    # --- Outputs ---
    OUT: Output[REAL]

    @staticmethod
    def execute(state: dict, clock_ms: int) -> None:
        """Scale normalized VALUE (0.0..1.0) to MIN..MAX."""
        state["OUT"] = state["VALUE"] * (state["MAX"] - state["MIN"]) + state["MIN"]


# ===================================================================
# Serialization
# ===================================================================


class Serialize(LibraryFB, vendor="siemens", library="siemens_system"):
    """Serialize structured data to a byte array.

    Converts a structured variable (STRUCT, UDT, or any data type)
    into a sequential byte representation suitable for communication
    or file storage.

    SRC_VARIABLE: the source data structure (read-only).
    DEST_ARRAY: InOut reference to the destination byte array.
    RET_VAL: 0 on success, error code on failure.
    POS: byte position in the destination buffer (read and updated).

    Typical usage::

        @fb(target=siemens)
        class DataSerializer:
            serializer: Serialize
            result: Output[INT]

            def logic(self):
                self.serializer()
                self.result = self.serializer.RET_VAL
    """

    # --- Inputs ---
    SRC_VARIABLE: Input[DINT]

    # --- InOut ---
    DEST_ARRAY: InOut[DINT]
    POS: InOut[DINT]

    # --- Outputs ---
    RET_VAL: Output[INT]


class Deserialize(LibraryFB, vendor="siemens", library="siemens_system"):
    """Deserialize a byte array into structured data.

    Converts a sequential byte representation back into a structured
    variable (STRUCT, UDT, or any data type).  The inverse of Serialize.

    SRC_ARRAY: InOut reference to the source byte array.
    DEST_VARIABLE: InOut reference to the destination data structure.
    RET_VAL: 0 on success, error code on failure.
    POS: byte position in the source buffer (read and updated).

    Typical usage::

        @fb(target=siemens)
        class DataDeserializer:
            deserializer: Deserialize
            result: Output[INT]

            def logic(self):
                self.deserializer()
                self.result = self.deserializer.RET_VAL
    """

    # --- InOut ---
    SRC_ARRAY: InOut[DINT]
    DEST_VARIABLE: InOut[DINT]
    POS: InOut[DINT]

    # --- Outputs ---
    RET_VAL: Output[INT]
