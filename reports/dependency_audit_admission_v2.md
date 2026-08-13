# Dependency vulnerability admission v2

- Run ID: `depaudit-v2-20260813-a8fe763cdd12`
- Tool: pip-audit 2.9.0 / PyPI
- Initial runtime: **7 findings** (retained failure evidence)
- Fixed runtime: **0 findings**
- Intermediate dev: **1 finding** (retained failure evidence)
- Fixed dev v2: **0 findings**
- Current runtime r2: **0 findings**
- Current dev r2: **0 findings**
- Admission: **PASS**

A zero-known-vulnerability result is a point-in-time advisory-database scan, not proof that dependencies are vulnerability-free. Scheduled CI must rerun it.

The initial runtime report found 7 advisories across Click, Starlette and python-dotenv.
The intermediate development report then found one pytest advisory. Lockfiles were regenerated
with Python 3.12. The current r2 reports rerun both lockfiles after the final code audit;
the full application test count is reported separately by the reproducible pytest command.
