"""Modal dialog components for the NiceGUI viewer."""

from __future__ import annotations

__docformat__ = "google"

from .create_assignment import CreateAssignmentModal
from .delete_assignment import DeleteAssignmentModal
from .push import PushModal

__all__ = [
    "CreateAssignmentModal",
    "DeleteAssignmentModal",
    "PushModal",
]
