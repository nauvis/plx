"""Exception hierarchy for the plx framework.

All framework-specific exceptions inherit from ``PlxError``, which lets
users write ``except PlxError`` to catch any framework error while still
being able to target specific categories.
"""


class PlxError(Exception):
    """Base exception for all plx framework errors."""


class DeclarationError(PlxError):
    """Invalid variable declaration (wrong Field() options for the variable direction)."""

    def __init__(self, message: str, *, class_name: str | None = None):
        if class_name:
            message = f"[{class_name}] {message}"
        self.class_name = class_name
        super().__init__(message)


class DefinitionError(PlxError):
    """Invalid type or GVL definition (empty @struct, bad @enumeration member, etc.)."""


class ProjectAssemblyError(PlxError):
    """Error during project or task assembly (non-compiled POU, invalid task config)."""
