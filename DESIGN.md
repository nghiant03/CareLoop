---
name: CareLoop
description: Clinical nutrition reporting UI styled as a laboratory report — paper, ink, hairline rules, and state-only color.
colors:
  paper: "#FBFAF6"
  panel: "#F4F2EA"
  card: "#FFFFFF"
  ink: "#17140F"
  ink-soft: "#453F35"
  ink-mute: "#6F6759"
  rule: "#E3E0D3"
  rule-strong: "#C8C3B0"
  flag: "#B3352B"
  flag-bg: "#F9E9E5"
  flag-rule: "#E3B8AE"
  ok: "#1F6F4A"
  ok-bg: "#E6F0E7"
  ok-rule: "#B3D2BA"
  warn: "#9A5B12"
  warn-bg: "#F8EFDD"
  warn-rule: "#E0C79B"
  line: "#1D4ED8"
  line-bg: "#E7EDFB"
  line-rule: "#B9C8EF"
typography:
  display:
    fontFamily: "Public Sans, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1.5rem"
    fontWeight: 700
    lineHeight: 1.2
    letterSpacing: "-0.02em"
  body:
    fontFamily: "Public Sans, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: "normal"
  label:
    fontFamily: "Roboto Mono, ui-monospace, Menlo, monospace"
    fontSize: "0.6875rem"
    fontWeight: 500
    lineHeight: 1.4
    letterSpacing: "0.14em"
  data:
    fontFamily: "Roboto Mono, ui-monospace, Menlo, monospace"
    fontSize: "0.875rem"
    fontWeight: 500
    lineHeight: 1.4
    letterSpacing: "normal"
rounded:
  report: "2px"
spacing:
  sm: "8px"
  md: "16px"
  lg: "24px"
components:
  button-primary:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.paper}"
    rounded: "{rounded.report}"
    padding: "8px 16px"
  button-approve:
    backgroundColor: "{colors.ok}"
    textColor: "#FFFFFF"
    rounded: "{rounded.report}"
    padding: "8px 16px"
  button-danger:
    backgroundColor: "{colors.card}"
    textColor: "{colors.flag}"
    rounded: "{rounded.report}"
    padding: "8px 16px"
  button-ghost:
    backgroundColor: "{colors.card}"
    textColor: "{colors.ink-soft}"
    rounded: "{rounded.report}"
    padding: "8px 16px"
  field:
    backgroundColor: "{colors.card}"
    textColor: "{colors.ink}"
    rounded: "{rounded.report}"
    padding: "8px 12px"
  flag-chip:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.ink-soft}"
    rounded: "{rounded.report}"
    padding: "2px 8px"
  panel-card:
    backgroundColor: "{colors.card}"
    textColor: "{colors.ink}"
    rounded: "{rounded.report}"
    padding: "20px"
---

# Design System: CareLoop

## Overview

**Creative North Star: "The Lab Report"**

CareLoop's interface is the laboratory report for a clinical nutrition trial: paper-white ground, ink text, hairline rules, and squared corners. The reader is an evaluator or clinician scanning for values, limits, and provenance, so the system behaves like a printed analytical report — everything is ruled, aligned, and tabulated, and nothing decorates.

Color is rationed to meaning. Neutrals carry structure; four state hues (flag red, caution amber, verified green, interactive blue) carry status and nothing else. A screen that uses red for anything other than a hard limit or alert has broken the system.

Depth comes from the rule, not the shadow. Hierarchy is weight, scale, and hairlines — patient rosters, analyte tables, and rule traces are all the same ruled paper at different densities.

**Key Characteristics:**
- Paper ground (#FBFAF6) with white ruled panels and a warm panel tint for recessed areas
- Hairline borders (1px, #E3E0D3) as the only container language; squared 2px corners
- Roboto Mono uppercase microcopy for report codes, column heads, IDs, and flags
- All measured values in tabular mono; every value is read against its reference range
- State hues only: red = hard limit/alert, amber = soft gap/caution, green = verified/compliant, blue = interactive

## Colors

The palette is paper and ink with four reserved state hues; every tinted background is the state hue's own wash with a matching rule color.

### Primary
- **Report Ink** (#17140F): headings, primary buttons, active navigation, measured-value emphasis. The authority color of the report.

### State hues
- **Flag Red** (#B3352B): hard ceilings, hard violations, alerts, reject actions, the forbidden region of a range bar. Never decoration.
- **Caution Amber** (#9A5B12): soft floors and gaps, relaxation notices, pending/proposed states, manual-entry warnings.
- **Verified Green** (#1F6F4A): approved envelopes, compliant days, on-track readings, the approve action.
- **Interaction Blue** (#1D4ED8): links, focus rings, selected-row tint. It marks interactivity, not status.

### Neutral
- **Report Paper** (#FBFAF6): the application ground.
- **Panel Tint** (#F4F2EA): recessed areas — range-bar tracks, empty states, recorded detail blocks.
- **Card White** (#FFFFFF): working surfaces and tables.
- **Soft Ink** (#453F35): secondary text and ghost-button labels.
- **Muted Ink** (#6F6759): captions, units, placeholder text (5.4:1 on paper — the floor for all secondary text).
- **Hairline** (#E3E0D3): row and container rules; **Strong Hairline** (#C8C3B0): header rules, field borders, table column separations.

### Named Rules
**The State-Only Hue Rule.** Hue answers "what state is this?" — never "what section is this?" Section identity is mono department codes and ink underlines; if a colored element does not encode status or interactivity, it must be ink or paper.
**The Tinted-from-Hue Rule.** On a state-colored background, text and borders take that same hue (flag text on #F9E9E5, never gray on red).

## Typography

**Display / Body Font:** Public Sans (self-hosted via @fontsource, weights 400–700)
**Label / Data Font:** Roboto Mono (self-hosted, weights 400–600)

**Character:** a workhorse grotesque for prose and a plain monospace for everything measured or coded — the pairing of a printed report's body and its tabulated data. Mono is reserved for data, IDs, codes, and labels, never as decoration.

### Hierarchy
- **Display** (700, 1.5rem, tight tracking): page titles in the report header, once per screen.
- **Headline** (700, 1.125rem, tight tracking): panel and section titles ("Proposed envelope", "Review queue" history).
- **Title** (600, 1rem): card and record titles (patient names, dish names).
- **Body** (400, 0.875rem, 1.5): all reading text; descriptions capped near 65ch (max-w-2xl).
- **Label** (mono 500, 0.6875rem, +0.14em, uppercase): report codes (CL·ENV), department codes (ENV/QUE/SIM), column heads, section labels.
- **Data** (mono 500, tabular-nums): every numeric value, limit, revision, ID, and timestamp.

### Named Rules
**The Measured-in-Mono Rule.** Any number a clinician would compare against a limit is set in tabular Roboto Mono; prose never carries a measurement.

## Layout

A centered report column (max-w-7xl, chat max-w-4xl) on the paper ground. The masthead is a ruled strip: wordmark and report tagline left, department-code navigation right, active section underlined in ink. Each screen opens with a ruled report header: display title, one-line description, mono report code (CL·ENV) at the right.

Content organizes as ruled panels, not floating cards. The clinician review screen uses a two-column report sheet at lg: a fixed roster column (~340px) beside the working report. Dense data uses the data-table pattern: mono uppercase column heads, hairline row rules, and expressed column rules — the grid is visible, as on a printed form. Sections separate by whitespace and a single strong hairline; more space above a heading than below it.

## Elevation & Depth

The system is flat by doctrine: no drop shadows anywhere. Depth is conveyed by the rule and the tint — a panel is white paper bounded by a hairline; recessed content sits on the warm panel tint. Overlays (edit modal, swap dialog) dim the page with a flat ink wash (50%), never blur.

### Named Rules
**The Flat-By-Doctrine Rule.** No shadows, no gradients, no blur. If two surfaces need separating, the answer is a hairline or the panel tint, in that order.

## Shapes

Everything is squared: a 2px "report" radius on buttons, fields, flags, and panels; tables and banners are fully square. No pills, no circles. The one recurring geometry is the range bar: a 12px-high ruled track with quartile ticks, a state-hued value fill, a solid red rule for hard ceilings, a hollow marker for soft aims, and a hatched region for the forbidden side of a limit.

## Components

### Buttons
- **Shape:** squared (2px radius), 1px border, semibold 0.875rem label, 8px 16px padding.
- **Primary:** Report Ink ground with paper text — the default action ("Generate proposed envelope", "Send").
- **Approve:** Verified Green ground — reserved for approval and record actions that finalize ("Approve", "Record observation").
- **Danger:** white ground, flag-red text and rule — destructive lifecycle actions ("Reject", "Remove").
- **Ghost:** white ground, soft-ink text, strong-hairline border — neutral actions ("Edit", "Load plan").
- **States:** hover shifts ground a step; disabled is 50% opacity with not-allowed cursor; keyboard focus is a 2px Interaction Blue outline offset 2px, shown only on focus-visible.

### Flags (status chips)
- **Style:** squared mono uppercase label (0.6875rem, +0.08em) on the state hue's wash with its matching rule border: flag/ok/warn/line/neutral variants.
- **Use:** every status word in the system — envelope states (PROPOSED/APPROVED/REJECTED/EDITED), feasibility, compliance, severity. Status is never bare colored text.

### Cards / Containers
- **Corner Style:** squared (2px radius) panels; tables fully square.
- **Background:** Card White with a Hairline border; recessed detail blocks on Panel Tint.
- **Shadow Strategy:** none — see The Flat-By-Doctrine Rule.
- **Internal Padding:** 20px panels, 12–16px records.

### Inputs / Fields
- **Style:** white ground, strong-hairline border, squared corners, 8px 12px padding; numeric fields in tabular mono.
- **Focus:** border shifts to Interaction Blue plus the focus-visible outline; caret is Interaction Blue.
- **Error / Disabled:** errors surface in a ruled flag-red notice strip beside the form; disabled fields take the panel tint.

### Navigation
- Masthead tabs: mono department code + Public Sans label, active section underlined in ink, inactive in muted ink warming to ink on hover. Banners below the masthead are full-width ruled notice strips with a mono flag chip (NOTICE/OFFLINE) and state-tinted ground.

### Range Bar (signature)
The report's central mark: a measured value plotted on its reference range. Quartile ticks on the ruled track; the value fills from the left in its state hue; a hard ceiling is a solid Flag Red rule, soft floors and aims are hollow ink markers; overrun beyond a ceiling and the region below a floor hatch in their state hue (red for hard, amber for soft). In a constraint table the bar shows the limit alone, hatching the forbidden side.

### Data Table
Mono uppercase column heads over a strong hairline; hairline row rules; column rules between cells; rows tint to Panel on hover; values right-aligned in tabular mono.

## Do's and Don'ts

### Do:
- **Do** set every measured value, limit, ID, revision, and timestamp in tabular Roboto Mono (the `num` class).
- **Do** express status with a flag chip, never bare colored text.
- **Do** keep disclosure and error copy in ruled notice strips tinted from their state hue.
- **Do** separate surfaces with hairlines; recess detail blocks with the panel tint.
- **Do** keep one authored motion: the loading scan bar (exponential ease-out, 1.2s), with the reduced-motion static fallback.

### Don't:
- **Don't** use shadows, gradients, backdrop blur, or rounded/pill shapes — the report is flat and squared.
- **Don't** spend state hues on decoration, section identity, or navigation; hue answers "what state is this?"
- **Don't** render a nutrient value without its reference context — no bare numbers where a range bar or limit column belongs.
- **Don't** imply human review with language like "verified"; the approved state is labeled APPROVED, and auto-approval disclosure is mandatory.
- **Don't** add kickers or eyebrows above headings; mono microcopy labels are column heads, codes, and IDs, not decoration.
