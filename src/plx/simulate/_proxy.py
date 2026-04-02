"""StructProxy: attribute-style access wrapper for dict-backed struct values.

Returned by ``SimulationContext.__getattr__`` when a variable's current
value is a ``dict``.  The proxy is a *read-path wrapper only* — the
``ExecutionEngine`` never sees proxies; it always operates on the
underlying dicts.
"""

from __future__ import annotations

from plx.simulate._values import _coerce_input_value


class StructProxy:
    """Wraps a plain dict to provide ``proxy.field`` attribute access.

    Recursive — nested dicts are themselves wrapped on access so that
    ``ctx.recipe.nested.field`` chains work.

    The proxy is transparent for comparisons: ``proxy == {"a": 1}``
    compares the underlying dict.
    """

    __slots__ = ("_dict",)

    def __init__(self, d: dict) -> None:
        object.__setattr__(self, "_dict", d)

    # Make isinstance(proxy, dict) return True.  CPython's isinstance()
    # checks obj.__class__ as a fallback after type(obj), so reporting
    # dict here keeps StructProxy transparent for code that guards on
    # ``isinstance(val, dict)``.
    @property  # type: ignore[override]
    def __class__(self):
        return dict

    # -- attribute access --------------------------------------------------

    def __getattr__(self, name: str) -> object:
        d = object.__getattribute__(self, "_dict")
        try:
            val = d[name]
        except KeyError:
            raise AttributeError(f"Struct has no field '{name}'. Available: {sorted(d.keys())}") from None
        if isinstance(val, dict):
            return StructProxy(val)
        return val

    def __setattr__(self, name: str, value: object) -> None:
        d = object.__getattribute__(self, "_dict")
        if name in d:
            d[name] = _coerce_input_value(value)
        else:
            raise AttributeError(f"Struct has no field '{name}'. Available: {sorted(d.keys())}")

    # -- dict-style access (still works) -----------------------------------

    def __getitem__(self, key: str) -> object:
        d = object.__getattribute__(self, "_dict")
        val = d[key]
        if isinstance(val, dict):
            return StructProxy(val)
        return val

    def __setitem__(self, key: str, value: object) -> None:
        d = object.__getattribute__(self, "_dict")
        d[key] = _coerce_input_value(value)

    def __contains__(self, key: object) -> bool:
        d = object.__getattribute__(self, "_dict")
        return key in d

    # -- dict protocol (for serialization/iteration) -----------------------

    def keys(self):
        return object.__getattribute__(self, "_dict").keys()

    def values(self):
        return object.__getattribute__(self, "_dict").values()

    def items(self):
        return object.__getattribute__(self, "_dict").items()

    def get(self, key: str, default: object = None) -> object:
        d = object.__getattribute__(self, "_dict")
        return d.get(key, default)

    def __len__(self) -> int:
        return len(object.__getattribute__(self, "_dict"))

    def __iter__(self):
        return iter(object.__getattribute__(self, "_dict"))

    # -- comparison --------------------------------------------------------

    def __eq__(self, other: object) -> bool:
        d = object.__getattribute__(self, "_dict")
        if isinstance(other, StructProxy):
            return d == object.__getattribute__(other, "_dict")
        if isinstance(other, dict):
            return d == other
        return NotImplemented

    def __ne__(self, other: object) -> bool:
        result = self.__eq__(other)
        if result is NotImplemented:
            return result
        return not result

    # -- repr --------------------------------------------------------------

    def __repr__(self) -> str:
        d = object.__getattribute__(self, "_dict")
        return f"StructProxy({d!r})"

    def __bool__(self) -> bool:
        return bool(object.__getattribute__(self, "_dict"))
