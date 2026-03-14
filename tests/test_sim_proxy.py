"""Tests for StructProxy — attribute-style dict access wrapper."""

import pytest

from plx.simulate._proxy import StructProxy


class TestStructProxyBasic:
    def test_getattr(self):
        d = {"x": 1, "y": 2.0, "name": "hello"}
        p = StructProxy(d)
        assert p.x == 1
        assert p.y == 2.0
        assert p.name == "hello"

    def test_setattr(self):
        d = {"x": 1, "y": 2.0}
        p = StructProxy(d)
        p.x = 42
        assert d["x"] == 42
        assert p.x == 42

    def test_setattr_unknown_field_raises(self):
        d = {"x": 1}
        p = StructProxy(d)
        with pytest.raises(AttributeError, match="no field 'z'"):
            p.z = 99

    def test_getattr_unknown_field_raises(self):
        d = {"x": 1}
        p = StructProxy(d)
        with pytest.raises(AttributeError, match="no field 'z'"):
            _ = p.z

    def test_getitem(self):
        d = {"x": 1}
        p = StructProxy(d)
        assert p["x"] == 1

    def test_setitem(self):
        d = {"x": 1}
        p = StructProxy(d)
        p["x"] = 99
        assert d["x"] == 99

    def test_contains(self):
        d = {"x": 1, "y": 2}
        p = StructProxy(d)
        assert "x" in p
        assert "z" not in p


class TestStructProxyNested:
    def test_nested_dict_returns_proxy(self):
        d = {"inner": {"a": 1, "b": 2}}
        p = StructProxy(d)
        inner = p.inner
        assert isinstance(inner, StructProxy)
        assert inner.a == 1

    def test_nested_setattr_mutates_original(self):
        d = {"inner": {"a": 1}}
        p = StructProxy(d)
        p.inner.a = 42
        assert d["inner"]["a"] == 42

    def test_deep_nesting(self):
        d = {"a": {"b": {"c": 99}}}
        p = StructProxy(d)
        assert p.a.b.c == 99


class TestStructProxyEquality:
    def test_eq_dict(self):
        d = {"x": 1, "y": 2}
        p = StructProxy(d)
        assert p == {"x": 1, "y": 2}
        assert p != {"x": 1}

    def test_eq_proxy(self):
        d = {"x": 1}
        p1 = StructProxy(d)
        p2 = StructProxy(d)
        assert p1 == p2

    def test_eq_different_data(self):
        p1 = StructProxy({"x": 1})
        p2 = StructProxy({"x": 2})
        assert p1 != p2

    def test_eq_non_dict(self):
        p = StructProxy({"x": 1})
        assert (p == 42) is False


class TestStructProxyDictProtocol:
    def test_keys(self):
        d = {"x": 1, "y": 2}
        p = StructProxy(d)
        assert set(p.keys()) == {"x", "y"}

    def test_values(self):
        d = {"x": 1, "y": 2}
        p = StructProxy(d)
        assert list(p.values()) == [1, 2]

    def test_items(self):
        d = {"x": 1, "y": 2}
        p = StructProxy(d)
        assert dict(p.items()) == {"x": 1, "y": 2}

    def test_len(self):
        p = StructProxy({"a": 1, "b": 2, "c": 3})
        assert len(p) == 3

    def test_iter(self):
        p = StructProxy({"a": 1, "b": 2})
        assert set(p) == {"a", "b"}

    def test_bool_nonempty(self):
        assert bool(StructProxy({"x": 1})) is True

    def test_bool_empty(self):
        assert bool(StructProxy({})) is False


class TestStructProxyIsinstance:
    def test_isinstance_dict(self):
        """StructProxy must pass isinstance(x, dict) for backward compat."""
        p = StructProxy({"x": 1})
        assert isinstance(p, dict)

    def test_type_is_still_structproxy(self):
        """type() returns StructProxy (not dict)."""
        p = StructProxy({"x": 1})
        assert type(p) is StructProxy


class TestStructProxyRepr:
    def test_repr(self):
        p = StructProxy({"x": 1})
        assert "StructProxy" in repr(p)
        assert "'x': 1" in repr(p)


class TestStructProxyMutationTransparency:
    """Verify that mutations through the proxy affect the original dict."""

    def test_setattr_reflects_in_dict(self):
        d = {"val": 0}
        p = StructProxy(d)
        p.val = 42
        assert d["val"] == 42

    def test_setitem_reflects_in_dict(self):
        d = {"val": 0}
        p = StructProxy(d)
        p["val"] = 42
        assert d["val"] == 42

    def test_dict_mutation_reflects_in_proxy(self):
        d = {"val": 0}
        p = StructProxy(d)
        d["val"] = 99
        assert p.val == 99

    def test_get_method(self):
        d = {"x": 1}
        p = StructProxy(d)
        assert p.get("x") == 1
        assert p.get("missing") is None
        assert p.get("missing", 42) == 42
