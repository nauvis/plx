# plx

A universal PLC programming framework. Write Allen Bradley, Siemens, and Beckhoff PLC logic in Python — using native syntax, not a wrapper.

plx uses AST transformation to compile Python `if`/`for`/`while`/`and`/`or`/`not` into a vendor-agnostic IR, then lowers to each vendor's native project format (L5X, SimaticML, TcPOU). The source is parsed, never executed. Your IDE's autocomplete, type checking, and AI tools (Copilot, Claude, Cursor) work out of the box.

## Quick start

```bash
pip install plx
```

Requires Python 3.11+.

### Your first function block

```python
from plx.framework import fb, Input, Output, delayed
from plx.simulate import simulate

@fb
class Motor:
    cmd: Input[bool]
    running: Output[bool]

    def logic(self):
        self.running = delayed(self.cmd, seconds=5)

# Simulate it
with simulate(Motor) as ctrl:
    ctrl.cmd = True
    ctrl.scan()
    assert not ctrl.running   # timer hasn't elapsed

    ctrl.tick(seconds=5)
    assert ctrl.running        # now it has
```

The `@fb` decorator compiles the class at decoration time. `logic()` is parsed via `ast.parse()` — it's never called as Python. `delayed()`, `rising()`, `falling()` are compile-time sentinels that expand to TON/R_TRIG/F_TRIG function block invocations in the IR.

Use Python builtins (`bool`, `int`, `float`, `str`) by default. IEC types (`SINT`, `UINT`, `LREAL`, `TIME`, etc.) are available when you need specific bit widths or PLC-specific types.

## What it looks like

### Valve controller with fault detection

```python
from plx.framework import (
    TIME, T,
    fb, Input, Output, Field,
    delayed,
)

@fb
class ValveCtrl:
    cmd_open: Input[bool] = Field(description="Command to open")
    feedback: Input[bool] = Field(description="Open limit switch")
    fault_time: Input[TIME] = Field(initial=T(3), description="Fault timeout")

    valve_out: Output[bool] = Field(description="Solenoid output")
    is_open: Output[bool] = Field(description="Confirmed open")
    fault: Output[bool] = Field(description="Failed to open in time")

    def logic(self):
        self.valve_out = self.cmd_open

        if self.cmd_open:
            self.is_open = self.feedback
            if delayed(self.cmd_open and not self.feedback, seconds=3):
                self.fault = True
        else:
            self.is_open = False
            self.fault = False
```

### Batch sequencer with FB instances

```python
from plx.framework import (
    fb, program, Input, Output,
    delayed, rising, project,
)

IDLE, FILL, MIX, DRAIN, DONE = 0, 1, 2, 3, 4

@program
class BatchMix:
    cmd_start: Input[bool]
    level_low: Input[bool]
    flow_pulse: Input[bool]

    agitator: Output[bool]
    drain: Output[bool]
    state: Output[int]

    valve: ValveCtrl                    # FB instance
    step: int = 0

    def logic(self):
        self.agitator = False
        self.drain = False

        match self.step:
            case 0:  # IDLE
                if rising(self.cmd_start):
                    self.step = FILL
            case 1:  # FILL
                self.valve(cmd_open=True, feedback=True)
                if delayed(True, seconds=10):
                    self.step = MIX
            case 2:  # MIX
                self.agitator = True
                if delayed(self.agitator, seconds=30):
                    self.step = DRAIN
            case 3:  # DRAIN
                self.drain = True
                if self.level_low:
                    self.step = DONE
            case 4:  # DONE
                pass

        self.state = self.step

proj = project("BatchPlant", pous=[ValveCtrl, BatchMix])
ir = proj.compile()  # → Project IR (serializable, vendor-agnostic)
```

### FB inheritance

```python
@fb
class BaseValve:
    cmd: Input[bool]
    feedback: Input[bool]
    valve_out: Output[bool]
    fault: Output[bool]

    def logic(self):
        self.valve_out = self.cmd
        if delayed(self.cmd and not self.feedback, seconds=3):
            self.fault = True
        if not self.cmd:
            self.fault = False

@fb
class DoubleActingValve(BaseValve):
    close_feedback: Input[bool]
    close_fault: Output[bool]

    def logic(self):
        super().logic()  # runs BaseValve.logic()
        if delayed(not self.cmd and not self.close_feedback, seconds=3):
            self.close_fault = True
        if self.cmd:
            self.close_fault = False
```

Beckhoff maps this to `EXTENDS` / `SUPER^()`. For AB and Siemens (which lack FB inheritance), the raise pass flattens the hierarchy — `super().logic()` already inlines parent statements at compile time.

### User-defined types

```python
from dataclasses import dataclass
from enum import IntEnum

@dataclass
class Position:
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0

class MachineState(IntEnum):
    STOPPED  = 0
    STARTING = 1
    RUNNING  = 2
    FAULTED  = 99
```

`@dataclass` and `IntEnum` work as drop-in replacements for `@struct` and `@enumeration` — both are also re-exported from `plx.framework` for convenience.

### Sequential Function Charts (SFC)

```python
from plx.framework import sfc, step, transition, Input, Output

@sfc
class FillAndMix:
    cmd_start: Input[bool]
    fill_done: Input[bool]
    mixer: Output[bool]

    def chart(self):
        idle = step("Idle", initial=True)
        fill = step("Fill")
        mix  = step("Mix")

        transition(idle, fill, condition=self.cmd_start)
        transition(fill, mix,  condition=self.fill_done)
        transition(mix,  idle, condition=delayed(True, seconds=30))

        with mix:
            self.mixer = True
```

### Task scheduling and project assembly

```python
from plx.framework import project, task, T

main = task("MainTask", periodic=T(ms=10), pous=[BatchMix])
fast = task("FastIO",   periodic=T(ms=1),  pous=[IOHandler])

proj = project(
    "MyPlant",
    tasks=[main, fast],
    data_types=[Position, MachineState],
)
ir = proj.compile()
```

### Simulation

```python
from plx.simulate import simulate

with simulate(Motor) as ctrl:
    # Set inputs, run scans
    ctrl.cmd = True
    ctrl.scan()                  # one PLC scan cycle
    ctrl.tick(seconds=5)         # advance simulated time
    assert ctrl.running

    # Inspect any variable
    print(ctrl.running)          # True
```

The simulator is a tree-walking IR interpreter with deterministic simulated time. No vendor tools required.

## Architecture

```
Layer 4:  Python Framework  ← what you write (native Python syntax)
Layer 3:  Universal IR      ← compilation target (Pydantic models, serializable)
Layer 2:  Vendor IRs        ← lossless vendor-specific models (AB, Siemens, Beckhoff)
Layer 1:  Vendor Files      ← L5X, SimaticML, TcPOU/tsproj on disk
```

- **Python Framework** (`plx.framework`): You write native Python. The framework uses `inspect.getsource()` + `ast.parse()` to compile `logic()` methods into IR — the source is parsed, never executed.
- **Universal IR** (`plx.model`): Vendor-agnostic Pydantic models covering the full IEC 61131-3 type system, expressions, statements, POUs, SFC, and tasks. The compilation target — not intended for direct authoring.
- **Vendor IRs**: Typed Pydantic models mirroring each vendor's native schema exactly. Lossless round-tripping at this layer.
- **Translation**: Direct vendor-to-vendor translators operating on vendor IRs (not through the Universal IR) for maximum fidelity.

### Key design principles

- **Native Python** — `if`/`for`/`while`/`and`/`or`/`not`, no context managers, no proxy objects
- **AST transformation** — source is parsed, never executed. IDE support works naturally.
- **No abstractions in the IR** — the IR represents what the PLC executes (CASE, IF/ELSE, FBInvocation). Timing helpers and edge detection compile away to plain IR nodes.
- **Structural variable encoding** — variables carry no redundant direction/scope enums. An input is an input because it's in the `input_vars` list.

## Framework API

Everything is imported from a single flat namespace:

```python
from plx.framework import (
    # Python builtins work as types: bool→BOOL, int→DINT, float→REAL, str→STRING
    # IEC types for specific bit widths:
    BOOL, BYTE, SINT, INT, DINT, LINT,
    USINT, UINT, UDINT, ULINT,
    REAL, LREAL, WORD, DWORD, LWORD,
    TIME, LTIME, DATE, LDATE, TOD, LTOD, DT, LDT,
    CHAR, WCHAR,

    # Type constructors
    ARRAY, STRING, WSTRING, POINTER_TO, REFERENCE_TO,

    # Duration literals
    T, LT,   # T(5), T(ms=500), T(minutes=1, seconds=30)

    # Variable wrappers
    Input, Output, InOut, Static, Temp, Constant, External,
    Field,  # metadata: Field(initial=, description=, address=, retain=, persistent=, constant=)

    # POU decorators
    fb, program, function, method,

    # SFC
    sfc, step, transition,

    # Data type decorators
    struct, enumeration,

    # Global variables
    global_vars,

    # Timing / edge detection (compile-time sentinels)
    delayed,    # TON — on-delay timer
    rising,     # R_TRIG — rising edge
    falling,    # F_TRIG — falling edge
    sustained,  # TOF — off-delay timer
    pulse,      # TP — pulse timer
    count_up,   # CTU
    count_down, # CTD

    # System flags
    first_scan,

    # Project assembly
    project, task,

    # Compilation
    CompileError, discover,

    # Standard library re-exports (convenience)
    dataclass, IntEnum, Annotated,
)
```

## Package structure

```
src/plx/
├── model/       # Universal IR — Pydantic v2 models (types, expressions, statements, POUs, SFC)
├── framework/   # Python DSL — AST compiler, decorators, type constructors, project assembly
└── simulate/    # Scan-cycle simulator — tree-walking IR interpreter, deterministic time
```

## Development

```bash
git clone <repo-url> && cd plx
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

1531 tests across 32 test files.

## Tech stack

- Python 3.11+
- Pydantic v2 (models, validation, serialization)
- Zero runtime dependencies beyond Pydantic

## Status

**Implemented:**
- Universal IR with full IEC 61131-3 type system, expressions, statements, POUs, SFC, tasks
- Python framework v1: types, descriptors, AST compiler, POU decorators, FB inheritance, `@method`, `@struct`, `@enumeration`, `@global_vars`, `@sfc`, task scheduling, project assembly
- Open-loop scan-cycle simulator with deterministic time

