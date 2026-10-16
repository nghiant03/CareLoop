# Patient guide

What you will see in the CareLoop app, in plain language.

> **Important:** CareLoop is an academic demo, not medical advice. Demo mode
> auto-approves new eligible targets without clinical review and labels them as
> such. The clinician role is simulated. Never use these targets to make real
> changes to diet or medication.

## Reading your meal plan

On the **Meal plan** screen, pick your name and press **Generate 7-day plan**.
You get seven day cards, one per day. Each card shows three meals — breakfast,
lunch and dinner — with a main dish and sometimes a side (for example, "Chicken
Rice (Hainanese)"). The dishes are picked to fit the approved demo limits:
salt, protein, potassium, phosphorus, calories and more.

Plans require targets in the **APPROVED** workflow state. Demo auto mode does
this for new eligible proposals; clinician mode waits for simulated manual
review. An edit clears approval in either mode. "Envelope not approved" means
review or re-approval is still needed; rejected scope cases cannot be approved.

## The "why these meals" panel

Above your meals there is a short explanation in everyday words:

- **Your daily targets** — things like "Keep salt (sodium) under 2 g a day" or
  "Get at least 130 g of carbohydrate a day".
- **What to avoid** — for example "potassium-based salt substitutes",
  "processed foods with phosphate additives", "sugar-sweetened drinks".
- **Why** — the panel explains the guideline source of a target (for example
  "KDIGO 2024 CKD Guideline recommends: …") or identifies a clinician adjustment.
  A clinician's changed number is not presented as a guideline recommendation.

If the planner used a lowered goal during its fallback search, you will see a
note explaining that adjustment. A plan can also miss a goal without lowering
it: check the adequacy information against your original approved goals and
discuss any gaps with your clinician.

## The daily bars and "over limit"

Each day card has a "Daily totals vs targets" section. Every bar shows one
nutrient: how much **today's meals add up to**, against your personal limit or
goal.

- A **blue bar** means you are within your limit (or on track for a "at least"
  goal).
- A **red bar** with the words **"Over limit"** means today's combination went
  past a limit. Treat it as a signal to talk to your care team — the numbers
  come from estimated food values, not from weighing your actual plate.

## Logging what you actually ate

On the **Adherence** screen you can record what you really ate. Pick your
name, a day, and the meal (breakfast, lunch or dinner), then choose the dish
from a searchable list (type part of a dish name, e.g. "chicken rice"). Add
multiple dishes and their serving quantities before saving. Saving the same
meal again replaces its previous items, rather than adding another meal.

The app compares each logged date with the approved targets effective on that
date, not today's newest proposal. Dates without approval coverage are listed
as unattributed and are not compared with targets:

- A day can show **"Over limit"** (red) — the logged food went past a hard
  ceiling, such as a sodium or potassium limit. This is the same "over the
  limit" idea as on the meal-plan bars, but for what you actually ate.
- A day can show **"Below aim"** (amber) — the logged food fell short of an
  "at least" goal (such as getting enough carbohydrate) or drifted off a
  "target" value. Falling short of an aim is not a violation; it just means
  today's food didn't reach the goal.
- An **aggregate view** shows how many logged days were over a limit, and
  which nutrients come up most often.
- A **trends** view looks at your logged days over time. If a nutrient keeps
  moving away from your target, you will see a **worsening banner** — a
  signal worth bringing up with your care team, not an emergency.

Log breakfast, lunch and dinner for a day to count toward trends and below-aim
summaries. A partly logged day can still show an over-limit warning.

The numbers are only as good as the dish estimates behind them, and only you
know what portion you really ate — treat the results as a conversation
starter, not a lab report. An informational notice about your latest targets
does not change the older approvals used for historical comparisons; days with
no approval coverage remain unattributed.

## Using chat

The **Chat** screen answers questions about your nutrition — for example *"why
is my sodium limit 2000?"*.

- Answers are built **only** from CareLoop's medical guideline database and
  your approved plan — the chat cannot make things up, and every answer shows
  its source: the guideline it came from (name and link) or, when your
  clinician edited a value, a clinician-edit note (edited values are never
  presented as guideline recommendations).
- It answers nutrition questions only. If you ask something a chatbot should
  not answer, you will see a banner instead:
  - emergency symptoms (including metabolic emergencies like possible
    ketoacidosis signs) → "contact emergency services or urgent care
    immediately";
  - diagnosis questions ("do I have …?") → "please discuss symptoms and
    diagnosis with your clinician";
  - medication changes — including phrasings like *"should I stop taking
    metformin?"* or *"can I skip my insulin today?"* — and other out-of-scope
    topics → "this needs a clinician".
  **"A clinician will review this"** means exactly that: the app does not
  answer, and the question belongs with your care team.
- If the chat cannot find guideline-backed information for your question, it
  says so and suggests speaking with your clinician or dietitian rather than
  guessing.
- If you take **warfarin** (Coumadin), asking about vitamin K or leafy greens
  gives one specific, guideline-backed message: keep your vitamin K intake
  **consistent** from week to week — do not avoid leafy greens or make drastic
  dietary changes while on warfarin (source: the FDA Coumadin label's
  instructions for patients). Your clinician manages the dose, not your
  salad.
