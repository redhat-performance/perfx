# PerfX [Performance X-ray]

[![Tests](https://github.com/redhat-performance/perfx/actions/workflows/tests.yml/badge.svg)](https://github.com/redhat-performance/perfx/actions/workflows/tests.yml)
[![codecov](https://codecov.io/gh/redhat-performance/perfx/branch/main/graph/badge.svg)](https://codecov.io/gh/redhat-performance/perfx)

PerfX is an agentic tool that encodes performance expertise into structured, reusable skills. It combines curated domain knowledge with an AI agent to help engineers and customers diagnose and resolve performance issues faster and more consistently. While initially focused on KVM/OpenShift Virtualization, the architecture is designed to be extensible and the same skills, rules, and methodology model can be applied to any performance domain or product in the future.

---

## Setup

```bash
cd PerfX
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
# edit .env and fill in your credentials
```

---

## Run

```bash
perfx
```

Switch models:

```bash
perfx --model gemini
perfx --model claude
```

> Alternatively: `python run.py` (without install)

---

## Choosing a backend

**Option 1 — Anthropic API (recommended for external users)**

Get an API key from [console.anthropic.com](https://console.anthropic.com) and set it in `.env`:

```
ANTHROPIC_API_KEY=your-api-key
```

Then run:

```bash
perfx --model claude
```

**Option 2 — Google Vertex AI (Red Hat internal)**

Requires a GCP project with Claude enabled and `gcloud` authenticated:

```bash
gcloud auth application-default login
```

Set in `.env`:

```
CLAUDE_CODE_USE_VERTEX=1
ANTHROPIC_VERTEX_PROJECT_ID=your-gcp-project-id
```

Then run:

```bash
perfx --model claude
```

**Option 3 — Gemini**

Get an API key from [Google AI Studio](https://aistudio.google.com/app/apikey) and set it in `.env`:

```
GEMINI_API_KEY=your-api-key
```

Then run:

```bash
perfx --model gemini
```

**Option 4 — Custom LLM (bring your own)**

You can plug in any LLM by adding a new backend class to `perfx/llm/backend.py`. The only requirement is a `complete(system, user)` method that returns a string:

```python
class MyBackend:
    def __init__(self):
        # initialize your LLM client here
        pass

    def complete(self, system: str, user: str) -> str:
        # call your LLM and return the response text
        return my_llm.call(system=system, prompt=user)
```

Then register it in `get_backend()`:

```python
def get_backend(model: str = None):
    model = model or os.environ.get("PERFBOT_MODEL", "gemini").lower()
    if model == "claude":
        return ClaudeBackend()
    if model == "my-llm":
        return MyBackend()
    return GeminiBackend()
```

Run with:

```bash
PERFBOT_MODEL=my-llm perfx
```

---

## Example prompts

- `/vm-config --file /path/to/vm.yaml`
- `/io-analysis --file /path/to/domstat.log`
- `/vmexit-analysis --file /path/to/vmexit_stats.txt`
- `/cpu-analysis --file /path/to/pidstat.log`
- `list open issues in redhat-performance/benchmark-runner`
- `search for PROJ-123 in Jira`

---

## Getting credentials

Copy `.env.example` to `.env` and fill in:

| Variable | Required for | Where to get it |
|---|---|---|
| `ANTHROPIC_API_KEY` | Claude (direct API) | [console.anthropic.com](https://console.anthropic.com) |
| `CLAUDE_CODE_USE_VERTEX` | Claude via Vertex AI | Set to `1` to use GCP instead of direct API |
| `ANTHROPIC_VERTEX_PROJECT_ID` | Claude via Vertex AI | Your GCP project ID |
| `GEMINI_API_KEY` | Gemini agent | [Google AI Studio](https://aistudio.google.com/app/apikey) |
| `GITHUB_TOKEN` | GitHub tools (>60 req/hr) | GitHub → Settings → Developer settings → Personal access tokens |
| `GIT_REPOS` | Restrict GitHub search | Comma-separated list of full repo URLs |
| `JIRA_URL` | Jira tools | Your Jira instance URL |
| `JIRA_EMAIL` | Jira tools | Your Jira login email |
| `JIRA_API_TOKEN` | Jira tools | Jira → Account Settings → Security → API tokens |

---

## Available Skills

| Skill | Input | What it detects |
|---|---|---|
| `vm-config` | VM YAML file | hyperv enlightenments, machine type, ioThreads, disk bus, CPU pinning, HPET |
| `cpu-analysis` | pidstat file | vCPU saturation, KVM exit overhead, IO-driven idle |
| `io-analysis` | domstat file | Forced fsync (1:1 flush:write), write latency, vCPU stall |
| `memory-analysis` | domstat file | RSS usage, swap activity, major page faults |
| `network-analysis` | domstat file | TX/RX throughput, packet drops, pps, avg packet size |
| `delta-analysis` | domstat file | Full metric scan across CPU, memory, block IO, vCPU |
| `vmexit-analysis` | kvm vmexit stats file | HLT dominance, IO_INSTRUCTION (useplatformclock), exit overhead |

---

## Project Structure

```
rules/          — structured facts: thresholds, known issue signatures, reference VM configs
methodology/    — how to analyze: step-by-step investigation workflows
skills/         — executable analysis scripts + SKILL.md definitions
perfx/          — core agent code: LLM backends, tool registry, GitHub/Jira integrations
tests/          — pytest integration tests
logs/           — generated analysis reports
.env.example    — credential template
```

---

## Running Tests

```bash
source .venv/bin/activate
pytest tests/ --cov=perfx -q
```

---

## License

Apache License 2.0 — see [LICENSE](LICENSE).
