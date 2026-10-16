"""Select approval authority without bypassing lifecycle or scope checks."""

import os
from typing import Literal

AUTO_APPROVAL_ACTOR = "system:auto-approval (demo, not clinical)"


def approval_mode() -> Literal["auto", "clinician"]:
    """Default to the academic demo; reject invalid configuration before writes."""
    mode = os.environ.get("CARELOOP_APPROVAL_MODE", "auto")
    if mode not in {"auto", "clinician"}:
        raise ValueError("CARELOOP_APPROVAL_MODE must be auto or clinician")
    return mode
