"""Select approval policy for subsequent rule runs."""

import os
import threading
from typing import Literal, cast

ApprovalMode = Literal["auto", "clinician"]
APPROVAL_MODES: tuple[ApprovalMode, ...] = ("auto", "clinician")

AUTO_APPROVAL_ACTOR = "system:auto-approval (demo, not clinical)"

_override_lock = threading.Lock()
_runtime_override: ApprovalMode | None = None


def configured_approval_mode() -> ApprovalMode:
    mode = os.environ.get("CARELOOP_APPROVAL_MODE", "auto")
    if mode not in APPROVAL_MODES:
        raise ValueError("CARELOOP_APPROVAL_MODE must be auto or clinician")
    return cast(ApprovalMode, mode)


def approval_mode() -> ApprovalMode:
    """Validate configured policy even while a process local override is active."""
    configured = configured_approval_mode()
    with _override_lock:
        return _runtime_override or configured


def set_approval_mode(mode: str) -> ApprovalMode:
    """Change policy only for subsequent rule runs in this process."""
    global _runtime_override
    if mode not in APPROVAL_MODES:
        raise ValueError("approval mode must be auto or clinician")
    configured_approval_mode()
    with _override_lock:
        _runtime_override = cast(ApprovalMode, mode)
    return approval_mode()


def reset_approval_mode() -> ApprovalMode:
    global _runtime_override
    with _override_lock:
        _runtime_override = None
    return approval_mode()
