# Growth Analyst

**Mission:** Tells Harsh what's working and what to try next.

**Inputs:** Platform metrics APIs, posts table.
**Outputs:** metrics rows, weekly report, recommendations for the Executive Producer.
**AI does:** Interpret patterns, propose experiments (hook styles, lengths, posting times).
**Code does (deterministic):** Metric pulls, comparisons, retention curves.
**Guardrails:** Recommends only; doesn't change anything itself.
**Status:** not implemented. Prompts will live in `prompts/` as versioned text files.
