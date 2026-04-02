"""Source-map helpers for the ST exporter."""

from __future__ import annotations

import re
from typing import Union

from plx.model.pou import POU
from plx.model.project import Project


def _collect_variable_names(target: Union[Project, POU]) -> set[str]:
    """Collect all variable names from POU interfaces."""
    names: set[str] = set()
    pous = target.pous if isinstance(target, Project) else [target]
    for pou in pous:
        iface = pou.interface
        for var_list in (
            iface.input_vars,
            iface.output_vars,
            iface.inout_vars,
            iface.static_vars,
            iface.temp_vars,
            iface.constant_vars,
            iface.external_vars,
        ):
            for v in var_list:
                names.add(v.name)
    return names


_VAR_BLOCK_KEYWORDS = frozenset(
    {
        "VAR_INPUT",
        "VAR_OUTPUT",
        "VAR_IN_OUT",
        "VAR",
        "VAR_TEMP",
        "VAR CONSTANT",
        "VAR_GLOBAL",
        "VAR_EXTERNAL",
    }
)


def _build_source_map(st_text: str, variable_names: set[str]) -> list[dict]:
    """Scan ST text for variable references, return [{name, line, column}].

    Lines and columns are 1-indexed (matching Monaco editor conventions).
    Skips VAR declaration blocks, comment text, and de-duplicates per variable
    per line (first occurrence only).
    """
    if not variable_names:
        return []

    # Sort longest-first so the alternation doesn't short-circuit on prefixes
    sorted_names = sorted(variable_names, key=len, reverse=True)
    pattern = re.compile(r"\b(" + "|".join(re.escape(n) for n in sorted_names) + r")\b")

    entries: list[dict] = []
    in_var_block = False

    for line_num, line_text in enumerate(st_text.splitlines(), start=1):
        stripped = line_text.strip()

        # Track VAR declaration blocks -- skip them entirely
        if stripped in _VAR_BLOCK_KEYWORDS:
            in_var_block = True
            continue
        if stripped == "END_VAR":
            in_var_block = False
            continue
        if in_var_block:
            continue

        # Strip comment portion before matching
        comment_pos = line_text.find("//")
        searchable = line_text[:comment_pos] if comment_pos >= 0 else line_text

        # First occurrence of each variable name per line only
        seen_on_line: set[str] = set()
        for match in pattern.finditer(searchable):
            name = match.group(1)
            if name in seen_on_line:
                continue
            seen_on_line.add(name)
            entries.append(
                {
                    "name": name,
                    "line": line_num,
                    "column": match.start() + 1,
                }
            )
    return entries
