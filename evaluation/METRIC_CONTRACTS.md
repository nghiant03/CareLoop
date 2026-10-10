# Evaluation metric compatibility

These corrections apply to newly computed results. Historical `results.json`
and `EVALUATION.md` are not rewritten automatically.

- **Q1 traceability** matches cited actions by nutrient, kind, and final value
  within trace-rounding tolerance. Matching may credit a superseded action.
  This is not exact constraint authorship or semantic evidence entailment.
- **Q3 soft aims**: `soft_aims_by_constraint` is the lossless map keyed by
  `nutrient:kind`. MIN entries report worst-day shortfall; TARGET entries report
  mean daily absolute distance. Both use original approved aims, including
  when the solver relaxes a MIN floor. `soft_aims` remains the legacy
  nutrient-keyed, last-aim-wins projection for older readers. Its TARGET
  `mean_distance` now measures mean absolute distance, not distance from the
  mean intake; the old artifact cannot recover this correction from that field
  alone. Consumers needing every aim should prefer the new map, and treat an
  absent map in historical results as incomplete rather than inventing aims.
- **Q4 violations**: `violation_rate` retains its numeric field/type but stores
  the exact fraction of violating runs. Verdicts compare this unrounded value
  with zero. Historical rounded rates cannot prove absence of violations;
  recompute from the source benchmark rows when a verdict is needed.
- **Q5 grounding metadata**: `claim_sources_consistent` names the source-identity,
  applicability, and structured-answer-coverage check. `all_claims_supported`
  is retained as an equal-valued serialized alias. The callable
  `_claims_supported` remains an alias of `_claim_sources_consistent` for
  existing callers. Neither spelling proves arbitrary prose entailment.
- **Q6 cross-aim gaps**: per-aim `mean_daily_shortfall` retains the nutrient's
  own unit (kcal/g/mg), including two-sided TARGET gaps. Plan and pooled
  summaries use `mean_daily_rel_shortfall_pct`, the mean of per-aim daily
  gap/aim percentages. An aim at or below the evaluator's EPS has relative
  gap zero, consistently with the existing worst-day metric. The old pooled `mean_daily_shortfall`
  mixed incompatible units and is not an alias of the new metric. The report
  ignores that old pooled field and renders the new column as `n/a` when
  missing; no conversion from historical mixed-unit values is valid.
