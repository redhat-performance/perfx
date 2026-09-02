import json
import os
import re
import warnings
warnings.filterwarnings("ignore", message=".*quota project.*", category=UserWarning)
from perfx.tool_registry import DISPATCH, TOOL_DECLARATIONS, ANTHROPIC_TOOLS
from perfx.logger import get_logger

log = get_logger("client")


def _thinking(msg: str):
    print(f"\r\033[K  {msg}", end="", flush=True)


def _clear_thinking():
    print(f"\r\033[K", end="", flush=True)


def _parse_repos() -> list[str]:
    raw = os.environ.get("GIT_REPOS", "")
    if not raw:
        return []
    urls = re.findall(r'https?://[^\s\'">,\]]+', raw)
    repos = []
    for url in urls:
        match = re.search(r'github\.com/([^/]+/[^/]+)', url.rstrip("/"))
        if match:
            repos.append(match.group(1))
    return repos


def _build_system_instruction() -> str:
    repo_list = _parse_repos()
    base = (
        "You are a helpful assistant with access to GitHub, Jira, a performance knowledge base, VM YAML configuration auditing, and the local filesystem. "
        "Use read_file to read any local file the user mentions — sosreport files, log files, config files, system files. "
        "When the user shares a Google Drive URL — ALWAYS call list_gdrive_folder or read_gdrive immediately. NEVER say you don't have access. "
        "Use list_gdrive_folder to list files in a Google Drive folder (accepts folder ID or full URL). "
        "Use read_gdrive to read a Google Drive file (accepts file ID or full URL). "
        "When a Google Drive folder or file contains a VM YAML — list the folder, read the YAML content, ask the user 'Is this a Windows or Linux VM?' then call check_vm_config_from_content(yaml_content, os_type) with the confirmed os_type. NEVER analyze the YAML yourself — always call the tool. "
        "When asked to analyze a sosreport or directory, read the key files using read_file: "
        "etc/os-release, proc/cmdline, sos_commands/processor/lscpu, "
        "sys/devices/system/cpu/cpu0/cpuidle/state*/name, sys/devices/system/cpu/cpu0/cpufreq/scaling_governor, "
        "proc/meminfo, sos_commands/block/lsblk, proc/sys/vm/dirty_ratio. "
        "Apply rules from read_rules('io-degradation') to interpret the findings. "
        "IMPORTANT: When the user asks about performance issues, degradation, recommendations, investigation steps, "
        "or asks to see a recommended/reference configuration (e.g. 'show me the windows yaml', 'recommended config', "
        "'windows template', 'linux template') — ALWAYS call read_rules first with the relevant topic. "
        "Topics to use: 'io-degradation', 'memory', 'vmexit', 'cpu', 'windows-vm-example', 'linux-vm-example'. "
        "Base your answer entirely on the returned rules content. Never answer from memory alone. "
        "When the user asks to check or analyze a VM YAML configuration and NO file path is provided: "
        "1. Call list_cluster_vms to get all running VMs across all namespaces. "
        "2. If exactly 1 VM is found — automatically call fetch_cluster_vm_yaml with that VM's name and namespace, then analyze it. "
        "3. If more than 1 VM is found — list all VMs clearly (namespace, name, status) and ask the user which one to analyze. Once user chooses, call fetch_cluster_vm_yaml then analyze. "
        "4. If no VMs found — tell the user no VMs are running on the cluster. "
        "For ALL VM YAML checks (file path, cluster, or Google Drive) — ALWAYS use check_vm_config_from_content(yaml_content, os_type). "
        "Never call check_vm_config or validate_linux_vm_config directly — they are missing guest-side steps. "
        "To get yaml_content: use read_file for local paths, fetch_cluster_vm_yaml for cluster VMs, read_gdrive for Drive files. "
        "To determine os_type: if the user says 'windows' use os_type='windows'; if 'linux' use os_type='linux'; otherwise ask 'Is this a Windows or Linux VM?'. "
        "After the tool runs, ALWAYS display: "
        "1. VM name and namespace at the top of the report "
        "2. The 'table' field EXACTLY as returned (pre-formatted — do not modify it) "
        "3. Severity and summary "
        "4. 'Report saved to: <log_file>' "
        "Never skip showing the table. "
        "Always confirm the action you took and summarize the result clearly. "
        "Maintain context across the conversation — if the user refers to something from a previous message (e.g. 'fill the values', 'that file', 'same repo'), use the prior context to fulfill the request. "
        "When the user asks for the content of a file (e.g. 'give me the yaml file', 'show me the template'), "
        "first use github_search_code to find the best matching file, then IMMEDIATELY call github_get_file to fetch and return its full content — do not stop to ask the user which file they want unless the results are completely ambiguous. "
        "\n\nIMPORTANT — You do NOT have the following capabilities. If asked, clearly say so:\n"
        "- No terminal or shell access — cannot run arbitrary commands\n"
        "- No ability to run Podman, Docker, or any container\n"
        "- No arbitrary network access — only GitHub API, Jira API, and OCP cluster (via oc CLI) are available\n"
        "- No ability to execute benchmark-runner or any other program\n"
        "- No ability to deploy, apply, or create any resource on a cluster\n"
        "What you CAN do: list Running VMs and fetch VM YAMLs from the OCP cluster, audit VM configs, read files, search GitHub and Jira."
    )
    if repo_list:
        formatted = ", ".join(repo_list)
        base += (
            f" When the user does not specify a repository, search only across these configured repos: {formatted}. "
            "Never search outside this list unless the user explicitly names a different repo."
        )
    return base


def _dispatch_tool(fn_name: str, fn_args: dict) -> dict:
    log.debug("tool call: %s(%s)", fn_name, fn_args)
    try:
        result = DISPATCH[fn_name](**fn_args)
        log.debug("tool result: %s", result)
        return result
    except Exception as exc:
        log.exception("tool %s raised an exception", fn_name)
        return {"error": str(exc)}


class GeminiAgent:
    def __init__(self):
        from google import genai
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise EnvironmentError("GEMINI_API_KEY is not set")
        self.client = genai.Client(api_key=api_key)
        self.history = []

    def chat(self, user_message: str) -> str:
        from google.genai import types
        self.history.append(types.Content(role="user", parts=[types.Part(text=user_message)]))

        first_turn = True
        while True:
            if first_turn:
                _thinking("Thinking...")
                first_turn = False
            response = self.client.models.generate_content(
                model="gemini-2.5-flash",
                contents=self.history,
                config=types.GenerateContentConfig(
                    system_instruction=_build_system_instruction(),
                    tools=TOOL_DECLARATIONS,
                ),
            )
            candidate = response.candidates[0].content
            self.history.append(candidate)

            tool_calls = [p for p in candidate.parts if p.function_call]
            if not tool_calls:
                _clear_thinking()
                break

            tool_results = []
            for part in tool_calls:
                fn_name = part.function_call.name
                fn_args = dict(part.function_call.args)
                _thinking(f"Using tool: {fn_name}...")
                result = _dispatch_tool(fn_name, fn_args)
                tool_results.append(types.Part(
                    function_response=types.FunctionResponse(
                        name=fn_name,
                        response={"result": json.dumps(result, default=str)},
                    )
                ))
            self.history.append(types.Content(role="user", parts=tool_results))

        return response.text


class ClaudeAgent:
    def __init__(self):
        import anthropic
        use_vertex = os.environ.get("CLAUDE_CODE_USE_VERTEX", "").lower() in {"1", "true", "yes"}
        if use_vertex:
            project = os.environ.get("ANTHROPIC_VERTEX_PROJECT_ID")
            region = os.environ.get("CLOUD_ML_REGION", "us-east5")
            if not project:
                raise EnvironmentError("ANTHROPIC_VERTEX_PROJECT_ID is not set")
            self.client = anthropic.AnthropicVertex(project_id=project, region=region)
            self.model = "claude-sonnet-4-5"
        else:
            api_key = os.environ.get("ANTHROPIC_API_KEY")
            if not api_key:
                raise EnvironmentError("ANTHROPIC_API_KEY is not set (or set CLAUDE_CODE_USE_VERTEX=1 for Vertex)")
            self.client = anthropic.Anthropic(api_key=api_key)
            self.model = "claude-sonnet-4-5"
        self.history = []

    def chat(self, user_message: str) -> str:
        self.history.append({"role": "user", "content": user_message})

        first_turn = True
        while True:
            if first_turn:
                _thinking("Thinking...")
                first_turn = False
            response = self.client.messages.create(
                model=self.model,
                max_tokens=8096,
                system=_build_system_instruction(),
                tools=ANTHROPIC_TOOLS,
                messages=self.history,
            )
            # add assistant turn to history
            self.history.append({"role": "assistant", "content": response.content})

            tool_uses = [b for b in response.content if b.type == "tool_use"]
            if not tool_uses:
                _clear_thinking()
                break

            tool_results = []
            for block in tool_uses:
                _thinking(f"Using tool: {block.name}...")
                result = _dispatch_tool(block.name, block.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result, default=str),
                })
            self.history.append({"role": "user", "content": tool_results})

        # extract final text
        text_blocks = [b.text for b in response.content if hasattr(b, "text")]
        return "\n".join(text_blocks)


def Agent():
    """Factory — returns GeminiAgent or ClaudeAgent based on PERFBOT_MODEL."""
    model = os.environ.get("PERFBOT_MODEL", "claude").lower()
    if model == "claude":
        log.debug("Using Claude backend")
        return ClaudeAgent()
    log.debug("Using Gemini backend")
    return GeminiAgent()
