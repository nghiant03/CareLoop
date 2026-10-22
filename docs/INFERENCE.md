# Hosted inference

Use paid hosted inference for extraction and cited patient answers. Numerical
checking, optimization, and clustering run locally. Model selection follows a
pilot comparing extraction fidelity and grounded-answer performance.

## Budget

The user specified Neuralwatt Basic, superseding the earlier $50 proposal.
[Pricing](https://portal.neuralwatt.com/pricing) observed on 2026-10-23 lists
$20/month, 2.35 kWh included, and $8.50/kWh monthly overage. Recheck at execution;
do not assume a fixed token-to-energy conversion or authorization for overage.

Measure actual pilot consumption, reserve demonstration capacity, and size the
evaluation to the remaining included allowance. Cache completed work, bound
outputs/retries, and support resumption. Save model identifiers, prompts, responses,
and consumption so reports can be regenerated without fresh calls.

No API key was supplied during requirements discussion. Never put credentials in
the repository or reports. A local LLM is not required. Laptop hardware was
described as having a 5050 GPU; CPU, RAM, VRAM, and runtime remain unmeasured.
