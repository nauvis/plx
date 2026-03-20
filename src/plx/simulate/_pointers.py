"""Pointer and reference simulation support.

Provides an address table that maps integer "addresses" to variable
storage locations, enabling ADR(), pointer dereference (ptr^), __NEW,
__DELETE, REF=, and __ISVALIDREF simulation.

Addresses are assigned with large stride so pointer arithmetic
(ADR(x) + offset) produces addresses not in the table, which are
detected and rejected at dereference time.
"""

from __future__ import annotations

from ._values import SimulationError


# Null pointer value — matches PLC convention (0 = null).
NULL_PTR = 0

# Address layout:
#   0x1000_0000 .. 0x7FFF_FFFF  — variable addresses (assigned by ADR)
#   0x8000_0000 .. 0xFFFF_FFFF  — heap addresses (assigned by __NEW)
_VAR_BASE = 0x1000_0000
_HEAP_BASE = 0x8000_0000
_STRIDE = 1024  # gap between addresses — detects arithmetic


class _RefBinding:
    """Sentinel stored as a reference variable's value after REF= assignment.

    Distinguished from plain int so the engine can transparently follow
    references on read/write without confusing them with integer values.
    """

    __slots__ = ("target_addr",)

    def __init__(self, target_addr: int) -> None:
        self.target_addr = target_addr

    def __repr__(self) -> str:
        return f"_RefBinding(0x{self.target_addr:08X})"


# A binding is (container, key) where container[key] accesses the value.
# container is a dict or list; key is str (dict) or int (list).
_Binding = tuple[dict | list, str | int]


class PointerTable:
    """Maps integer addresses to variable storage locations.

    Each address points to a ``(container, key)`` pair so that reads
    do ``container[key]`` and writes do ``container[key] = value``.
    This works because Python dicts/lists are mutable containers.
    """

    def __init__(self) -> None:
        self._path_to_addr: dict[str, int] = {}
        self._addr_to_binding: dict[int, _Binding] = {}
        self._next_var_addr = _VAR_BASE
        self._next_heap_addr = _HEAP_BASE
        self._freed: set[int] = set()
        self._heap_addrs: set[int] = set()

    def get_or_assign(
        self,
        path: str,
        container: dict | list,
        key: str | int,
    ) -> int:
        """Return a stable address for the variable at *path*.

        If the variable already has an address, return it (updating the
        binding if the container changed). Otherwise assign a new one.

        Parameters
        ----------
        path : str
            Dot-separated variable path (e.g. ``"fb_inst.output"``).
        container : dict or list
            The mutable container that holds the variable's value.
        key : str or int
            The key within *container* where the value is stored.

        Returns
        -------
        int
            The integer address assigned to this variable.
        """
        addr = self._path_to_addr.get(path)
        if addr is not None:
            # Update binding (container may have been reallocated)
            self._addr_to_binding[addr] = (container, key)
            return addr
        addr = self._next_var_addr
        self._next_var_addr += _STRIDE
        self._path_to_addr[path] = addr
        self._addr_to_binding[addr] = (container, key)
        return addr

    def read(self, addr: int) -> object:
        """Read the value at *addr*.

        Parameters
        ----------
        addr : int
            The pointer address to dereference.

        Returns
        -------
        object
            The value stored at the address.

        Raises
        ------
        SimulationError
            If *addr* is ``0`` (null pointer dereference), refers to
            freed heap memory (use after free), or is not in the
            address table (e.g. from unsupported pointer arithmetic).
        """
        if addr == NULL_PTR:
            raise SimulationError("Null pointer dereference (address 0)")
        if addr in self._freed:
            raise SimulationError(
                f"Use after free: address 0x{addr:08X} has been deleted"
            )
        binding = self._addr_to_binding.get(addr)
        if binding is None:
            raise SimulationError(
                f"Invalid pointer address 0x{addr:08X} — "
                f"pointer arithmetic is not supported in simulation"
            )
        container, key = binding
        return container[key]

    def write(self, addr: int, value: object) -> None:
        """Write *value* to the location at *addr*.

        Parameters
        ----------
        addr : int
            The pointer address to write to.
        value : object
            The value to store.

        Raises
        ------
        SimulationError
            If *addr* is ``0`` (null pointer write), refers to freed
            heap memory (write after free), or is not in the address
            table (e.g. from unsupported pointer arithmetic).
        """
        if addr == NULL_PTR:
            raise SimulationError("Null pointer write (address 0)")
        if addr in self._freed:
            raise SimulationError(
                f"Write after free: address 0x{addr:08X} has been deleted"
            )
        binding = self._addr_to_binding.get(addr)
        if binding is None:
            raise SimulationError(
                f"Invalid pointer address 0x{addr:08X} — "
                f"pointer arithmetic is not supported in simulation"
            )
        container, key = binding
        container[key] = value

    def heap_alloc(self, default_value: object) -> int:
        """Allocate a heap entry with *default_value*.

        Parameters
        ----------
        default_value : object
            The initial value stored at the new heap address.

        Returns
        -------
        int
            The newly allocated heap address.
        """
        addr = self._next_heap_addr
        self._next_heap_addr += _STRIDE
        # Store in an internal dict so the binding has a mutable container
        self._heap_addrs.add(addr)
        # Create a single-entry dict as the container
        store: dict[str, object] = {"_v": default_value}
        self._addr_to_binding[addr] = (store, "_v")
        return addr

    def heap_free(self, addr: int) -> None:
        """Free a heap-allocated entry at *addr*.

        Parameters
        ----------
        addr : int
            The heap address to free.

        Raises
        ------
        SimulationError
            If *addr* is ``0`` (null pointer), was already freed
            (double free), or was not allocated by ``__NEW`` (only
            heap memory can be freed).
        """
        if addr == NULL_PTR:
            raise SimulationError("Cannot __DELETE null pointer (address 0)")
        if addr in self._freed:
            raise SimulationError(
                f"Double free: address 0x{addr:08X} already deleted"
            )
        if addr not in self._heap_addrs:
            raise SimulationError(
                f"Cannot __DELETE address 0x{addr:08X} — "
                f"not allocated by __NEW (only heap memory can be freed)"
            )
        self._freed.add(addr)
        # Remove the binding so future reads/writes fail
        self._addr_to_binding.pop(addr, None)

    def is_valid(self, addr: int) -> bool:
        """Check if *addr* is a valid, non-freed address.

        Parameters
        ----------
        addr : int
            The address to check.

        Returns
        -------
        bool
            ``True`` if *addr* is non-null, has not been freed, and
            exists in the address table; ``False`` otherwise.
        """
        if addr == NULL_PTR:
            return False
        if addr in self._freed:
            return False
        return addr in self._addr_to_binding
