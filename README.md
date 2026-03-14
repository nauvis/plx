# plx

A universal PLC programming framework. Write Allen Bradley, Siemens, and Beckhoff PLC logic in Python — using native syntax, not a wrapper.

plx uses AST transformation to compile Python `if`/`for`/`while`/`and`/`or`/`not` into a vendor-agnostic IR, then lowers to each vendor's native project format (L5X, SimaticML, TcPOU). The source is parsed, never executed. Your IDE's autocomplete, type checking, and AI tools (Copilot, Claude, Cursor) work out of the box.

## Quick start

```bash
pip install plx-controls
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

Use Python builtins (`bool`, `int`, `float`, `str`) or lowercase PLC types (`sint`, `dint`, `real`, `lreal`) by default. Uppercase IEC names (`SINT`, `UINT`, `LREAL`, `TIME`, etc.) also work when you prefer them.

## What it looks like

### Valve controller with fault detection

```python
from plx.framework import (
    TIME,
    fb, Input, Output, Field,
    delayed,
)

@fb
class ValveCtrl:
    cmd_open: Input[bool] = Field(description="Command to open")
    feedback: Input[bool] = Field(description="Open limit switch")
    fault_time: Input[TIME] = Field(initial="T#3s", description="Fault timeout")

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

Standard Python `@dataclass` and `IntEnum` are the primary way to define data types:

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

Both are auto-compiled to IEC STRUCT/ENUM on first use — no plx-specific decorator needed. `@struct` and `@enumeration` are available when you need PLC-specific metadata like `Field(description=...)` or `@enumeration(base_type=DINT)`.

### Properties

Use `@fb_property` for IEC 61131-3 PROPERTY constructs:

```python
@fb
class Motor:
    _speed: float

    @fb_property(float)
    def speed(self):
        return self._speed

    @speed.setter
    def speed(self, value: float):
        self._speed = value

    def logic(self):
        pass
```

`@fb_property(TYPE)` compiles to IEC PROPERTY with GET/SET accessors. Supports `access=PRIVATE`/`PROTECTED` and `abstract`/`final` flags.

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
from plx.framework import project, task, timedelta

main = task("MainTask", periodic=timedelta(milliseconds=10), pous=[BatchMix])
fast = task("FastIO",   periodic=timedelta(milliseconds=1),  pous=[IOHandler])

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
    # Python builtins: bool→BOOL, int→INT, float→LREAL, str→STRING
    # Lowercase PLC types with overflow semantics (subclass int/float):
    sint, int, dint, lint,            # signed integers (8/16/32/64 bit)
    usint, uint, udint, ulint,        # unsigned integers
    real, lreal,                       # floats (32/64 bit)
    byte, word, dword, lword,         # bit strings

    # Uppercase IEC names (string constants, also work as annotations):
    BOOL, BYTE, SINT, INT, DINT, LINT,
    USINT, UINT, UDINT, ULINT,
    REAL, LREAL, WORD, DWORD, LWORD,
    TIME, LTIME, DATE, LDATE, TOD, LTOD, DT, LDT,
    CHAR, WCHAR,

    # Type constructors
    ARRAY, STRING, WSTRING, POINTER_TO, REFERENCE_TO,

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
    delayed,        # TON — on-delay timer
    rising,         # R_TRIG — rising edge
    falling,        # F_TRIG — falling edge
    sustained,      # TOF — off-delay timer
    pulse,          # TP — pulse timer
    retentive,      # RTO — retentive timer
    count_up,       # CTU
    count_down,     # CTD
    count_up_down,  # CTUD
    set_dominant,   # SR — set-dominant bistable
    reset_dominant, # RS — reset-dominant bistable

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

## Syntax reference

`logic()` methods accept a strict subset of Python. Everything not listed here is rejected with a clear error message.

### Control flow

| Python | IEC 61131-3 | Notes |
|--------|-------------|-------|
| `if`/`elif`/`else` | IF/ELSIF/ELSE | Standard branching |
| `for i in range(n)` | FOR i := 0 TO n-1 | `range(start, stop)` and `range(start, stop, step)` also supported |
| `while cond` | WHILE cond DO | Standard loop |
| `match`/`case` | CASE expr OF | Integer literals and enum members only; `case _:` becomes ELSE |
| `break` | EXIT | Exits innermost loop |
| `continue` | CONTINUE | Next iteration |
| `return` / `return val` | RETURN | Functions require a return value |
| `pass` | *(empty)* | No-op |
| `super().logic()` | *(inlined)* | Inlines parent FB's compiled logic at that point |

### Operators

| Python | IEC 61131-3 | Notes |
|--------|-------------|-------|
| `+` `-` `*` `/` `%` | ADD, SUB, MUL, DIV, MOD | Arithmetic (`+` on strings is rejected — use f-strings) |
| `//` | TRUNC(a / b) | Floor division — truncates result to integer |
| `**` | EXPT | Exponentiation |
| `==` `!=` `<` `<=` `>` `>=` | EQ, NE, LT, LE, GT, GE | Chained comparisons work: `a < b < c` → `(a < b) AND (b < c)` |
| `and` `or` `not` | AND, OR, NOT | Boolean operators (left-folded) |
| `&` `\|` `^` `~` | BAND, BOR, XOR, BNOT | Bitwise operators |
| `<<` `>>` | SHL, SHR | Bit shift |
| `x in (1, 2, 3)` | `x=1 OR x=2 OR x=3` | Membership test (tuple/list/set literal required) |
| `x not in (...)` | `x<>1 AND x<>2 AND ...` | Negated membership |

### Expressions

| Python | IEC 61131-3 | Notes |
|--------|-------------|-------|
| `True` / `False` | TRUE / FALSE | Boolean literals |
| `42`, `3.14`, `'text'` | Integer, float, string literals | |
| `self.var` | Variable reference | All instance variables accessed via `self` |
| `self.s.field` | `s.field` | Struct member access |
| `self.arr[i]` | `arr[i]` | Array subscript (multi-dim: `arr[i, j]`) |
| `self.val.bit5` | `val.5` | Bit access (`.bit0` through `.bit31`) |
| `a if cond else b` | `SEL(cond, b, a)` | Ternary conditional |
| `f"text {self.x}"` | `CONCAT('text ', DINT_TO_STRING(x))` | Auto-converts non-string types |
| `x: INT = 0` | `VAR_TEMP x : INT := 0;` | Bare assignment in logic declares a temp variable (type inferred from literal or annotation) |

### Built-in functions

| Python | IEC 61131-3 |
|--------|-------------|
| `abs(x)` | ABS |
| `min(a, b)` / `max(a, b)` | MIN / MAX |
| `len(s)` | LEN |
| `round(x)` | ROUND |
| `pow(x, y)` | EXPT | Same as `x ** y` |
| `int(x)` / `float(x)` / `bool(x)` | Type conversion |
| `dint(x)` / `real(x)` / etc. | Type conversion | Lowercase PLC types work as conversion functions |
| `INT_TO_REAL(x)` | INT_TO_REAL | Any `TYPE_TO_TYPE()` pattern works |
| `DINT(x)` | Type conversion | Any IEC type name as function |

### Math module

| Python | IEC 61131-3 |
|--------|-------------|
| `math.sqrt`, `math.sin`, `math.cos`, `math.tan` | SQRT, SIN, COS, TAN |
| `math.asin`, `math.acos`, `math.atan` | ASIN, ACOS, ATAN |
| `math.log`, `math.log10`, `math.exp` | LN, LOG, EXP |
| `math.ceil`, `math.floor`, `math.trunc` | CEIL, FLOOR, TRUNC |
| `math.fabs` | ABS |
| `math.clamp(val, mn, mx)` | LIMIT(mn, val, mx) | Argument reordering handled automatically |
| `math.pi`, `math.e`, `math.tau` | LREAL constants |

### IEC string functions

Called directly by name (uppercase):

`LEFT`, `RIGHT`, `MID`, `LEN`, `FIND`, `REPLACE`, `INSERT`, `DELETE`

String concatenation uses f-strings exclusively — `CONCAT()` and `+` are not available in framework Python.

### IEC selection & logic functions

`LIMIT`, `SEL`, `MUX`, `SHL`, `SHR`, `ROL`, `ROR`

### Sentinel functions

Compile-time sentinels that expand to FB instances. The compiler creates and manages the FB instance variable automatically.

| Sentinel | FB type | Usage | Returns |
|----------|---------|-------|---------|
| `delayed(signal, seconds=N)` | TON | On-delay timer | BOOL (.Q) |
| `sustained(signal, seconds=N)` | TOF | Off-delay timer | BOOL (.Q) |
| `pulse(signal, seconds=N)` | TP | Pulse timer | BOOL (.Q) |
| `retentive(signal, seconds=N)` | RTO | Retentive timer | BOOL (.Q) |
| `rising(signal)` | R_TRIG | Rising edge | BOOL (.Q) |
| `falling(signal)` | F_TRIG | Falling edge | BOOL (.Q) |
| `count_up(signal, preset=N)` | CTU | Count up | BOOL (.Q) |
| `count_down(signal, preset=N)` | CTD | Count down | BOOL (.Q) |
| `count_up_down(up, down, preset=N)` | CTUD | Count up/down | BOOL (.QU) |
| `set_dominant(set, reset)` | SR | Set-dominant bistable | BOOL (.Q) |
| `reset_dominant(set, reset)` | RS | Reset-dominant bistable | BOOL (.Q) |
| `first_scan()` | *(system flag)* | True on first scan only | BOOL |

Duration can be specified as `seconds=N`, `ms=N`, or `duration=timedelta(...)`.

### Variable declarations

| Annotation | IEC section | Notes |
|------------|-------------|-------|
| `x: Input[BOOL]` | VAR_INPUT | Read-only from caller |
| `x: Output[REAL]` | VAR_OUTPUT | Written by the POU |
| `x: InOut[INT]` | VAR_IN_OUT | Pass by reference |
| `x: Static[int]` | VAR_STAT / VAR | Persists across scans |
| `x: Temp[float]` | VAR_TEMP | Reinitialized each scan |
| `x: int = Field(initial=42, constant=True)` | VAR CONSTANT | Read-only constant |
| `x: External[int]` | VAR_EXTERNAL | Reference to global variable |
| `timer: TON` | VAR (FB instance) | Bare FB type annotation → static FB instance |
| `speed: float = 0.0` | VAR (inferred) | Bare annotation → static variable |

`Field()` adds metadata: `Field(initial=0.0, description="...", address="%Q0.0", retain=True, persistent=True)`

### Type system

| Python | IEC 61131-3 | Notes |
|--------|-------------|-------|
| `bool` | BOOL | Python builtins work as type shorthand |
| `int` | INT | 16-bit signed (shadows `builtins.int`) |
| `float` | LREAL | 64-bit float |
| `str` | STRING[255] | |
| `sint`, `int`, `dint`, `lint` | Signed integers | 8/16/32/64 bit — lowercase classes with overflow semantics |
| `usint`, `uint`, `udint`, `ulint` | Unsigned integers | 8/16/32/64 bit |
| `real`, `lreal` | Floating point | 32/64 bit (`real` truncates to single precision) |
| `byte`, `word`, `dword`, `lword` | Bit strings | 8/16/32/64 bit |
| `SINT`, `INT`, `DINT`, `LINT` | Signed integers | Uppercase string constants (also work as annotations) |
| `USINT`, `UINT`, `UDINT`, `ULINT` | Unsigned integers | |
| `REAL`, `LREAL` | Floating point | |
| `BYTE`, `WORD`, `DWORD`, `LWORD` | Bit strings | |
| `TIME`, `LTIME` | Duration | |
| `DATE`, `LDATE`, `TOD`, `LTOD`, `DT`, `LDT` | Date/time | |
| `CHAR`, `WCHAR` | Character | Single-byte / wide |
| `ARRAY(INT, 10)` | ARRAY[0..9] OF INT | Multi-dim: `ARRAY(REAL, 3, 4)` |
| `ARRAY(INT, (1, 10))` | ARRAY[1..10] OF INT | Custom bounds |
| `STRING(80)` | STRING[80] | Max length |
| `WSTRING(80)` | WSTRING[80] | Wide string |
| `POINTER_TO(INT)` | POINTER TO INT | Beckhoff only |
| `REFERENCE_TO(INT)` | REFERENCE TO INT | Beckhoff only |

### POU decorators

| Decorator | IEC type | Notes |
|-----------|----------|-------|
| `@fb` | FUNCTION_BLOCK | Has state, instantiated |
| `@program` | PROGRAM | Top-level, assigned to tasks |
| `@function` | FUNCTION | Stateless, return type from `def logic(self) -> REAL:` |
| `@interface` | INTERFACE | Method signatures only (Beckhoff only) |
| `@method` / `@method(access=PRIVATE)` | METHOD | On FBs, with access specifier |
| `@fb_property(REAL)` | PROPERTY | Getter/setter with access specifiers, abstract/final flags |
| `@sfc` | SFC body | Sequential Function Chart |

### Data types

| Decorator | IEC type | Notes |
|-----------|----------|-------|
| `@dataclass` | STRUCT (DUT) | Primary path — auto-compiled on first use |
| `@struct` | STRUCT (DUT) | Advanced: `Field(description=...)` metadata |
| `IntEnum` | ENUM (DUT) | Primary path — auto-compiled on first use |
| `@enumeration` / `@enumeration(base_type=DINT)` | ENUM (DUT) | Advanced: custom base type |
| `@global_vars` | GVL | Global variable list; `@global_vars(scope="controller")` |

### Project assembly

```python
proj = project("Name", pous=[...], data_types=[...], global_var_lists=[...])
ir = proj.compile()                        # → Project IR
result = proj.compile(target=Vendor.AB)    # → CompileResult with warnings

main = task("MainTask", periodic=timedelta(ms=10), pous=[Main])
fast = task("FastIO",   periodic=timedelta(ms=1),  pous=[IOHandler], priority=1)
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

2296 tests across 54 test files.

## Tech stack

- Python 3.11+
- Pydantic v2 (models, validation, serialization)
- Zero runtime dependencies beyond Pydantic

## Status

**Implemented:**
- Universal IR with full IEC 61131-3 type system, expressions, statements, POUs, SFC, tasks
- Python framework v1: types, descriptors, AST compiler, POU decorators, FB inheritance, `@method`, `@struct`, `@enumeration`, `@global_vars`, `@sfc`, task scheduling, project assembly
- Open-loop scan-cycle simulator with deterministic time

