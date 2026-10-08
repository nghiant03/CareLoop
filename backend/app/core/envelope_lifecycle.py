"""Clinician transitions over durable, revision-checked envelope snapshots.

Each transition persists and returns a deep copy, leaving its input untouched.
Successful writes advance ``lifecycle_revision``. ``expected_revision``, when
supplied, must match the input snapshot's revision or ``EnvelopeConflictError``
is raised. Persistence always checks that snapshot against the durable revision,
even when the client token is omitted. A conflict requires reloading and review
before retrying; omitting the token cannot detect changes since a client's view
if the caller has already loaded a newer snapshot.
"""

from datetime import datetime, timezone

from backend.app.core.approval_gate import put_envelope
from backend.app.core.persistence import EnvelopeConflictError
from shared.envelope_schema import (
    CitationSource, EnvelopeStatus, ExclusionFlag, NutrientConstraint,
    NutrientEnvelope, RuleFire,
)
from shared.provenance import attach_provenance


class EnvelopeScopeError(Exception):
    def __init__(self, envelope: NutrientEnvelope):
        self.envelope = envelope
        super().__init__("Rejected or out-of-scope envelopes cannot be edited or approved.")


def _transition_copy(envelope: NutrientEnvelope, expected_revision: int | None) -> NutrientEnvelope:
    if expected_revision is not None and expected_revision != envelope.lifecycle_revision:
        raise EnvelopeConflictError(envelope.envelope_id)
    return envelope.model_copy(deep=True)


def _require_eligible(envelope: NutrientEnvelope) -> None:
    if not envelope.scope_eligible or envelope.status == EnvelopeStatus.REJECTED:
        raise EnvelopeScopeError(envelope)


def approve(envelope: NutrientEnvelope, *, approved_by: str, notes: str | None = None,
            expected_revision: int | None = None) -> NutrientEnvelope:
    """Persist an APPROVED copy with reviewer and UTC approval time.

    Raise ``EnvelopeScopeError`` for rejected, scope-ineligible, or targetless
    inputs. ``notes=None`` preserves existing notes; content version is unchanged.
    Copy ownership and revision conflicts follow the module's transition contract.
    """
    updated = _transition_copy(envelope, expected_revision)
    _require_eligible(updated)
    if not updated.targets:
        raise EnvelopeScopeError(updated)
    updated.status = EnvelopeStatus.APPROVED
    updated.approved_by = approved_by
    updated.approved_at = datetime.now(timezone.utc)
    if notes is not None:
        updated.notes = notes
    return put_envelope(updated)


def edit(envelope: NutrientEnvelope, *, edited_by: str,
         targets: list[NutrientConstraint] | None = None,
         exclusions: list[ExclusionFlag] | None = None, notes: str | None = None,
         expected_revision: int | None = None) -> NutrientEnvelope:
    """Persist an EDITED copy, clear approval, and increment the content version.

    Raise ``EnvelopeScopeError`` for rejected or scope-ineligible inputs. ``None``
    preserves a field; supplied target/exclusion lists replace it in full (empty
    lists clear it). Every call appends a clinician-edit trace, even for notes-only
    edits; replacement targets receive clinician provenance. Copy ownership and
    revision conflicts follow the module's transition contract.
    """
    updated = _transition_copy(envelope, expected_revision)
    _require_eligible(updated)
    if targets is not None:
        updated.targets = [target.model_copy(deep=True) for target in targets]
    if exclusions is not None:
        updated.exclusions = [flag.model_copy(deep=True) for flag in exclusions]
    if notes is not None:
        updated.notes = notes
    updated.status = EnvelopeStatus.EDITED
    updated.approved_by = None
    updated.approved_at = None
    updated.version += 1

    if targets is not None:
        values = "; ".join(
            f"set {t.nutrient.value} {t.kind.value} = {t.value:g} {t.unit}" for t in targets
        )
        action = f"clinician override: targets replaced ({values or 'no constraints'})"
    else:
        action = "clinician override: targets unchanged"
    if exclusions is not None:
        action += f"; exclusions replaced ({len(exclusions)} entries)"
    citation = CitationSource(guideline="clinician override", section="clinician edit", rule_id="CLINICIAN-EDIT")
    updated.fired_rules.append(RuleFire(
        rule_id="CLINICIAN-EDIT", fired_at=datetime.now(timezone.utc),
        patient_summary=f"clinician edit by {edited_by}", action_summary=action,
        priority=0, citation=citation,
    ))
    # A replacement's values belong to the clinician, not the original guideline.
    if targets is not None:
        attach_provenance(updated, author=edited_by, citation=citation)
    return put_envelope(updated)


def reject(envelope: NutrientEnvelope, *, reason: str | None = None,
           expected_revision: int | None = None) -> NutrientEnvelope:
    """Persist a REJECTED copy and clear approval without changing content version.

    A nonempty reason replaces notes. Any input status or scope eligibility is
    accepted. Copy ownership and revision conflicts follow the module's
    transition contract.
    """
    updated = _transition_copy(envelope, expected_revision)
    updated.status = EnvelopeStatus.REJECTED
    updated.approved_by = None
    updated.approved_at = None
    if reason:
        updated.notes = reason
    return put_envelope(updated)
