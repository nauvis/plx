# Architecture

plx uses a four-layer architecture to bridge Python code and vendor-native PLC project formats.

```
Layer 4:  Python Framework  ← what you write (native Python syntax)
Layer 3:  Universal IR      ← compilation target (Pydantic models, serializable)
Layer 2:  Vendor IRs        ← lossless vendor-specific models (AB, Siemens, Beckhoff)
Layer 1:  Vendor Files      ← L5X, SimaticML, TcPOU/tsproj on disk
```

## Layer 4: Python Framework

The user-facing programming surface. Users write native Python (`if`/`for`/`while`, standard operators). The framework uses AST transformation (`inspect.getsource()` + `ast.parse()`) to compile `logic()` methods into Universal IR nodes — the source is parsed, never executed.

This distinction matters: because plx parses source text rather than executing it, your IDE's autocomplete, type checking, linting, and AI tools all work naturally. There is no runtime magic, no proxy objects, and no context managers intercepting operations.

The compiler is split across focused modules:

- **Expression compiler** — maps Python expressions (`a + b`, `self.arr[i]`, `f"text {self.x}"`) to IR expression nodes
- **Statement compiler** — maps Python statements (`if`/`for`/`while`/`match`/`return`) to IR statement nodes
- **Sentinel compiler** — recognizes compile-time sentinel functions (`delayed()`, `rising()`, etc.) and expands them to FB invocations with auto-generated instance variables

A strict AST **allowlist** ensures only supported Python constructs are accepted. Unsupported constructs (`lambda`, `try`/`except`, `with`, `print()`, etc.) are rejected with clear error messages explaining why and what to do instead.

## Layer 3: Universal IR

The vendor-agnostic data model — the compilation target. Built entirely on Pydantic v2 models with `extra="forbid"` (rejects unknown fields at construction time) and comprehensive validators.

The IR is not intended for direct authoring. It is a structured, serializable, analyzable representation that intentionally omits vendor-specific details.

### What the IR covers

| Domain | Coverage |
|--------|----------|
| **Types** | All 23 IEC 61131-3 primitives, STRING/WSTRING with max length, ARRAY (multi-dimensional, symbolic bounds), POINTER_TO, REFERENCE_TO, STRUCT, ENUM, UNION, ALIAS, SUBRANGE |
| **Variables** | Input, output, in-out, static, temp, constant, external — encoded structurally (no redundant direction/scope enums) |
| **Expressions** | Binary (23 ops incl. AND_THEN/OR_ELSE), unary (3 ops), function calls, array/member/bit access (dynamic), type conversion, dereference, substring, system flags |
| **Statements** | Assignment (with ref-assign and latch variants), IF/CASE/FOR/WHILE/REPEAT, FB invocation, function call, return, exit, continue, jump/label, try/catch, pragma, empty |
| **POUs** | Function blocks, programs, functions, interfaces — with methods, properties, actions, access specifiers, inheritance (`extends`/`implements`) |
| **SFC** | Steps (with entry/exit actions), transitions, all 11 IEC action qualifiers (N, R, S, P, L, D, P0, P1, SD, DS, SL) |
| **Tasks** | Periodic, continuous, event-driven, startup — as a discriminated union |
| **Project** | POUs, data types, global variable lists, tasks, library references |

### Key design decisions

**No abstractions in the IR.** The IR represents what the PLC actually executes — CASE statements, IF/ELSE, FB invocations. Higher-level concepts (state machines, timing helpers, edge detection) live in the framework and compile away to plain IR nodes. This ensures generated vendor code is readable and debuggable by PLC technicians.

**Structural variable encoding.** Variables carry no redundant `direction` or `scope` enums. An input is an input because it lives in the `input_vars` list. This prevents contradictions like "input variable declared as output" by construction.

**Discriminated unions for polymorphism.** Expressions, statements, type references, type definitions, and tasks all use Pydantic discriminated unions with explicit `kind` fields. This enables safe JSON deserialization without runtime type-guessing.

**Fail-fast validation.** 56 validators across 77 model classes catch invalid IR at construction time: duplicate member names, SFC graph integrity (transitions reference existing steps, exactly one initial step), array bounds, body exclusivity (networks XOR sfc_body), and more.

## Layers 2 & 1: Vendor IRs and Vendor Files

plx generates native vendor project files that can be opened directly in each vendor's IDE:

| Vendor | Output format | Complete deliverable? |
|--------|---------------|----------------------|
| Allen Bradley | L5X | Yes — import into Studio 5000, download, go online |
| Beckhoff | .tsproj + .TcPOU + .xti | Yes — open in TwinCAT XAE, compile, activate |
| Siemens | SimaticML .xml | Logic blocks only — hardware must be configured in TIA Portal separately |

## Design principles

### The framework is the portability layer, not the IR

The IR is honest about vendor differences — it represents exactly what each PLC will execute. The framework knows the compile target and emits the correct vendor-specific IR nodes. This means the IR vocabulary stays small and stable, while the framework vocabulary grows per-vendor through sentinels and vendor-qualified APIs.

### Vendor-specific feature tiers

Cross-vendor features fall into three tiers:

**Tier 1 — Universal.** Features that exist on all vendors with compatible semantics. Examples: IF/CASE/FOR/WHILE, arithmetic, BOOL/INT/DINT/REAL, FUNCTION_BLOCK, ARRAY, STRUCT, STRING.

**Tier 2 — Portable via sentinels.** Features that exist on all vendors but with different FB names and parameters. The framework provides universal sentinel functions (`delayed()`, `rising()`, etc.) that compile to the correct vendor-specific implementation based on the compile target.

**Tier 3 — Vendor-specific.** Features unique to one vendor with no semantic equivalent. Users access them through vendor-qualified namespaces (`from plx.framework.vendor import ab`) and mark POUs with `@fb(target=ab)`. The compiler rejects vendor-qualified calls that don't match the compile target.

### Safety PLC isolation

plx never touches safety logic. This is enforced structurally — there is no mechanism by which safety content can enter the pipeline.

**Why this matters:** Safety PLCs run SIL-rated programs (emergency stops, light curtains, safety interlocks). Modifying safety programs requires formal revalidation. An accidental modification could bypass safety protections and cause physical harm.

**Structural guarantee:** The pipeline only processes what it creates. plx compiles `.py` files into IR, raises to vendor IR, exports to vendor files. Safety content never exists as `.py` source, so it never enters the IR. The framework has no API to declare a safety POU — `@fb`, `@program`, `@function` all produce standard POUs. You cannot accidentally create safety logic any more than you can accidentally create a JPEG with a text editor.

**Safety as overlay:** Safety logic is authored and validated in the vendor's native safety tooling (GuardLogix Safety Partner, TwinSAFE Editor, TIA Safety). For projects that include safety, the safety engineer exports vendor-native safety files and checks them into the project repo alongside `.py` source. The build merges both — plx-generated standard logic + vendor-native safety files — via file copy, not a pipeline stage.

### Project source model

A plx project is fully compilable from its source files — vendor files are build artifacts, never the source of truth.

```
my_machine/
├── *.py              # POU logic, data types, GVLs, project assembly
├── plx.toml          # Project-level settings
└── <vendor>.toml     # Vendor-specific hardware/IO/network config
```

**Logic lives in Python.** `.py` files contain POUs, data types, global variable lists, task definitions, and project assembly. These compile to Universal IR via the framework.

**Hardware/IO config lives in config files.** Hardware configuration (controller model, module slot assignments, IO point addresses, network topology, drive parameters) is structured data with no useful universal abstraction. Config files are vendor-specific.

## Package structure

```
src/plx/
├── model/       # Universal IR — Pydantic v2 models
├── framework/   # Python DSL — AST compiler, decorators, sentinels, project assembly
├── export/      # Code generation from IR
│   ├── st/      #   → IEC 61131-3 Structured Text
│   ├── py/      #   → plx Python framework code (lossless round-trip)
│   └── ld/      #   → Ladder Diagram visual model (display only)
├── simulate/    # Scan-cycle simulator — tree-walking IR interpreter
├── analyze/     # Static analysis — visitor-based rule engine
└── stdlib/      # Standard library of reusable POU templates
    ├── analog/      # Analog signal processing
    ├── discrete/    # Discrete I/O patterns
    ├── motors/      # Motor control
    ├── process/     # Process control
    ├── safety/      # Safety-related patterns
    └── valves/      # Valve control
```
