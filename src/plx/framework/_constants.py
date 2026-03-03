"""Canonical set of IEC 61131-3 standard function block type names.

Zero framework imports — just frozen data.  Import from here instead of
defining the set inline so all modules stay in sync.
"""

STANDARD_FB_TYPES: frozenset[str] = frozenset({
    "TON", "TOF", "TP", "RTO",
    "R_TRIG", "F_TRIG",
    "CTU", "CTD", "CTUD",
    "SR", "RS",
})
