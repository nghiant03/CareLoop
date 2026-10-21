---
name: CareLoop
description: Clinical blue wayfinding for evidence-led nutrition review.
colors:
  paper: "#f3f6fa"
  panel: "#eaf0f6"
  card: "#ffffff"
  ink: "#172b40"
  ink-2: "#354c63"
  ink-3: "#52677d"
  rule: "#d9e2ec"
  rule-2: "#aabccc"
  shell: "#153650"
  flag: "#b3352b"
  flag-bg: "#f9e9e5"
  flag-rule: "#e3b8ae"
  ok: "#1f6f4a"
  ok-bg: "#e6f0e7"
  ok-rule: "#b3d2ba"
  warn: "#9a5b12"
  warn-bg: "#f8efdd"
  warn-rule: "#e0c79b"
  line: "#175d99"
  line-bg: "#e7f1fb"
  line-rule: "#a6c7e7"
typography:
  headline:
    fontFamily: '"Public Sans", ui-sans-serif, system-ui, sans-serif'
    fontSize: "1.5rem"
    fontWeight: 700
    lineHeight: "calc(2 / 1.5)"
    letterSpacing: "-0.025em"
  title:
    fontFamily: '"Public Sans", ui-sans-serif, system-ui, sans-serif'
    fontSize: "1.25rem"
    fontWeight: 700
    lineHeight: "calc(1.75 / 1.25)"
  body:
    fontFamily: '"Public Sans", ui-sans-serif, system-ui, sans-serif'
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.5
  body-small:
    fontFamily: '"Public Sans", ui-sans-serif, system-ui, sans-serif'
    fontSize: "0.875rem"
    fontWeight: 400
    lineHeight: "calc(1.25 / 0.875)"
  label:
    fontFamily: '"Public Sans", ui-sans-serif, system-ui, sans-serif'
    fontSize: "0.8125rem"
    fontWeight: 600
    letterSpacing: "0"
  status:
    fontFamily: '"Public Sans", ui-sans-serif, system-ui, sans-serif'
    fontSize: "0.75rem"
    fontWeight: 600
    letterSpacing: "0"
  data:
    fontFamily: '"Roboto Mono", ui-monospace, "SFMono-Regular", Menlo, monospace'
rounded:
  status: "4px"
  control: "6px"
  panel: "8px"
spacing:
  unit: "0.25rem"
  compact: "0.5rem"
  control: "0.75rem"
  standard: "1rem"
  summary: "1.25rem"
  section: "1.5rem"
  wide: "2rem"
components:
  button-primary:
    backgroundColor: "{colors.line}"
    textColor: "{colors.card}"
    rounded: "{rounded.control}"
    padding: "0.5rem 1rem"
  button-approve:
    backgroundColor: "{colors.ok}"
    textColor: "{colors.card}"
    rounded: "{rounded.control}"
    padding: "0.5rem 1rem"
  button-danger:
    backgroundColor: "{colors.card}"
    textColor: "{colors.flag}"
    rounded: "{rounded.control}"
    padding: "0.5rem 1rem"
  button-danger-hover:
    backgroundColor: "{colors.flag-bg}"
  button-ghost:
    backgroundColor: "{colors.card}"
    textColor: "{colors.ink-2}"
    rounded: "{rounded.control}"
    padding: "0.5rem 1rem"
  button-ghost-hover:
    backgroundColor: "{colors.panel}"
  field:
    backgroundColor: "{colors.card}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "0.5rem 0.75rem"
    width: "100%"
  flag-warn:
    backgroundColor: "{colors.warn-bg}"
    textColor: "{colors.warn}"
    typography: "{typography.status}"
    rounded: "{rounded.status}"
    padding: "0.125rem 0.5rem"
  panel:
    backgroundColor: "{colors.card}"
    rounded: "{rounded.panel}"
  workspace-nav:
    textColor: "#d2e2f0"
    padding: "0.5rem 0.875rem 0.75rem"
  rule-selected:
    backgroundColor: "{colors.line-bg}"
    rounded: "{rounded.status}"
    padding: "1rem 0.75rem"
---

# Design System: CareLoop

## Overview

**Creative North Star: "Clinical wayfinding"**

CareLoop uses hospital wayfinding-inspired navigation above light clinical working surfaces. Deep blue identifies the workspace; readable evidence, explicit state text and familiar controls guide decisions. The character is clear, clinical and factual, with restrained density rather than report decoration.

This records the user-approved replacement of the warm lab-report design. The implemented source is `frontend/src/index.css`, the shared workspace and page headers, and the Knowledge Review workspace; `PRODUCT.md` and `docs/UI-DIRECTION.md` establish the confirmed direction.

**Key Characteristics:**
- Deep navy navigation, blue selection and cool neutral reading surfaces.
- Public Sans for reading; Roboto Mono and tabular numerals for data.
- Modest corners, fine borders and explicit state text.
- Evidence-first review with a persistent list/detail selection.

## Colors

### Primary

Wayfinding blue (`line`) marks actions, links, selection and keyboard focus. Its light fill and border companions distinguish selected records and informational notices. Deep navy (`shell`) anchors the branded workspace header.

### Secondary

Clinical green (`ok`) identifies approval actions and successful states. Amber (`warn`) signals caution or incomplete review; red (`flag`) identifies errors, rejection and destructive actions. Each semantic family has its own light background and border. State words accompany color.

### Neutral

Cool ground (`paper`) sits beneath white working surfaces (`card`) and lightly tinted supporting regions (`panel`). Slate text steps from primary `ink` through `ink-2` to supporting `ink-3`. `rule` separates content; `rule-2` strengthens control outlines and table headings.

**The Explicit State Rule.** Pair semantic color with visible state text; approval color must not imply human review or publication.

## Typography

Public Sans carries headings, prose, controls and sentence-case labels. Roboto Mono distinguishes identifiers and measurements through the data treatment; tabular numerals also appear in the draft summary without changing its sans-serif family.

The frontmatter records the page headline, rule-detail title, body, compact body, label and status roles. Page headlines are compact and bold, not oversized display typography. Evidence quotations use body size with relaxed line-height (1.625) and a readable measure (65ch). Supporting page copy uses a maximum width of 42rem. The wordmark uses Public Sans (1.375rem, 700, -0.035em tracking).

**The Reading First Rule.** Keep prose and navigation in Public Sans; reserve the mono treatment for data and identifiers.

## Layout

The shared header and Knowledge Review content align within an 80rem maximum width. Header contents wrap with explicit spacing; the main review surface uses horizontal gutters of 1rem, increasing to 1.5rem at 40rem and 2rem at 64rem. The spacing vocabulary follows the built quarter-rem unit.

Knowledge Review places a bordered page header above disclosure, draft summary and section navigation. Rules use a two-column grid: a 240–300px browser and a flexible detail area, separated by 1.5rem. The browser scrolls within 65vh; the detail area uses 1.5rem padding. Source evidence precedes mappings and expandable provenance. Decision entry has its own section.

At widths up to 767px, the review grid stacks, the rule list is capped at 18rem, detail padding becomes 1rem, section buttons wrap into approximately two columns, and page-context text hides. Workspace navigation wraps onto a full-width row. Long identifiers, source URLs and records wrap rather than forcing the detail column wider.

## Elevation & Depth

The documented shared surfaces are flat: borders, contrasting fills and spacing establish hierarchy without box shadows. Navy navigation creates the strongest tonal boundary. Selection combines a light blue fill and border in the rule browser; active navigation uses a contrasting fill and bottom marker.

## Shapes

Panels use the panel radius; fields, notices and buttons use the control radius; flags and selectable rule rows use the status radius. Fine one-pixel borders define surfaces and fields. Navigation remains rectilinear, with a three-pixel active underline. Avoid turning these modest corners into pill-shaped primary controls.

## Components

### Buttons

Bordered, legible actions use compact body size and semibold weight. Primary blue and approval green brighten on hover; outlined danger actions gain a pale red fill, and neutral actions gain the panel fill. Controls have a minimum height of 42px, increasing to 48px for coarse pointers. Disabled buttons show a not-allowed cursor and half opacity.

### Inputs / Fields

White fields have stronger neutral borders, the control radius and compact body text. Focus changes the border to blue; the shared keyboard-focus outline is two pixels with a two-pixel offset. Disabled fields use the panel fill. The review decision form explicitly enlarges its text fields to body size and at least 48px height.

### Chips

Small bordered status flags use semantic foreground, pale background and matching border. Labels state the condition: for example, awaiting review, quote missing or a recorded decision. They are status text, not substitute buttons.

### Cards / Containers

White panels and tinted panels share thin neutral borders and modest rounding. Padding belongs to the content context: draft summaries use the summary spacing, filters use standard spacing, and evidence detail uses section spacing. A bare panel does not impose a universal padding value.

### Navigation

The branded header pairs the CareLoop wordmark with a workspace label. Main links have a 44px minimum height. Active links use a lighter navy fill, white text and a pale blue underline; focus uses a light blue outline against the dark shell. Review-section buttons have a 48px minimum height and a blue underline plus blue text when selected.

### Evidence review

The searchable rule browser exposes a persistent “Selected” label alongside its blue selected-row treatment. The detail heading repeats the rule ID. Source quotations and source links lead; mapping details and provenance follow. Draft status and warnings stay explicit, including unpublished knowledge and revision-bound decisions.

### Tables and loading

Tables use tinted headers, compact sans-serif labels, horizontal and vertical rules, and a tinted row hover. Data cells use tabular mono where requested by the data treatment. Loading uses a thin scanning line; reduced-motion preference replaces its animation with a static, full-width low-opacity line.

## Do's and Don'ts

### Do:
- **Do** use the navy shell and cool light surfaces to orient clinical work.
- **Do** pair selection and status colors with visible labels or markers.
- **Do** keep evidence readable and let identifiers and URLs wrap.
- **Do** retain visible keyboard focus and coarse-pointer control sizing.

### Don't:
- **Don't** restore warm paper or lab-report decoration as the shared visual identity.
- **Don't** use mono typography for general reading or navigation.
- **Don't** make approval styling imply human review, publication or clinical readiness.
