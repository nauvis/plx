# plx User Stories — System Integrator

## Feasible Today

### Tier 1 — Transformative

**1. Write once, compile to any vendor**

> As an SI, I want to write control logic once in Python and generate L5X, SimaticML, and TcPOU output, so I can bid on jobs regardless of vendor spec.

- **Acceptance:** Python source → `compile(target=Vendor.AB)` → valid L5X; same source → Beckhoff TcPOU
- All three vendor layers (parser + exporter + IR) exist
- Vendor validation already flags incompatible features per target

**2. AI writes my PLC logic**

> As an SI, I want AI tools to generate and autocomplete PLC logic, which is possible because plx is Python — not proprietary XML in a locked-down IDE.

- **Acceptance:** Copilot/Claude can suggest `logic()` bodies, complete FB interfaces, generate entire POUs from docstring descriptions
- Works today with zero additional tooling — it's just Python
- Vendor library stubs (AB drives/motion/process, Beckhoff MC2/standard) give AI context on available FBs

**3. Import existing projects, modify, re-export**

> As an SI, I want to import a customer's existing L5X, modify logic in Python, and export back without losing their tag descriptions, comments, or module config.

- **Acceptance:** Round-trip L5X → AB IR → Universal IR → modify → AB IR → L5X preserves unmodified sections
- Parsers exist for all three vendors
- Lossless fidelity at the vendor IR layer by design

### Tier 2 — High Daily Value

**4. Reusable FB library across vendors**

> As an SI, I want to maintain a standard library of FBs (PID wrappers, valve sequencing, motor starters) in Python and compile per-vendor, so my IP isn't locked to one platform.

- **Acceptance:** `@fb class ValveControl` compiles to AOI (AB), FB (Siemens), and FB (Beckhoff) with correct interface mapping
- FB inheritance, methods, properties all supported
- `project(packages=[my_library])` auto-discovers and includes dependencies

**5. Version control with real diffs**

> As an SI, I want to version-control PLC projects in Git with meaningful line-by-line diffs, so I can review changes, blame regressions, and merge work from multiple engineers.

- **Acceptance:** `git diff` on Python source shows exactly what logic changed; PRs are reviewable
- Works today — Python is the source of truth, vendor files are build artifacts
- Python export can regenerate framework code from IR for imported projects

**6. Simulate before hardware exists**

> As an SI, I want to simulate PLC logic scan-by-scan with manual inputs before the panel is built, so I validate sequences at my desk.

- **Acceptance:** `sim = simulate(MyProgram)` → `sim.ctx.start_button = True` → `sim.ctx.scan()` → assert `sim.ctx.motor_running == True`
- Open-loop executor fully implemented with deterministic time, standard FBs (TON, TOF, CTU, etc.)

**7. Unit test FBs with assertions**

> As an SI, I want to write pytest-style tests for individual FBs, so I catch regressions when updating shared library blocks.

- **Acceptance:** Standard pytest — inject inputs, step N scans, assert outputs
- Simulation API is Pythonic — attribute-style access, `tick(seconds=5)`, `scan()`

### Tier 3 — Team & Process

**8. Enforce coding standards at the framework level**

> As an SI with 15 engineers, I want the framework to enforce naming, structure, and patterns, so code reviews are consistent regardless of who wrote it or which vendor it targets.

- **Acceptance:** AST allowlist rejects unsupported Python constructs; type system catches mismatches at compile time; vendor validation flags platform-incompatible features

**9. Static analysis before commissioning**

> As an SI, I want to catch unguarded outputs, dead SFC steps, and type mismatches before generating vendor files — not during FAT.

- **Acceptance:** `analyze(project, rules=[UnguardedOutputRule(), DeadSfcStepRule()])` returns findings with severity
- Extensible visitor pattern — custom rules can be added

**10. Scaffold new projects instantly**

> As an SI, I want to scaffold a project with task configuration, IO mapping, and boilerplate FBs in minutes instead of clicking through vendor IDE wizards.

- **Acceptance:** `project(name="Line4", pous=[...], tasks=[task("Fast", periodic=T(ms=10))]).compile()` produces full project IR
- Task types: periodic, continuous, event-driven, startup
- Package auto-discovery pulls in all decorated classes from a module

---

## Not Yet Feasible

### Tier 1 — High Impact, On Roadmap

**11. Vendor-to-vendor translation**

> As an SI, I want to translate an existing AB project directly to Beckhoff when a customer switches platforms, preserving as much structure as possible.

- **Blocked by:** Translation infrastructure exists but per-pair modules are incomplete
- All vendor IRs exist, so the foundation is there — the gap is the semantic mapping logic between vendor IR pairs

**12. CI/CD pipeline producing vendor artifacts**

> As an SI, I want every merge to `main` to produce validated, downloadable L5X/TcPOU files automatically.

- **Blocked by:** Remote compilation/validation not fully wired up; exporters exist but CI integration doesn't
- The pieces are in place — this is more DevOps plumbing than core feature work

**13. Push logic updates across 30+ sites**

> As an SI managing many sites, I want to update a shared FB and recompile for each site's vendor/config without touching each project individually.

- **Blocked by:** No site-configuration or fleet-management layer; requires per-site config (IO mapping, hardware) + batch compilation
- Framework supports the compile step; the orchestration layer doesn't exist

### Tier 2 — Differentiated, Longer Horizon

**14. Closed-loop simulation with plant models**

> As an SI, I want to simulate PLC logic against a physics model of the plant (conveyor speeds, tank levels, thermal dynamics) so I can tune PIDs and verify interlocks before FAT.

- **Blocked by:** Plant model library and closed-loop orchestrator not implemented
- Open-loop executor is solid foundation; the gap is the plant-PLC feedback loop

**15. Natural language to state machines**

> As an SI, I want to describe a machine sequence in plain English and get a working state machine that compiles to CASE/enum/timer patterns.

- **Blocked by:** State machine compiler not yet implemented
- AI can generate plx Python today, but the dedicated state machine DSL isn't wired up

**16. Remote compilation against vendor toolchains**

> As an SI, I want to validate generated vendor files against the real compiler (TcBuild, Studio 5000) without installing those tools locally.

- **Blocked by:** Compile repo exists but validation services aren't complete
- Beckhoff TcBuild integration started; AB and Siemens not yet
