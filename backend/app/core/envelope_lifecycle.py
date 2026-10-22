"""Apply revision checked envelope transitions."""

from datetime import UTC, datetime

from backend.app.core.approval_gate import put_envelope
from backend.app.core.persistence import EnvelopeConflictError
from shared.envelope_schema import (
    CitationSource,
    EnvelopeStatus,
    ExclusionFlag,
    NutrientConstraint,
    NutrientEnvelope,
    RuleFire,
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
    """Persist a revision checked copy without changing the content version."""
    updated = _transition_copy(envelope, expected_revision)
    _require_eligible(updated)
    if not updated.targets:
        raise EnvelopeScopeError(updated)
    updated.status = EnvelopeStatus.APPROVED
    updated.approved_by = approved_by
    updated.approved_at = datetime.now(UTC)
    if notes is not None:
        updated.notes = notes
    return put_envelope(updated)


def edit(envelope: NutrientEnvelope, *, edited_by: str,
         targets: list[NutrientConstraint] | None = None,
         exclusions: list[ExclusionFlag] | None = None, notes: str | None = None,
         expected_revision: int | None = None) -> NutrientEnvelope:
    """Every edit clears approval. Replacement targets receive clinician provenance."""
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
        rule_id="CLINICIAN-EDIT", fired_at=datetime.now(UTC),
        patient_summary=f"clinician edit by {edited_by}", action_summary=action,
        priority=0, citation=citation,
    ))
    # Replacement values belong to the clinician rather than the original guideline.
    if targets is not None:
        attach_provenance(updated, author=edited_by, citation=citation)
    return put_envelope(updated)


def reject(envelope: NutrientEnvelope, *, reason: str | None = None,
           expected_revision: int | None = None) -> NutrientEnvelope:
    """Clear approval without changing the content version."""
    updated = _transition_copy(envelope, expected_revision)
    updated.status = EnvelopeStatus.REJECTED
    updated.approved_by = None
    updated.approved_at = None
    if reason:
        updated.notes = reason
    return put_envelope(updated)
