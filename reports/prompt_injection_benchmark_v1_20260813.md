# Prompt-injection regression v1

- Run ID: `promptsec-20260813-8c77c82f44d6`
- Result: **PASS**
- Fixed cases: 26 (16 attack / 10 benign)
- Precision / recall / benign specificity: 1.000 / 1.000 / 1.000
- Attack isolation rate: 1.000

This fixed bilingual regression checks deterministic pattern detection and isolation only.
It is not an external red-team, does not cover adaptive attacks, and does not certify production security.
Source knowledge records remain unchanged; isolation is applied only to model context.
