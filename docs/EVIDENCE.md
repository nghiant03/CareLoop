# Evidence sources and ingestion

Status: researched candidates and agreed direction, 2026-10-23. Sources have been
located; extraction, reference checks, and integrations are not yet implemented.
Food and participant datasets are documented separately in [DATA.md](DATA.md).

## General nutrition and life stages

- [Singapore RDA tables](https://www.healthhub.sg/well-being-and-lifestyle/food-diet-and-nutrition/recommended_dietary_allowances):
  age/sex/life-stage recommendations. Observed page review date: November 2022.
  Check references, footnotes, age boundaries, and additions versus total amounts.
- [My Healthy Plate](https://www.healthhub.sg/well-being-and-lifestyle/food-diet-and-nutrition/plan-your-meals-with-my-healthy-plate):
  food-group guidance and explanations, not a universal energy prescription.
- [Kids and teens](https://www.healthhub.sg/well-being-and-lifestyle/food-diet-and-nutrition/a-healthy-food-foundation-for-kids-and-teens):
  age-specific food-group guidance.
- [Pregnancy guide](https://www.healthhub.sg/well-being-and-lifestyle/personal-care/healthy-start-for-your-pregnancy):
  public guide/PDF and pregnancy nutrition material.
- [WHO healthy diet](https://www.who.int/news-room/fact-sheets/detail/healthy-diet):
  overview and discovery links to original guidelines.
- [WHO carbohydrates](https://www.who.int/publications/i/item/9789240073593) and
  [WHO sugars](https://www.who.int/publications/i/item/9789241549028):
  recommendations, populations, qualifications, and supporting evidence.

Energy-estimation formulas and weight-management methods still need dedicated
source selection. Numeric reference intakes, ceilings, ranges, and qualitative
guidance must remain distinct.

## Conditions and complications

- [HPB Lifestyle Prescriptions](https://www.primarycarepages.sg/healthier-sg/lifestyle-prescriptions):
  prediabetes/diabetes, hypoglycaemia risk, hypertension, lipid/CV-risk guidance,
  including meal timing and carbohydrate consistency.
- [ACE repository](https://www.ace-hta.gov.sg/healthcare-professionals/ace-repository-for-clinical-guidelines/):
  authoritative local discovery entry point; select nutrition-relevant sections.
- [ACE hypertension](https://www.ace-hta.gov.sg/healthcare-professionals/ace-repository-for-clinical-guidelines/hypertension-tailoring-the-management-plan-to-optimise-blood-pressure-control/)
  and [ACE lipids](https://www.ace-hta.gov.sg/healthcare-professionals/ace-repository-for-clinical-guidelines/lipid-management-focus-on-cardiovascular-risk/).
- [Healthier SG multimorbidity](https://www.primarycarepages.sg/healthier-sg/care-protocols/chronic-care-protocols/multimorbidity-diabetes-hypertension-and-hyperlipidaemia):
  interacting conditions and individualized kidney-related dietary management.
- [KDIGO 2024 CKD guideline](https://kdigo.org/wp-content/uploads/2024/03/KDIGO-2024-CKD-Guideline.pdf):
  protein, sodium, potassium considerations, and qualifications for stage, age,
  metabolic instability, frailty, and other patient circumstances.

Do not apply universal potassium restriction to CKD or adult protein rules to
children. Extract full applicability and exceptions. A source's availability does
not establish that required patient facts or food attributes are available.

## Loading and publication

1. Discover documents within approved authoritative domains, or accept reviewer
   URLs, PDFs, and pasted text. Present discoveries for selection/extraction.
2. Retain source content and metadata. Parse text, tables, headings, footnotes,
   and page/section references; report extraction failures explicitly.
3. Build linked searchable passages for chat and structured draft rules for
   computation. See [inference](INFERENCE.md) for hosted-model selection/budget.
4. Validate units, applicability, supporting passages, and conflicts. Model output
   must not activate itself as a published rule.
5. Reviewers edit/approve individual rules or selected source-batch members, then
   explicitly publish a versioned batch. One reviewer and self-approval suffice.
6. Patient proposals reference the published version and supporting rules;
   clinician completion/approval is a separate workflow.
7. On-demand refresh creates drafts and differences. Published changes and
   retirement flag affected patient targets; preserve historical explanations.

Audit who changed what, when, why, and source support. Missing evidence is not an
invitation to invent a numeric recommendation. Resolve conflicts through explicit
applicability and reviewer decisions, not automatic strictest-value selection.
