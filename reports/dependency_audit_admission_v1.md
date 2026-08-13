# Dependency vulnerability admission v1

- Run ID: `depaudit-20260813-3d3e967e0c55`
- Tool: pip-audit 2.9.0 / PyPI
- Initial runtime: **7 findings** (retained failure evidence)
- Fixed runtime: **0 findings**
- Intermediate dev: **1 finding** (retained failure evidence)
- Fixed dev v2: **0 findings**
- Admission: **PASS**

A zero-known-vulnerability result is a point-in-time advisory-database scan, not proof that dependencies are vulnerability-free. Scheduled CI must rerun it.

The initial runtime report found 7 advisories across Click, Starlette and python-dotenv.
The intermediate development report then found one pytest advisory. Lockfiles were regenerated
with Python 3.12 and all 345 tests were rerun after the upgrades.
