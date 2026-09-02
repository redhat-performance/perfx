# PerfX — project rules

## PR and commit rules — ALWAYS enforce

- **All changes must go through a PR to upstream (`redhat-performance/perfx`)** — never push directly to main
- **Never reference internal Jira ticket numbers** in commit messages, PR titles, or PR descriptions — these are internal Red Hat links not accessible publicly
- **Only reference public sources** in commits and PRs: Red Hat blog posts, access.redhat.com articles, KCS articles, or GitHub issues
- Skills, rules, and methodology content must come from verified public sources — never from training data alone
- **Never mention customer names** in skills, rules, methodology, commits, or PRs — extract only the generic technical pattern

## Package structure

Source lives in `perfx/`, tests mirror it under `tests/perfx/`:
- `perfx/github/github.py` → `tests/perfx/github/test_github.py`
- `perfx/jira/jira.py` → `tests/perfx/jira/test_jira.py`

## Adding tests

Use the `/add-tests` skill. Key rules:
- pytest, class-based, integration tests (no mocks)
- Skip when credentials are missing, not fail
- Jira JQL must always be bounded (include `project is not EMPTY`)
- Run `pytest <file> -v` and fix failures before reporting done

## Coverage rule — ALWAYS enforce

**Every code change must be accompanied by tests.**

- After editing any `perfx/` or `skills/` file, add or update the corresponding test
- Test files mirror source: `perfx/foo.py` → `tests/perfx/test_foo.py`, `skills/foo/foo.py` → `tests/perfx/skills/foo/test_foo.py`
- Verify with: `.venv/bin/pytest tests/ --cov=perfx -q`

## Logging standard — ALWAYS enforce

**All skills must use the unified logging format: `perfx_{uuid}_{datetime}.log`**

When creating a new skill that generates log files:

```python
import os
import uuid
from datetime import datetime
from pathlib import Path

LOGS_DIR = Path(os.environ.get("PERFX_LOGS_DIR", Path(__file__).parent.parent.parent / "logs"))

# In your main() function:
LOGS_DIR.mkdir(parents=True, exist_ok=True)  # Create parent dirs if needed
run_uuid = uuid.uuid4().hex[:8]
ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
out = LOGS_DIR / f"perfx_{run_uuid}_{ts}.log"
out.write_text(report, encoding="utf-8")
print(f"\nReport saved to: {out}")
```

**Never use skill-specific prefixes** like `perfx_windows_`, `perfx_linux_`, or `perfx_vm_audit_`. The 8-character UUID combined with timestamp ensures uniqueness across concurrent runs (collision probability < 1 in 4 billion).

## Knowledge base rule — ALWAYS enforce

**Every new or updated rule/methodology file must be reflected in the relevant SKILL.md files.**

When adding or editing a file in `rules/` or `methodology/`:
1. Identify which skills are affected by the new rule
2. Add or update the `## Rules` section in the relevant `skills/*/SKILL.md` to reference the new file
3. Add a step in `## Steps` that tells chai-bot to read the rule before analyzing

**Mapping:**
- `rules/windows-vm-example.yaml` → `skills/validate-windows-vm-config/SKILL.md`
- `rules/linux-vm-example.yaml` → `skills/validate-linux-vm-config/SKILL.md`
- `rules/host-tuning.md` → `skills/ocp-analysis/SKILL.md`
- New methodology file → all relevant skills that cover that topic

Do NOT report a task done if a new rule was added without updating the corresponding SKILL.md files.

## Credentials

All credentials via `export` or `.env` (never committed):
- `GEMINI_API_KEY` — Gemini model
- `GITHUB_TOKEN` — needed for >60 req/hour on public repos
- `JIRA_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN` — Jira access
- `GIT_REPOS` — list of allowed GitHub repos

## Running the agent

```bash
source .venv/bin/activate
python run.py
```
