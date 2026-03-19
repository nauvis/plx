"""Execution engine: tree-walking interpreter for Universal IR.

The ``ExecutionEngine`` evaluates statements and expressions against a
flat state dict.  FB instances are nested dicts; structs are dicts;
arrays are lists.
"""

from __future__ import annotations

from collections.abc import Callable

from plx.model.expressions import (
    ArrayAccessExpr,
    BinaryExpr,
    BinaryOp,
    BitAccessExpr,
    DerefExpr,
    Expression,
    FunctionCallExpr,
    LiteralExpr,
    MemberAccessExpr,
    SubstringExpr,
    SystemFlag,
    SystemFlagExpr,
    TypeConversionExpr,
    UnaryExpr,
    UnaryOp,
    VariableRef,
)
from plx.model.pou import POU, Property
from plx.model.sfc import Action, ActionQualifier, SFCBody, Step, Transition
from plx.model.types import NamedTypeRef, PrimitiveTypeRef
from plx.model.statements import (
    Assignment,
    CaseStatement,
    FBInvocation,
    ForStatement,
    FunctionCallStatement,
    IfStatement,
    RepeatStatement,
    ReturnStatement,
    Statement,
    WhileStatement,
)

from ._builtins import STDLIB_FUNCTIONS
from ._pointers import NULL_PTR, PointerTable, _RefBinding
from plx.framework._library import get_library_fb
from ._values import SimulationError, coerce_type, parse_literal, type_default


# ---------------------------------------------------------------------------
# Private signal exceptions for EXIT/CONTINUE/RETURN
# ---------------------------------------------------------------------------

class _ExitSignal(Exception):
    """Raised by EXIT statement, caught by loop handlers."""


class _ContinueSignal(Exception):
    """Raised by CONTINUE statement, caught by loop handlers."""


class _ReturnSignal(Exception):
    """Raised by RETURN statement, carries optional return value."""

    def __init__(self, value: object = None):
        self.value = value


# ---------------------------------------------------------------------------
# ExecutionEngine
# ---------------------------------------------------------------------------

class ExecutionEngine:
    """Tree-walking interpreter for a single POU scan cycle.

    Parameters
    ----------
    pou : POU
        The POU whose logic is being executed.
    state : dict
        Mutable state dict (variable name -> value). Mutated in place.
    clock_ms : int
        Current simulated time in milliseconds.
    pou_registry : dict[str, POU]
        Registry of user-defined POUs for nested FB execution.
    data_type_registry : dict[str, object]
        Registry of type definitions (StructType, EnumType) for resolution.
    enum_registry : dict
        Enum name -> IntEnum class for literal resolution.
    """

    def __init__(
        self,
        pou: POU,
        state: dict,
        clock_ms: int,
        pou_registry: dict[str, POU] | None = None,
        data_type_registry: dict | None = None,
        enum_registry: dict | None = None,
        pointer_table: PointerTable | None = None,
    ) -> None:
        self.pou = pou
        self.state = state
        self.clock_ms = clock_ms
        self.pou_registry = pou_registry or {}
        self.data_type_registry = data_type_registry or {}
        self.enum_registry = enum_registry or {}
        self.pointer_table = pointer_table

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def execute(self) -> object | None:
        """Execute all networks (or SFC body) in the POU.

        Returns the value from a RETURN statement if one is executed,
        otherwise returns None.
        """
        if self.pou.sfc_body is not None:
            self._execute_sfc()
        else:
            try:
                for network in self.pou.networks:
                    for stmt in network.statements:
                        self._exec_stmt(stmt)
            except _ReturnSignal as ret:
                return ret.value
        return None

    # -----------------------------------------------------------------------
    # SFC execution
    # -----------------------------------------------------------------------

    def _execute_sfc(self) -> None:
        """Execute one SFC scan cycle.

        Algorithm per scan:
        1. Initialize (first scan): activate initial steps
        2. Execute exit actions from previous scan's deactivated steps
        3. Execute entry actions on newly activated steps
        4. Execute N-qualified actions on all active steps
        5. Execute time-based actions (L, D, SD, DS, SL)
        6. Execute stored actions (S)
        7. Evaluate transitions and fire them
        """
        sfc = self.pou.sfc_body
        state = self.state

        # Build step lookup
        step_map: dict[str, Step] = {s.name: s for s in sfc.steps}

        # -- 1. Initialize on first scan --
        if not state.get("__sfc_initialized", False):
            active = set()
            for s in sfc.steps:
                if s.is_initial:
                    active.add(s.name)
            state["__sfc_active_steps"] = active
            state["__sfc_step_entry_time"] = {n: self.clock_ms for n in active}
            state["__sfc_just_activated"] = set(active)
            state["__sfc_just_deactivated"] = set()
            state["__sfc_action_start_time"] = {}
            state["__sfc_stored_actions"] = set()
            state["__sfc_initialized"] = True

        active_steps: set[str] = state["__sfc_active_steps"]
        just_activated: set[str] = state["__sfc_just_activated"]
        just_deactivated: set[str] = state["__sfc_just_deactivated"]
        step_entry_time: dict[str, int] = state["__sfc_step_entry_time"]
        action_start_time: dict[str, int] = state["__sfc_action_start_time"]
        stored_actions: set[str] = state["__sfc_stored_actions"]

        # -- 2. Execute exit actions from previous scan's deactivated steps --
        for step_name in just_deactivated:
            if step_name in step_map:
                step_obj = step_map[step_name]
                for action in step_obj.exit_actions:
                    self._exec_action_body(action)
                # Also run P0-qualified actions in the main actions list
                for action in step_obj.actions:
                    if action.qualifier == ActionQualifier.P0:
                        self._exec_action_body(action)

        # -- 3. Execute entry actions on newly activated steps --
        for step_name in just_activated:
            if step_name in step_map:
                step_obj = step_map[step_name]
                for action in step_obj.entry_actions:
                    self._exec_action_body(action)
                # Also run P1/P-qualified actions in the main actions list
                for action in step_obj.actions:
                    if action.qualifier in (ActionQualifier.P1, ActionQualifier.P):
                        self._exec_action_body(action)
                    # S-qualified: start stored action on activation
                    if action.qualifier == ActionQualifier.S:
                        stored_actions.add(action.name)
                    # SD-qualified: record start time for delayed-store
                    if action.qualifier == ActionQualifier.SD:
                        action_start_time[action.name] = self.clock_ms
                    # DS-qualified: record start time for delayed-then-stored
                    if action.qualifier == ActionQualifier.DS:
                        action_start_time[action.name] = self.clock_ms
                    # SL-qualified: start stored with time limit on activation
                    if action.qualifier == ActionQualifier.SL:
                        stored_actions.add(action.name)
                        action_start_time[action.name] = self.clock_ms

        # -- 4. Execute N-qualified actions on all active steps --
        for step_name in active_steps:
            if step_name in step_map:
                for action in step_map[step_name].actions:
                    if action.qualifier == ActionQualifier.N:
                        self._exec_action_body(action)

        # -- 5. Time-based actions --
        for step_name in active_steps:
            if step_name not in step_map:
                continue
            entry_time = step_entry_time.get(step_name, self.clock_ms)
            elapsed = self.clock_ms - entry_time

            for action in step_map[step_name].actions:
                duration_ms = self._parse_action_duration(action)

                if action.qualifier == ActionQualifier.L:
                    # Time-limited: run while elapsed < duration
                    if duration_ms is not None and elapsed < duration_ms:
                        self._exec_action_body(action)

                elif action.qualifier == ActionQualifier.D:
                    # Time-delayed: run after elapsed >= duration
                    if duration_ms is not None and elapsed >= duration_ms:
                        self._exec_action_body(action)

                elif action.qualifier == ActionQualifier.SD:
                    # Stored and delayed: after duration, becomes stored
                    if action.name in action_start_time:
                        sd_elapsed = self.clock_ms - action_start_time[action.name]
                        if duration_ms is not None and sd_elapsed >= duration_ms:
                            stored_actions.add(action.name)
                            del action_start_time[action.name]

                elif action.qualifier == ActionQualifier.DS:
                    # Delayed and stored: after duration (while step active), becomes stored
                    if action.name in action_start_time:
                        ds_elapsed = self.clock_ms - action_start_time[action.name]
                        if duration_ms is not None and ds_elapsed >= duration_ms:
                            stored_actions.add(action.name)
                            del action_start_time[action.name]

        # -- 5b. Process SD timers for deactivated steps --
        # SD becomes stored after delay regardless of step activity
        for s in sfc.steps:
            if s.name in active_steps:
                continue  # Already handled in section 5
            for action in s.actions:
                if action.qualifier == ActionQualifier.SD and action.name in action_start_time:
                    sd_elapsed = self.clock_ms - action_start_time[action.name]
                    duration_ms = self._parse_action_duration(action)
                    if duration_ms is not None and sd_elapsed >= duration_ms:
                        stored_actions.add(action.name)
                        del action_start_time[action.name]

        # -- 6. Execute stored actions --
        # Build a lookup of all actions by name for stored execution
        all_actions: dict[str, Action] = {}
        for s in sfc.steps:
            for a in s.actions + s.entry_actions + s.exit_actions:
                all_actions[a.name] = a

        expired_stored: set[str] = set()
        for action_name in stored_actions:
            if action_name in all_actions:
                action = all_actions[action_name]
                # SL: check time limit
                if action.qualifier == ActionQualifier.SL:
                    if action_name in action_start_time:
                        sl_elapsed = self.clock_ms - action_start_time[action_name]
                        duration_ms = self._parse_action_duration(action)
                        if duration_ms is not None and sl_elapsed >= duration_ms:
                            expired_stored.add(action_name)
                            continue
                self._exec_action_body(action)

        stored_actions -= expired_stored
        # Also clean up start times for expired
        for name in expired_stored:
            action_start_time.pop(name, None)

        # -- 7. Evaluate transitions and fire --
        # Track which sources have already had a transition fire (selection divergence)
        fired_sources: set[str] = set()
        new_active = set(active_steps)
        new_just_activated: set[str] = set()
        new_just_deactivated: set[str] = set()

        for trans in sfc.transitions:
            # Skip if any source step already consumed by another transition
            if any(s in fired_sources for s in trans.source_steps):
                continue
            # All source steps must be active
            if not all(s in active_steps for s in trans.source_steps):
                continue
            # Evaluate condition
            if self._eval(trans.condition):
                # Fire: remove sources, add targets
                for s in trans.source_steps:
                    fired_sources.add(s)
                    if s in new_active:
                        new_active.discard(s)
                        new_just_deactivated.add(s)
                for t in trans.target_steps:
                    new_active.add(t)
                    new_just_activated.add(t)
                    step_entry_time[t] = self.clock_ms

        # Handle R (reset) actions on newly activated steps
        for step_name in new_just_activated:
            if step_name in step_map:
                for action in step_map[step_name].actions:
                    if action.qualifier == ActionQualifier.R:
                        # R resets by action_name (if set) or the action's own name
                        target = action.action_name or action.name
                        stored_actions.discard(target)

        # Clean up entry times for deactivated steps
        for s in new_just_deactivated:
            step_entry_time.pop(s, None)
            # Clean up DS action timers for deactivated steps — DS requires
            # step to remain active for the full duration
            if s in step_map:
                for action in step_map[s].actions:
                    if action.qualifier == ActionQualifier.DS:
                        action_start_time.pop(action.name, None)

        # Update state
        state["__sfc_active_steps"] = new_active
        state["__sfc_just_activated"] = new_just_activated
        state["__sfc_just_deactivated"] = new_just_deactivated

    def _exec_action_body(self, action: Action) -> None:
        """Execute an action's body statements, or resolve action_name reference."""
        # If the action references a named POUAction, look it up
        if action.action_name is not None and not action.body:
            pou_action = self._find_pou_action(action.action_name)
            if pou_action is not None:
                try:
                    for network in pou_action.body:
                        for stmt in network.statements:
                            self._exec_stmt(stmt)
                except _ReturnSignal:
                    pass
                return
            raise SimulationError(
                f"POUAction '{action.action_name}' not found on POU '{self.pou.name}'"
            )
        try:
            self._exec_body(action.body)
        except _ReturnSignal:
            pass

    def _find_pou_action(self, name: str):
        """Find a named POUAction on the current POU."""
        for a in self.pou.actions:
            if a.name == name:
                return a
        return None

    @staticmethod
    def _parse_action_duration(action: Action) -> int | None:
        """Parse action duration to milliseconds, or None if no duration."""
        if action.duration is None:
            return None
        from ._values import _parse_time_literal
        return _parse_time_literal(action.duration)

    # -----------------------------------------------------------------------
    # Statement dispatch
    # -----------------------------------------------------------------------

    def _exec_stmt(self, stmt: Statement) -> None:
        handler = self._STMT_DISPATCH.get(stmt.kind)
        if handler is None:
            raise SimulationError(f"Unsupported statement kind: {stmt.kind}")
        handler(self, stmt)

    def _exec_assignment(self, stmt: Assignment) -> None:
        if stmt.ref_assign:
            self._exec_ref_assign(stmt)
            return
        value = self._eval(stmt.value)
        if stmt.latch == "S":
            # S= (set/latch): set target to TRUE only when value is truthy
            if self._scalar(value):
                self._write_target(stmt.target, True)
            return
        if stmt.latch == "R":
            # R= (reset/unlatch): reset target to FALSE only when value is truthy
            if self._scalar(value):
                self._write_target(stmt.target, False)
            return
        self._write_target(stmt.target, value)

    def _exec_ref_assign(self, stmt: Assignment) -> None:
        """Handle REF= assignment: bind a reference to a variable."""
        if self.pointer_table is None:
            raise SimulationError(
                "REF= assignment requires pointer support "
                "(use simulate() instead of raw ExecutionEngine)"
            )
        container, key, path = self._resolve_binding(stmt.value)
        addr = self.pointer_table.get_or_assign(path, container, key)
        # Store a _RefBinding as the LHS value
        self._write_target(stmt.target, _RefBinding(addr))

    def _exec_if(self, stmt: IfStatement) -> None:
        if self._scalar(self._eval(stmt.if_branch.condition)):
            self._exec_body(stmt.if_branch.body)
            return

        for branch in stmt.elsif_branches:
            if self._scalar(self._eval(branch.condition)):
                self._exec_body(branch.body)
                return

        if stmt.else_body:
            self._exec_body(stmt.else_body)

    def _exec_case(self, stmt: CaseStatement) -> None:
        selector = self._eval(stmt.selector)
        selector_int = int(selector) if not isinstance(selector, int) else selector

        for branch in stmt.branches:
            matched = False
            if selector_int in branch.values:
                matched = True
            if not matched:
                for rng in branch.ranges:
                    if rng.start <= selector_int <= rng.end:
                        matched = True
                        break
            if matched:
                self._exec_body(branch.body)
                return

        if stmt.else_body:
            self._exec_body(stmt.else_body)

    def _exec_for(self, stmt: ForStatement) -> None:
        from_val = int(self._eval(stmt.from_expr))
        to_val = int(self._eval(stmt.to_expr))
        by_val = int(self._eval(stmt.by_expr)) if stmt.by_expr else 1

        if by_val == 0:
            raise SimulationError("FOR loop step (BY) cannot be zero")

        i = from_val
        while True:
            if by_val > 0 and i > to_val:
                break
            if by_val < 0 and i < to_val:
                break

            self.state[stmt.loop_var] = i
            try:
                self._exec_body(stmt.body)
            except _ExitSignal:
                break
            except _ContinueSignal:
                pass
            i += by_val

    #: Maximum iterations for while/repeat before raising SimulationError.
    MAX_LOOP_ITERATIONS: int = 1_000_000

    def _exec_while(self, stmt: WhileStatement) -> None:
        iterations = 0
        while self._scalar(self._eval(stmt.condition)):
            iterations += 1
            if iterations > self.MAX_LOOP_ITERATIONS:
                raise SimulationError(
                    f"WHILE loop exceeded {self.MAX_LOOP_ITERATIONS} iterations "
                    f"(possible infinite loop)"
                )
            try:
                self._exec_body(stmt.body)
            except _ExitSignal:
                break
            except _ContinueSignal:
                pass

    def _exec_repeat(self, stmt: RepeatStatement) -> None:
        iterations = 0
        while True:
            iterations += 1
            if iterations > self.MAX_LOOP_ITERATIONS:
                raise SimulationError(
                    f"REPEAT loop exceeded {self.MAX_LOOP_ITERATIONS} iterations "
                    f"(possible infinite loop)"
                )
            try:
                self._exec_body(stmt.body)
            except _ExitSignal:
                break
            except _ContinueSignal:
                pass
            if self._scalar(self._eval(stmt.until)):
                break

    def _exec_return(self, stmt: ReturnStatement) -> None:
        value = self._eval(stmt.value) if stmt.value is not None else None
        raise _ReturnSignal(value)

    def _exec_fb_invocation(self, stmt: FBInvocation) -> None:
        fb_type = stmt.fb_type.name if isinstance(stmt.fb_type, NamedTypeRef) else None

        # 1. Resolve instance state
        if isinstance(stmt.instance_name, str):
            instance_name = stmt.instance_name
            if instance_name not in self.state:
                raise SimulationError(
                    f"FB instance '{instance_name}' not found in state"
                )
            instance_state = self.state[instance_name]
            display_name = instance_name
        else:
            # Expression instance_name (e.g. ArrayAccessExpr for arr[i])
            instance_state = self._eval(stmt.instance_name)
            display_name = "<array element>"

        if not isinstance(instance_state, dict):
            raise SimulationError(
                f"FB instance '{display_name}' is not a dict (got {type(instance_state).__name__})"
            )

        # 2. Map inputs
        for param_name, expr in stmt.inputs.items():
            instance_state[param_name] = self._eval(expr)

        # 3. Execute — library FBs (IEC standard + vendor stubs) take priority
        lib_fb = get_library_fb(fb_type) if fb_type else None
        if lib_fb is not None:
            lib_fb.execute(instance_state, self.clock_ms)
        elif fb_type and fb_type in self.pou_registry:
            self._exec_user_fb(self.pou_registry[fb_type], instance_state)
        else:
            raise SimulationError(
                f"Unknown FB type '{fb_type}' for instance '{display_name}'"
            )

        # 4. Map outputs
        for param_name, target_expr in stmt.outputs.items():
            if param_name in instance_state:
                self._write_target(target_expr, instance_state[param_name])

    def _exec_user_fb(self, pou: POU, instance_state: dict) -> None:
        """Execute a user-defined FB by creating a nested ExecutionEngine."""
        engine = ExecutionEngine(
            pou=pou,
            state=instance_state,
            clock_ms=self.clock_ms,
            pou_registry=self.pou_registry,
            data_type_registry=self.data_type_registry,
            enum_registry=self.enum_registry,
            pointer_table=self.pointer_table,
        )
        engine.execute()

    def _exec_function_call_stmt(self, stmt: FunctionCallStatement) -> None:
        name = stmt.function_name

        # __DELETE is statement-only
        if name.upper() == "__DELETE":
            if self.pointer_table is None:
                raise SimulationError(
                    "__DELETE() requires pointer support "
                    "(use simulate() instead of raw ExecutionEngine)"
                )
            if len(stmt.args) != 1:
                raise SimulationError("__DELETE() requires exactly 1 argument")
            addr = self._eval(stmt.args[0].value)
            self.pointer_table.heap_free(int(addr))
            # Set the pointer variable to null after deletion
            if isinstance(stmt.args[0].value, VariableRef):
                self.state[stmt.args[0].value.name] = NULL_PTR
            return

        if name in STDLIB_FUNCTIONS:
            pos_args = [self._eval(a.value) for a in stmt.args if a.name is None]
            kw_args = {a.name: self._eval(a.value) for a in stmt.args if a.name is not None}
            STDLIB_FUNCTIONS[name](*pos_args, **kw_args)
        elif name in self.pou_registry:
            self._call_user_function(name, stmt.args)
        elif self._find_method(name) is not None:
            self._call_method(name, stmt.args)
        else:
            raise SimulationError(f"Unknown function: {name}")

    def _find_method(self, name: str):
        """Find a method by name on the current POU."""
        for m in self.pou.methods:
            if m.name == name:
                return m
        return None

    def _call_method(self, name: str, args: list) -> object:
        """Execute a POU method in a nested context with mapped inputs."""
        from plx.model.expressions import CallArg

        method = self._find_method(name)
        if method is None:
            raise SimulationError(f"Method '{name}' not found on POU '{self.pou.name}'")

        # Build method state: start with current POU state (methods share instance vars)
        method_state = self.state

        # Map args to method input vars
        input_vars = method.interface.input_vars if method.interface else []
        for i, arg in enumerate(args):
            if isinstance(arg, CallArg):
                val = self._eval(arg.value)
                if arg.name is not None:
                    method_state[arg.name] = val
                elif i < len(input_vars):
                    method_state[input_vars[i].name] = val
            elif i < len(input_vars):
                method_state[input_vars[i].name] = arg

        # Initialize temp vars (always fresh per invocation)
        temp_vars = method.interface.temp_vars if method.interface else []
        for var in temp_vars:
            method_state[var.name] = type_default(var.data_type)

        # Execute method networks directly (avoid execute() which swallows ReturnSignal)
        try:
            for network in method.networks:
                for stmt in network.statements:
                    self._exec_stmt(stmt)
        except _ReturnSignal as ret:
            return ret.value

        return None

    def _exec_exit(self, _stmt: Statement) -> None:
        raise _ExitSignal()

    def _exec_continue(self, _stmt: Statement) -> None:
        raise _ContinueSignal()

    def _exec_empty(self, _stmt: Statement) -> None:
        pass

    def _exec_pragma(self, _stmt: Statement) -> None:
        pass  # Pragmas are compiler directives — no runtime effect

    # Statement dispatch table
    _STMT_DISPATCH: dict[str, Callable[[ExecutionEngine, Statement], None]] = {
        "assignment": _exec_assignment,
        "if": _exec_if,
        "case": _exec_case,
        "for": _exec_for,
        "while": _exec_while,
        "repeat": _exec_repeat,
        "exit": _exec_exit,
        "continue": _exec_continue,
        "return": _exec_return,
        "fb_invocation": _exec_fb_invocation,
        "function_call_stmt": _exec_function_call_stmt,
        "empty": _exec_empty,
        "pragma": _exec_pragma,
    }

    def _exec_body(self, stmts: list[Statement]) -> None:
        for stmt in stmts:
            self._exec_stmt(stmt)

    # -----------------------------------------------------------------------
    # Expression dispatch
    # -----------------------------------------------------------------------

    @staticmethod
    def _scalar(value: object) -> object:
        """Coerce FB instances (dicts) to their Q output for scalar contexts.

        In PLC semantics, referencing an FB instance in a boolean/arithmetic
        context implicitly reads its Q output (e.g. ``NOT timer`` means
        ``NOT timer.Q``).
        """
        if isinstance(value, dict):
            return value.get("Q", value.get("q", False))
        return value

    def _eval(self, expr: Expression) -> object:
        handler = self._EXPR_DISPATCH.get(expr.kind)
        if handler is None:
            raise SimulationError(f"Unsupported expression kind: {expr.kind}")
        return handler(self, expr)

    def _eval_literal(self, expr: LiteralExpr) -> object:
        return parse_literal(expr.value, expr.data_type, self.enum_registry)

    def _eval_variable_ref(self, expr: VariableRef) -> object:
        name = expr.name
        if name not in self.state:
            raise SimulationError(f"Variable '{name}' not found in state")
        value = self.state[name]
        # Transparently follow reference bindings
        if isinstance(value, _RefBinding):
            if self.pointer_table is None:
                raise SimulationError(
                    f"Variable '{name}' is a reference binding but no pointer table available"
                )
            return self.pointer_table.read(value.target_addr)
        return value

    def _eval_binary(self, expr: BinaryExpr) -> object:
        # AND_THEN / OR_ELSE: short-circuit evaluation (Beckhoff ExST extension)
        if expr.op == BinaryOp.AND_THEN:
            left = self._scalar(self._eval(expr.left))
            return bool(left) and bool(self._scalar(self._eval(expr.right)))
        if expr.op == BinaryOp.OR_ELSE:
            left = self._scalar(self._eval(expr.left))
            return bool(left) or bool(self._scalar(self._eval(expr.right)))
        # Standard PLC semantics — evaluate both sides (no short-circuit)
        left = self._scalar(self._eval(expr.left))
        right = self._scalar(self._eval(expr.right))
        return self._apply_binop(expr.op, left, right)

    def _apply_binop(self, op: BinaryOp, left: object, right: object) -> object:
        if op == BinaryOp.ADD:
            return left + right
        if op == BinaryOp.SUB:
            return left - right
        if op == BinaryOp.MUL:
            return left * right
        if op == BinaryOp.DIV:
            if isinstance(left, float) or isinstance(right, float):
                return left / right
            # IEC integer division: truncate toward zero
            return int(left / right)
        if op == BinaryOp.MOD:
            return left % right
        if op == BinaryOp.EXPT:
            return left ** right

        # Logical / bitwise
        if op == BinaryOp.AND:
            if isinstance(left, bool) and isinstance(right, bool):
                return left and right
            return left & right
        if op == BinaryOp.OR:
            if isinstance(left, bool) and isinstance(right, bool):
                return left or right
            return left | right
        if op == BinaryOp.XOR:
            if isinstance(left, bool) and isinstance(right, bool):
                return left ^ right
            return left ^ right
        if op == BinaryOp.BAND:
            return left & right
        if op == BinaryOp.BOR:
            return left | right

        # Comparison
        if op == BinaryOp.EQ:
            return left == right
        if op == BinaryOp.NE:
            return left != right
        if op == BinaryOp.GT:
            return left > right
        if op == BinaryOp.GE:
            return left >= right
        if op == BinaryOp.LT:
            return left < right
        if op == BinaryOp.LE:
            return left <= right

        # Shift
        if op == BinaryOp.SHL:
            return int(left) << int(right)
        if op == BinaryOp.SHR:
            return int(left) >> int(right)
        if op == BinaryOp.ROL:
            value, n = int(left) & 0xFFFFFFFF, int(right) % 32
            return ((value << n) | (value >> (32 - n))) & 0xFFFFFFFF
        if op == BinaryOp.ROR:
            value, n = int(left) & 0xFFFFFFFF, int(right) % 32
            return ((value >> n) | (value << (32 - n))) & 0xFFFFFFFF

        raise SimulationError(f"Unsupported binary op: {op}")

    def _eval_unary(self, expr: UnaryExpr) -> object:
        operand = self._scalar(self._eval(expr.operand))
        if expr.op == UnaryOp.NEG:
            return -operand
        if expr.op == UnaryOp.NOT:
            if isinstance(operand, bool):
                return not operand
            return ~operand
        if expr.op == UnaryOp.BNOT:
            return ~operand
        raise SimulationError(f"Unsupported unary op: {expr.op}")

    def _eval_function_call(self, expr: FunctionCallExpr) -> object:
        name = expr.function_name

        # Pointer intrinsics (before stdlib so ADR/SIZEOF don't conflict)
        result = self._try_pointer_intrinsic(name, expr)
        if result is not None:
            return result[0]

        # Stdlib functions
        if name in STDLIB_FUNCTIONS:
            pos_args = [self._eval(a.value) for a in expr.args if a.name is None]
            kw_args = {a.name: self._eval(a.value) for a in expr.args if a.name is not None}
            return STDLIB_FUNCTIONS[name](*pos_args, **kw_args)

        # User-defined FUNCTION POUs
        if name in self.pou_registry:
            return self._call_user_function(name, expr.args)

        # POU methods
        if self._find_method(name) is not None:
            return self._call_method(name, expr.args)

        raise SimulationError(f"Unknown function: {name}")

    def _try_pointer_intrinsic(
        self, name: str, expr: FunctionCallExpr,
    ) -> tuple[object] | None:
        """Handle pointer intrinsic functions. Returns (value,) or None."""
        upper = name.upper()

        if upper == "ADR" or upper == "ADRINST":
            if self.pointer_table is None:
                raise SimulationError(
                    f"{name}() requires pointer support "
                    f"(use simulate() instead of raw ExecutionEngine)"
                )
            if len(expr.args) != 1:
                raise SimulationError(f"{name}() requires exactly 1 argument")
            container, key, path = self._resolve_binding(expr.args[0].value)
            return (self.pointer_table.get_or_assign(path, container, key),)

        if upper == "SIZEOF":
            if len(expr.args) != 1:
                raise SimulationError("SIZEOF() requires exactly 1 argument")
            return (self._eval_sizeof(expr.args[0].value),)

        if upper == "__NEW":
            if self.pointer_table is None:
                raise SimulationError(
                    "__NEW() requires pointer support "
                    "(use simulate() instead of raw ExecutionEngine)"
                )
            return (self._eval_new(expr),)

        if upper == "__ISVALIDREF":
            if len(expr.args) != 1:
                raise SimulationError("__ISVALIDREF() requires exactly 1 argument")
            return (self._eval_isvalidref(expr.args[0].value),)

        return None

    def _resolve_binding(
        self, expr: Expression,
    ) -> tuple[dict | list, str | int, str]:
        """Resolve an expression to (container, key, canonical_path).

        The container is the dict/list holding the value; key is the
        name/index within it. This enables ADR() to return stable addresses
        and REF= to create aliases.
        """
        if isinstance(expr, VariableRef):
            return (self.state, expr.name, expr.name)

        if isinstance(expr, MemberAccessExpr):
            struct = self._eval(expr.struct)
            if not isinstance(struct, dict):
                raise SimulationError(
                    f"Cannot take address of member '{expr.member}' "
                    f"on {type(struct).__name__}"
                )
            # Build path for stable addressing
            if isinstance(expr.struct, VariableRef):
                path = f"{expr.struct.name}.{expr.member}"
            else:
                path = f"<expr>.{expr.member}"
            return (struct, expr.member, path)

        if isinstance(expr, ArrayAccessExpr):
            array = self._eval(expr.array)
            if not isinstance(array, list):
                raise SimulationError(
                    f"Cannot take address of element in {type(array).__name__}"
                )
            idx = int(self._eval(expr.indices[0]))
            if isinstance(expr.array, VariableRef):
                path = f"{expr.array.name}[{idx}]"
            else:
                path = f"<expr>[{idx}]"
            return (array, idx, path)

        if isinstance(expr, DerefExpr):
            # ADR(ptr^) — address of what ptr points to
            if self.pointer_table is None:
                raise SimulationError("Cannot resolve binding through pointer without pointer table")
            addr = self._eval(expr.pointer)
            binding = self.pointer_table._addr_to_binding.get(int(addr))
            if binding is None:
                raise SimulationError(f"Cannot take address of dereferenced invalid pointer")
            container, key = binding
            return (container, key, f"<deref@0x{int(addr):08X}>")

        raise SimulationError(
            f"Cannot take address of expression kind: {expr.kind}"
        )

    def _eval_sizeof(self, expr: Expression) -> int:
        """Evaluate SIZEOF() — return byte size based on type."""
        _PRIM_SIZES = {
            "BOOL": 1, "BYTE": 1, "SINT": 1, "USINT": 1,
            "WORD": 2, "INT": 2, "UINT": 2,
            "DWORD": 4, "DINT": 4, "UDINT": 4, "REAL": 4, "TIME": 4,
            "LWORD": 8, "LINT": 8, "ULINT": 8, "LREAL": 8, "LTIME": 8,
        }
        # Try to find the variable's declared type
        if isinstance(expr, VariableRef):
            for var in (
                self.pou.interface.input_vars
                + self.pou.interface.output_vars
                + self.pou.interface.static_vars
                + self.pou.interface.inout_vars
                + self.pou.interface.temp_vars
            ):
                if var.name == expr.name:
                    from plx.model.types import PrimitiveTypeRef, ArrayTypeRef, StringTypeRef
                    dt = var.data_type
                    if isinstance(dt, PrimitiveTypeRef):
                        return _PRIM_SIZES.get(dt.type.value, 4)
                    if isinstance(dt, StringTypeRef):
                        return (dt.max_length or 255) + 1
                    if isinstance(dt, ArrayTypeRef):
                        elem_size = 4  # default
                        if isinstance(dt.element_type, PrimitiveTypeRef):
                            elem_size = _PRIM_SIZES.get(dt.element_type.type.value, 4)
                        count = 1
                        for dim in dt.dimensions:
                            if isinstance(dim.lower, int) and isinstance(dim.upper, int):
                                count *= (dim.upper - dim.lower + 1)
                        return elem_size * count
                    break
        # Fallback: guess from runtime value
        value = self._eval(expr)
        if isinstance(value, bool):
            return 1
        if isinstance(value, int):
            return 4
        if isinstance(value, float):
            return 4
        if isinstance(value, str):
            return len(value) + 1
        if isinstance(value, dict):
            return sum(4 for _ in value)  # rough estimate
        if isinstance(value, list):
            return len(value) * 4
        return 4

    def _eval_new(self, expr: FunctionCallExpr) -> int:
        """Evaluate __NEW(Type [, count]). Returns heap address."""
        if not expr.args:
            raise SimulationError("__NEW() requires at least 1 argument")
        # First arg is a type literal (LiteralExpr with type name string)
        type_arg = expr.args[0].value
        if isinstance(type_arg, LiteralExpr):
            type_name = type_arg.value
        elif isinstance(type_arg, VariableRef):
            type_name = type_arg.name
        else:
            type_name = str(type_arg)
        # Strip "POINTER TO " prefix (common: __NEW(POINTER TO MyStruct))
        upper = type_name.upper()
        if upper.startswith("POINTER TO "):
            type_name = type_name[11:]
        # Determine default value
        from plx.model.types import PrimitiveType, StructType
        try:
            prim = PrimitiveType(type_name.upper())
            default = type_default(PrimitiveTypeRef(type=prim))
        except ValueError:
            # Named type — try to allocate from registry
            if type_name in self.data_type_registry:
                typedef = self.data_type_registry[type_name]
                if isinstance(typedef, StructType):
                    default = {}
                    for m in typedef.members:
                        d = type_default(m.data_type)
                        default[m.name] = d if d is not None else 0
                else:
                    default = 0
            else:
                default = {}
        # Handle count argument: __NEW(BYTE, 100) → list
        if len(expr.args) >= 2:
            count = int(self._eval(expr.args[1].value))
            default = [default for _ in range(count)]
        return self.pointer_table.heap_alloc(default)

    def _eval_isvalidref(self, expr: Expression) -> bool:
        """Evaluate __ISVALIDREF(ref) — check if reference is valid."""
        # Read raw value without following references
        if isinstance(expr, VariableRef):
            if expr.name not in self.state:
                return False
            value = self.state[expr.name]
            if isinstance(value, _RefBinding):
                if self.pointer_table is None:
                    return False
                return self.pointer_table.is_valid(value.target_addr)
            # A raw integer — check if it's a valid pointer
            if isinstance(value, int):
                if value == NULL_PTR:
                    return False
                if self.pointer_table is not None:
                    return self.pointer_table.is_valid(value)
                return value != 0
        # For other expressions, just check non-zero
        value = self._eval(expr)
        if isinstance(value, _RefBinding):
            if self.pointer_table is None:
                return False
            return self.pointer_table.is_valid(value.target_addr)
        if isinstance(value, int):
            return value != 0
        return True

    def _call_user_function(self, name: str, args: list) -> object:
        """Call a user-defined FUNCTION POU."""
        from plx.model.expressions import CallArg

        pou = self.pou_registry[name]
        func_state: dict[str, object] = {}

        # Initialize all vars to defaults
        for var in pou.interface.input_vars:
            func_state[var.name] = type_default(var.data_type)
        for var in pou.interface.temp_vars:
            func_state[var.name] = type_default(var.data_type)

        # Map args to input vars (positional or named)
        input_vars = pou.interface.input_vars
        for i, arg in enumerate(args):
            if isinstance(arg, CallArg):
                val = self._eval(arg.value)
                if arg.name is not None:
                    func_state[arg.name] = val
                elif i < len(input_vars):
                    func_state[input_vars[i].name] = val
            elif i < len(input_vars):
                func_state[input_vars[i].name] = arg

        # Execute
        engine = ExecutionEngine(
            pou=pou,
            state=func_state,
            clock_ms=self.clock_ms,
            pou_registry=self.pou_registry,
            data_type_registry=self.data_type_registry,
            enum_registry=self.enum_registry,
            pointer_table=self.pointer_table,
        )
        return engine.execute()

    def _find_property(self, struct_expr: Expression, member: str) -> tuple[Property, POU] | None:
        """Find a Property on the FB type of a struct expression.

        Returns (Property, POU) or None if not found.
        """
        if struct_expr.kind != "variable_ref":
            return None
        var_name = struct_expr.name
        # Look up the variable in the current POU's interface
        for var in (
            self.pou.interface.static_vars
            + self.pou.interface.input_vars
            + self.pou.interface.output_vars
            + self.pou.interface.inout_vars
        ):
            if var.name == var_name and isinstance(var.data_type, NamedTypeRef):
                fb_name = var.data_type.name
                if fb_name in self.pou_registry:
                    fb_pou = self.pou_registry[fb_name]
                    for prop in fb_pou.properties:
                        if prop.name == member:
                            return prop, fb_pou
        return None

    def _eval_member_access(self, expr: MemberAccessExpr) -> object:
        struct = self._eval(expr.struct)
        if isinstance(struct, dict):
            if expr.member in struct:
                return struct[expr.member]
            # Check for property getter
            result = self._find_property(expr.struct, expr.member)
            if result is not None:
                prop, fb_pou = result
                if prop.getter is not None:
                    return self._exec_property_getter(prop, fb_pou, struct)
            raise SimulationError(
                f"Member '{expr.member}' not found in struct. "
                f"Available: {list(struct.keys())}"
            )
        raise SimulationError(
            f"Cannot access member '{expr.member}' on {type(struct).__name__}"
        )

    def _exec_property_getter(self, prop: Property, fb_pou: POU, instance_state: dict) -> object:
        """Execute a property getter body and return the result."""
        engine = ExecutionEngine(
            pou=fb_pou,
            state=instance_state,
            clock_ms=self.clock_ms,
            pou_registry=self.pou_registry,
            data_type_registry=self.data_type_registry,
            enum_registry=self.enum_registry,
            pointer_table=self.pointer_table,
        )
        try:
            for network in prop.getter.networks:
                for stmt in network.statements:
                    engine._exec_stmt(stmt)
        except _ReturnSignal as ret:
            return ret.value
        return None

    _MISSING = object()  # sentinel for property setter cleanup

    def _exec_property_setter(self, prop: Property, fb_pou: POU, instance_state: dict, value: object) -> None:
        """Execute a property setter body with the given value."""
        # Inject value as prop_name (setter body uses the property name as var ref)
        old_val = instance_state.get(prop.name, self._MISSING)
        instance_state[prop.name] = value
        engine = ExecutionEngine(
            pou=fb_pou,
            state=instance_state,
            clock_ms=self.clock_ms,
            pou_registry=self.pou_registry,
            data_type_registry=self.data_type_registry,
            enum_registry=self.enum_registry,
            pointer_table=self.pointer_table,
        )
        try:
            for network in prop.setter.networks:
                for stmt in network.statements:
                    engine._exec_stmt(stmt)
        except _ReturnSignal:
            pass
        finally:
            # Clean up the injected property name if it wasn't part of the state
            if old_val is self._MISSING:
                instance_state.pop(prop.name, None)
            else:
                instance_state[prop.name] = old_val

    def _eval_bit_access(self, expr: BitAccessExpr) -> object:
        value = self._eval(expr.target)
        bit_index = expr.bit_index
        if bit_index < 0 or bit_index > 63:
            raise SimulationError(f"Bit index {bit_index} out of range (0..63)")
        return bool((int(value) >> bit_index) & 1)

    def _eval_array_access(self, expr: ArrayAccessExpr) -> object:
        array = self._eval(expr.array)
        if not isinstance(array, list):
            raise SimulationError(
                f"Cannot index into {type(array).__name__}"
            )
        indices = [int(self._eval(idx)) for idx in expr.indices]
        result = array
        for idx in indices:
            if not isinstance(result, list):
                raise SimulationError("Too many indices for array dimensions")
            if idx < 0 or idx >= len(result):
                raise SimulationError(
                    f"Array index {idx} out of bounds (0..{len(result) - 1})"
                )
            result = result[idx]
        return result

    def _eval_type_conversion(self, expr: TypeConversionExpr) -> object:
        value = self._eval(expr.source)
        return coerce_type(value, expr.target_type)

    def _eval_system_flag(self, expr: SystemFlagExpr) -> object:
        if expr.flag == SystemFlag.FIRST_SCAN:
            return self.state.get("__system_first_scan", False)
        raise SimulationError(f"Unknown system flag: {expr.flag}")

    def _eval_deref(self, expr: DerefExpr) -> object:
        if self.pointer_table is None:
            raise SimulationError(
                "Pointer dereference is not supported in simulation"
            )
        addr = self._eval(expr.pointer)
        if not isinstance(addr, (int, float)):
            raise SimulationError(
                f"Cannot dereference non-integer value: {type(addr).__name__}"
            )
        return self.pointer_table.read(int(addr))

    def _eval_substring(self, expr: SubstringExpr) -> object:
        s = self._eval(expr.string)
        if not isinstance(s, str):
            raise SimulationError(f"Substring requires a string, got {type(s).__name__}")
        if expr.single_char:
            idx = int(self._eval(expr.start))  # type: ignore[arg-type]
            return s[idx]
        start = int(self._eval(expr.start)) if expr.start is not None else None  # type: ignore[arg-type]
        end = int(self._eval(expr.end)) if expr.end is not None else None  # type: ignore[arg-type]
        return s[start:end]

    # Expression dispatch table
    _EXPR_DISPATCH: dict[str, Callable[[ExecutionEngine, Expression], object]] = {
        "literal": _eval_literal,
        "variable_ref": _eval_variable_ref,
        "binary": _eval_binary,
        "unary": _eval_unary,
        "function_call": _eval_function_call,
        "member_access": _eval_member_access,
        "deref": _eval_deref,
        "bit_access": _eval_bit_access,
        "array_access": _eval_array_access,
        "type_conversion": _eval_type_conversion,
        "substring": _eval_substring,
        "system_flag": _eval_system_flag,
    }

    # -----------------------------------------------------------------------
    # Write helpers
    # -----------------------------------------------------------------------

    def _write_target(self, target: Expression, value: object) -> None:
        """Write a value to an assignment target (variable, member, array, deref)."""
        if target.kind == "variable_ref":
            # Write-through for reference-bound variables
            current = self.state.get(target.name)
            if isinstance(current, _RefBinding) and not isinstance(value, _RefBinding):
                if self.pointer_table is None:
                    raise SimulationError(
                        f"Variable '{target.name}' is a reference binding "
                        f"but no pointer table available"
                    )
                self.pointer_table.write(current.target_addr, value)
            else:
                self.state[target.name] = value
        elif target.kind == "deref":
            if self.pointer_table is None:
                raise SimulationError(
                    "Pointer write requires pointer support "
                    "(use simulate() instead of raw ExecutionEngine)"
                )
            addr = self._eval(target.pointer)
            self.pointer_table.write(int(addr), value)
        elif target.kind == "member_access":
            struct = self._eval(target.struct)
            if isinstance(struct, dict):
                # Check for property setter
                result = self._find_property(target.struct, target.member)
                if result is not None and result[0].setter is not None:
                    self._exec_property_setter(result[0], result[1], struct, value)
                else:
                    struct[target.member] = value
            else:
                raise SimulationError(
                    f"Cannot write member '{target.member}' on {type(struct).__name__}"
                )
        elif target.kind == "bit_access":
            current = int(self._eval(target.target))
            bit_index = target.bit_index
            if bit_index < 0 or bit_index > 63:
                raise SimulationError(f"Bit index {bit_index} out of range (0..63)")
            if value:
                new_value = current | (1 << bit_index)
            else:
                new_value = current & ~(1 << bit_index)
            self._write_target(target.target, new_value)
        elif target.kind == "array_access":
            array = self._eval(target.array)
            indices = [int(self._eval(idx)) for idx in target.indices]
            container = array
            for idx in indices[:-1]:
                container = container[idx]
            container[indices[-1]] = value
        else:
            raise SimulationError(
                f"Unsupported assignment target kind: {target.kind}"
            )
