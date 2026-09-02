from google.genai import types as gtypes
from perfx.vm_config_tool import check_vm_config, validate_linux_vm_config, detect_os, check_vm_config_from_content, check_vm_config_from_path
from perfx.knowledge_tool import read_rules, read_file
from perfx.cluster_tool import list_cluster_vms, fetch_cluster_vm_yaml
from perfx.gdrive.gdrive import list_gdrive_folder, read_gdrive, search_gdrive
from perfx.github.github import (
    github_get_issue,
    github_list_issues,
    github_search_issues,
    github_create_issue,
    github_add_comment,
    github_search_code,
    github_get_file,
)
from perfx.jira.jira import (
    jira_get_issue,
    jira_search_issues,
    jira_create_issue,
    jira_update_issue,
    jira_add_comment,
)

DISPATCH = {
    "read_rules": read_rules,
    "read_file": read_file,
    "list_cluster_vms": list_cluster_vms,
    "fetch_cluster_vm_yaml": fetch_cluster_vm_yaml,
    "read_gdrive": read_gdrive,
    "list_gdrive_folder": list_gdrive_folder,
    "search_gdrive": search_gdrive,
    "check_vm_config": check_vm_config,
    "validate_linux_vm_config": validate_linux_vm_config,
    "detect_os": detect_os,
    "check_vm_config_from_path": check_vm_config_from_path,
    "check_vm_config_from_content": check_vm_config_from_content,
    "github_get_issue": github_get_issue,
    "github_list_issues": github_list_issues,
    "github_search_issues": github_search_issues,
    "github_create_issue": github_create_issue,
    "github_add_comment": github_add_comment,
    "github_search_code": github_search_code,
    "github_get_file": github_get_file,
    "jira_get_issue": jira_get_issue,
    "jira_search_issues": jira_search_issues,
    "jira_create_issue": jira_create_issue,
    "jira_update_issue": jira_update_issue,
    "jira_add_comment": jira_add_comment,
}

TOOL_DECLARATIONS = [
    gtypes.Tool(
        function_declarations=[
            # ── Google Drive ─────────────────────────────────────────────────
            gtypes.FunctionDeclaration(
                name="list_gdrive_folder",
                description="List all files in a Google Drive folder by folder ID or URL.",
                parameters=gtypes.Schema(
                    type=gtypes.Type.OBJECT,
                    properties={
                        "folder_id": gtypes.Schema(type=gtypes.Type.STRING,
                                                    description="Google Drive folder ID or full URL"),
                    },
                    required=["folder_id"],
                ),
            ),
            gtypes.FunctionDeclaration(
                name="read_gdrive",
                description="Read a file from Google Drive by file ID or full URL. Supports Google Docs, Sheets, plain text files.",
                parameters=gtypes.Schema(
                    type=gtypes.Type.OBJECT,
                    properties={
                        "file_id": gtypes.Schema(type=gtypes.Type.STRING,
                                                  description="Google Drive file ID or full URL (e.g. https://drive.google.com/file/d/xxx)"),
                    },
                    required=["file_id"],
                ),
            ),
            gtypes.FunctionDeclaration(
                name="search_gdrive",
                description="Search for files in Google Drive by name or content keyword.",
                parameters=gtypes.Schema(
                    type=gtypes.Type.OBJECT,
                    properties={
                        "query": gtypes.Schema(type=gtypes.Type.STRING, description="Search keyword"),
                        "max_results": gtypes.Schema(type=gtypes.Type.INTEGER, description="Max results (default 20)"),
                    },
                    required=["query"],
                ),
            ),
            # ── File reading ─────────────────────────────────────────────────
            gtypes.FunctionDeclaration(
                name="read_file",
                description=(
                    "Read any file or files from the filesystem. "
                    "Supports glob patterns (e.g. /path/state*/name for multiple files). "
                    "Use this to read sosreport files, log files, VM configs, or any system file. "
                    "Always use this when the user asks to analyze files from a path."
                ),
                parameters=gtypes.Schema(
                    type=gtypes.Type.OBJECT,
                    properties={
                        "path": gtypes.Schema(type=gtypes.Type.STRING,
                                              description="Absolute file path or glob pattern, e.g. /path/to/file or /path/state*/name"),
                        "max_lines": gtypes.Schema(type=gtypes.Type.INTEGER,
                                                   description="Max lines to return (default 200)"),
                    },
                    required=["path"],
                ),
            ),
            # ── Knowledge base ───────────────────────────────────────────────
            gtypes.FunctionDeclaration(
                name="read_rules",
                description=(
                    "Read rules and methodology files from the PerfX knowledge base. "
                    "Use this whenever the user asks about performance issues, recommendations, "
                    "or investigation steps — ALWAYS call this first before answering from memory. "
                    "Topics: 'io', 'io-degradation', 'memory', 'network', 'vmexit', 'cpu', 'windows-vm', 'linux-vm'."
                ),
                parameters=gtypes.Schema(
                    type=gtypes.Type.OBJECT,
                    properties={
                        "topic": gtypes.Schema(type=gtypes.Type.STRING,
                                               description="Topic to search for, e.g. 'io-degradation', 'memory', 'vmexit'"),
                    },
                    required=["topic"],
                ),
            ),
            gtypes.FunctionDeclaration(
                name="check_vm_config_from_path",
                description=(
                    "PREFERRED: Check a VM YAML configuration from a local file path. "
                    "Use this whenever the user provides a file path — do NOT read the file first. "
                    "IMPORTANT: Before calling, always ask the user 'Is this a Windows or Linux VM?' "
                    "and pass their answer as os_type. Do not rely on auto-detection alone."
                ),
                parameters=gtypes.Schema(
                    type=gtypes.Type.OBJECT,
                    properties={
                        "path": gtypes.Schema(type=gtypes.Type.STRING,
                                              description="Absolute path to the VM YAML file"),
                        "os_type": gtypes.Schema(type=gtypes.Type.STRING,
                                                 description="Override OS: 'windows' or 'linux'. Omit to auto-detect."),
                    },
                    required=["path"],
                ),
            ),
            gtypes.FunctionDeclaration(
                name="check_vm_config_from_content",
                description=(
                    "Check a VM YAML configuration from content string. "
                    "Use ONLY when the YAML comes from Google Drive or is not a local file. "
                    "If the user provided a file path, use check_vm_config_from_path instead."
                ),
                parameters=gtypes.Schema(
                    type=gtypes.Type.OBJECT,
                    properties={
                        "yaml_content": gtypes.Schema(type=gtypes.Type.STRING,
                                                       description="The full YAML content string"),
                    },
                    required=["yaml_content"],
                ),
            ),
            # ── OCP cluster tools ────────────────────────────────────────────
            gtypes.FunctionDeclaration(
                name="list_cluster_vms",
                description=(
                    "List all VMs running on the connected OCP cluster. "
                    "Call this when the user asks to check a VM YAML and has not provided a file path."
                ),
                parameters=gtypes.Schema(type=gtypes.Type.OBJECT, properties={}),
            ),
            gtypes.FunctionDeclaration(
                name="fetch_cluster_vm_yaml",
                description=(
                    "Fetch a VM YAML from the OCP cluster by name and namespace, save to a temp file, "
                    "and return the file path. Use this before calling check_vm_config or validate_linux_vm_config."
                ),
                parameters=gtypes.Schema(
                    type=gtypes.Type.OBJECT,
                    properties={
                        "name":      gtypes.Schema(type=gtypes.Type.STRING, description="VM name"),
                        "namespace": gtypes.Schema(type=gtypes.Type.STRING, description="Namespace the VM is in"),
                    },
                    required=["name", "namespace"],
                ),
            ),
            # ── VM config audit ──────────────────────────────────────────────
            gtypes.FunctionDeclaration(
                name="check_vm_config",
                description=(
                    "Audit a Windows VM YAML configuration against the recommended template. "
                    "Checks hyperv enlightenments, clock timers, ioThreads, autoattachMemBalloon, "
                    "machine type, firmware, and disk bus. Returns a table showing Customer VM vs "
                    "Recommended settings with pass/fail status."
                ),
                parameters=gtypes.Schema(
                    type=gtypes.Type.OBJECT,
                    properties={
                        "path": gtypes.Schema(type=gtypes.Type.STRING,
                                              description="Absolute path to the VM YAML file"),
                    },
                    required=["path"],
                ),
            ),
            gtypes.FunctionDeclaration(
                name="validate_linux_vm_config",
                description=(
                    "Audit a Linux VM YAML configuration against benchmark-runner best practices. "
                    "Checks disk bus (virtio), network model (virtio), CPU requests/limits, "
                    "dedicatedCpuPlacement, ioThreadsPolicy, machine type, and evictionStrategy. "
                    "Saves a report to logs/ and returns pass/fail/missing findings."
                ),
                parameters=gtypes.Schema(
                    type=gtypes.Type.OBJECT,
                    properties={
                        "path": gtypes.Schema(type=gtypes.Type.STRING,
                                              description="Absolute path to the Linux VM YAML file"),
                    },
                    required=["path"],
                ),
            ),
            # ── GitHub ──────────────────────────────────────────────────────
            gtypes.FunctionDeclaration(
                name="github_get_issue",
                description="Fetch a single GitHub issue or PR by repository and issue number.",
                parameters=gtypes.Schema(
                    type=gtypes.Type.OBJECT,
                    properties={
                        "repo": gtypes.Schema(type=gtypes.Type.STRING, description="owner/repo, e.g. octocat/Hello-World"),
                        "number": gtypes.Schema(type=gtypes.Type.INTEGER, description="Issue or PR number"),
                    },
                    required=["repo", "number"],
                ),
            ),
            gtypes.FunctionDeclaration(
                name="github_list_issues",
                description="List issues for a GitHub repository.",
                parameters=gtypes.Schema(
                    type=gtypes.Type.OBJECT,
                    properties={
                        "repo": gtypes.Schema(type=gtypes.Type.STRING, description="owner/repo"),
                        "state": gtypes.Schema(type=gtypes.Type.STRING, description="open, closed, or all (default: open)"),
                        "limit": gtypes.Schema(type=gtypes.Type.INTEGER, description="Max results to return (default: 20)"),
                    },
                    required=["repo"],
                ),
            ),
            gtypes.FunctionDeclaration(
                name="github_search_issues",
                description="Search GitHub issues and PRs using a search query string.",
                parameters=gtypes.Schema(
                    type=gtypes.Type.OBJECT,
                    properties={
                        "query": gtypes.Schema(type=gtypes.Type.STRING, description="GitHub search query, e.g. 'label:bug repo:owner/repo'"),
                        "limit": gtypes.Schema(type=gtypes.Type.INTEGER, description="Max results (default: 20)"),
                    },
                    required=["query"],
                ),
            ),
            gtypes.FunctionDeclaration(
                name="github_create_issue",
                description="Create a new issue in a GitHub repository.",
                parameters=gtypes.Schema(
                    type=gtypes.Type.OBJECT,
                    properties={
                        "repo": gtypes.Schema(type=gtypes.Type.STRING, description="owner/repo"),
                        "title": gtypes.Schema(type=gtypes.Type.STRING, description="Issue title"),
                        "body": gtypes.Schema(type=gtypes.Type.STRING, description="Issue body/description"),
                    },
                    required=["repo", "title"],
                ),
            ),
            gtypes.FunctionDeclaration(
                name="github_add_comment",
                description="Add a comment to an existing GitHub issue or PR.",
                parameters=gtypes.Schema(
                    type=gtypes.Type.OBJECT,
                    properties={
                        "repo": gtypes.Schema(type=gtypes.Type.STRING, description="owner/repo"),
                        "number": gtypes.Schema(type=gtypes.Type.INTEGER, description="Issue or PR number"),
                        "body": gtypes.Schema(type=gtypes.Type.STRING, description="Comment text"),
                    },
                    required=["repo", "number", "body"],
                ),
            ),
            gtypes.FunctionDeclaration(
                name="github_search_code",
                description="Search for files or code content inside GitHub repositories. Use this to find YAML templates, config files, scripts, or any file by name or content.",
                parameters=gtypes.Schema(
                    type=gtypes.Type.OBJECT,
                    properties={
                        "query": gtypes.Schema(type=gtypes.Type.STRING, description="Search query, e.g. 'windows yaml', 'filename:windows.yaml', 'extension:yaml windows'"),
                        "limit": gtypes.Schema(type=gtypes.Type.INTEGER, description="Max results (default: 10)"),
                    },
                    required=["query"],
                ),
            ),
            gtypes.FunctionDeclaration(
                name="github_get_file",
                description="Get the full content of a file from a GitHub repository by its path.",
                parameters=gtypes.Schema(
                    type=gtypes.Type.OBJECT,
                    properties={
                        "repo": gtypes.Schema(type=gtypes.Type.STRING, description="owner/repo"),
                        "path": gtypes.Schema(type=gtypes.Type.STRING, description="File path in the repo, e.g. 'ci/windows.yaml'"),
                    },
                    required=["repo", "path"],
                ),
            ),
            # ── Jira ─────────────────────────────────────────────────────────
            gtypes.FunctionDeclaration(
                name="jira_get_issue",
                description="Fetch a single Jira issue by its key, e.g. PROJ-123.",
                parameters=gtypes.Schema(
                    type=gtypes.Type.OBJECT,
                    properties={
                        "issue_key": gtypes.Schema(type=gtypes.Type.STRING, description="Jira issue key, e.g. PROJ-123"),
                    },
                    required=["issue_key"],
                ),
            ),
            gtypes.FunctionDeclaration(
                name="jira_search_issues",
                description="Search Jira issues using a JQL query string.",
                parameters=gtypes.Schema(
                    type=gtypes.Type.OBJECT,
                    properties={
                        "jql": gtypes.Schema(type=gtypes.Type.STRING, description="JQL query, e.g. 'project=PROJ AND status=Open'"),
                        "limit": gtypes.Schema(type=gtypes.Type.INTEGER, description="Max results (default: 20)"),
                    },
                    required=["jql"],
                ),
            ),
            gtypes.FunctionDeclaration(
                name="jira_create_issue",
                description="Create a new Jira issue in a project.",
                parameters=gtypes.Schema(
                    type=gtypes.Type.OBJECT,
                    properties={
                        "project": gtypes.Schema(type=gtypes.Type.STRING, description="Jira project key, e.g. PROJ"),
                        "summary": gtypes.Schema(type=gtypes.Type.STRING, description="Issue summary/title"),
                        "description": gtypes.Schema(type=gtypes.Type.STRING, description="Issue description"),
                        "issue_type": gtypes.Schema(type=gtypes.Type.STRING, description="Issue type: Task, Bug, Story, etc. (default: Task)"),
                    },
                    required=["project", "summary"],
                ),
            ),
            gtypes.FunctionDeclaration(
                name="jira_update_issue",
                description="Update fields of an existing Jira issue.",
                parameters=gtypes.Schema(
                    type=gtypes.Type.OBJECT,
                    properties={
                        "issue_key": gtypes.Schema(type=gtypes.Type.STRING, description="Jira issue key, e.g. PROJ-123"),
                        "summary": gtypes.Schema(type=gtypes.Type.STRING, description="New summary"),
                        "description": gtypes.Schema(type=gtypes.Type.STRING, description="New description"),
                        "assignee": gtypes.Schema(type=gtypes.Type.STRING, description="Assignee username"),
                    },
                    required=["issue_key"],
                ),
            ),
            gtypes.FunctionDeclaration(
                name="jira_add_comment",
                description="Add a comment to an existing Jira issue.",
                parameters=gtypes.Schema(
                    type=gtypes.Type.OBJECT,
                    properties={
                        "issue_key": gtypes.Schema(type=gtypes.Type.STRING, description="Jira issue key, e.g. PROJ-123"),
                        "body": gtypes.Schema(type=gtypes.Type.STRING, description="Comment text"),
                    },
                    required=["issue_key", "body"],
                ),
            ),
        ]
    )
]

# ── Anthropic tool schema (for Claude backend) ──────────────────────────────
ANTHROPIC_TOOLS = [
    {"name": "list_gdrive_folder",
     "description": "List all files in a Google Drive folder by folder ID or URL.",
     "input_schema": {"type": "object", "properties": {"folder_id": {"type": "string", "description": "Google Drive folder ID or full URL"}}, "required": ["folder_id"]}},
    {"name": "search_gdrive",
     "description": "Search for files in Google Drive by name or content keyword.",
     "input_schema": {"type": "object", "properties": {"query": {"type": "string"}, "max_results": {"type": "integer"}}, "required": ["query"]}},
    {"name": "read_gdrive",
     "description": "Read a file from Google Drive by file ID or full URL.",
     "input_schema": {"type": "object", "properties": {"file_id": {"type": "string", "description": "Google Drive file ID or full URL"}}, "required": ["file_id"]}},
    {"name": "read_file",
     "description": "Read any file or files from the filesystem. Supports glob patterns (e.g. /path/state*/name). Use this to read sosreport files, log files, VM configs, or any system file.",
     "input_schema": {"type": "object", "properties": {
         "path": {"type": "string", "description": "Absolute file path or glob pattern"},
         "max_lines": {"type": "integer", "description": "Max lines to return (default 200)"}
     }, "required": ["path"]}},
    {"name": "read_rules",
     "description": "Read rules and methodology files from the PerfX knowledge base. Use this whenever the user asks about performance issues, recommendations, or investigation steps — ALWAYS call this first before answering from memory. Topics: 'io', 'io-degradation', 'memory', 'network', 'vmexit', 'cpu', 'windows-vm', 'linux-vm'.",
     "input_schema": {"type": "object", "properties": {"topic": {"type": "string", "description": "Topic to search, e.g. 'io-degradation', 'memory', 'vmexit'"}}, "required": ["topic"]}},
    {"name": "check_vm_config_from_path",
     "description": "PREFERRED: Check a VM YAML configuration from a local file path. Use this whenever the user provides a file path — do NOT read the file first. IMPORTANT: Before calling, always ask the user 'Is this a Windows or Linux VM?' and pass their answer as os_type.",
     "input_schema": {"type": "object", "properties": {
         "path": {"type": "string", "description": "Absolute path to the VM YAML file"},
         "os_type": {"type": "string", "description": "Override OS: 'windows' or 'linux'. Omit to auto-detect."}
     }, "required": ["path"]}},
    {"name": "check_vm_config_from_content",
     "description": "Check a VM YAML configuration from content string. Use ONLY when YAML comes from Google Drive or is not a local file. If user gave a file path, use check_vm_config_from_path instead.",
     "input_schema": {"type": "object", "properties": {
         "yaml_content": {"type": "string", "description": "The full YAML content string"},
         "os_type": {"type": "string", "description": "OS type: 'windows' or 'linux' — confirmed by user"}
     }, "required": ["yaml_content"]}},
    {"name": "list_cluster_vms",
     "description": "List all VMs running on the connected OCP cluster. Call this when the user asks to check a VM YAML and has not provided a file path.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "fetch_cluster_vm_yaml",
     "description": "Fetch a VM YAML from the OCP cluster by name and namespace, save to a temp file, and return the file path. Use this before calling check_vm_config or validate_linux_vm_config.",
     "input_schema": {"type": "object", "properties": {
         "name":      {"type": "string", "description": "VM name"},
         "namespace": {"type": "string", "description": "Namespace the VM is in"}
     }, "required": ["name", "namespace"]}},
    {"name": "check_vm_config",
     "description": "Audit a Windows VM YAML configuration against the recommended template. Checks hyperv enlightenments, clock timers, ioThreads, autoattachMemBalloon, machine type, firmware, and disk bus. Saves report to logs/.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string", "description": "Absolute path to the Windows VM YAML file"}}, "required": ["path"]}},
    {"name": "validate_linux_vm_config",
     "description": "Audit a Linux VM YAML configuration against benchmark-runner best practices. Checks disk bus (virtio), network model, CPU requests/limits, dedicatedCpuPlacement, ioThreadsPolicy, machine type, evictionStrategy. Saves report to logs/.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string", "description": "Absolute path to the Linux VM YAML file"}}, "required": ["path"]}},
    {"name": "github_get_issue", "description": "Fetch a single GitHub issue or PR by repository and issue number.", "input_schema": {"type": "object", "properties": {"repo": {"type": "string", "description": "owner/repo"}, "number": {"type": "integer", "description": "Issue or PR number"}}, "required": ["repo", "number"]}},
    {"name": "github_list_issues", "description": "List issues for a GitHub repository.", "input_schema": {"type": "object", "properties": {"repo": {"type": "string", "description": "owner/repo"}, "state": {"type": "string", "description": "open, closed, or all (default: open)"}, "limit": {"type": "integer", "description": "Max results (default: 20)"}}, "required": ["repo"]}},
    {"name": "github_search_issues", "description": "Search GitHub issues and PRs using a search query string.", "input_schema": {"type": "object", "properties": {"query": {"type": "string", "description": "GitHub search query"}, "limit": {"type": "integer", "description": "Max results (default: 20)"}}, "required": ["query"]}},
    {"name": "github_create_issue", "description": "Create a new issue in a GitHub repository.", "input_schema": {"type": "object", "properties": {"repo": {"type": "string", "description": "owner/repo"}, "title": {"type": "string", "description": "Issue title"}, "body": {"type": "string", "description": "Issue body"}}, "required": ["repo", "title"]}},
    {"name": "github_add_comment", "description": "Add a comment to an existing GitHub issue or PR.", "input_schema": {"type": "object", "properties": {"repo": {"type": "string", "description": "owner/repo"}, "number": {"type": "integer", "description": "Issue or PR number"}, "body": {"type": "string", "description": "Comment text"}}, "required": ["repo", "number", "body"]}},
    {"name": "github_search_code", "description": "Search for files or code content inside GitHub repositories.", "input_schema": {"type": "object", "properties": {"query": {"type": "string", "description": "Search query, e.g. 'windows yaml'"}, "limit": {"type": "integer", "description": "Max results (default: 10)"}}, "required": ["query"]}},
    {"name": "github_get_file", "description": "Get the full content of a file from a GitHub repository by its path.", "input_schema": {"type": "object", "properties": {"repo": {"type": "string", "description": "owner/repo"}, "path": {"type": "string", "description": "File path in the repo"}}, "required": ["repo", "path"]}},
    {"name": "jira_get_issue", "description": "Fetch a single Jira issue by its key, e.g. PROJ-123.", "input_schema": {"type": "object", "properties": {"issue_key": {"type": "string", "description": "Jira issue key, e.g. PROJ-123"}}, "required": ["issue_key"]}},
    {"name": "jira_search_issues", "description": "Search Jira issues using a JQL query string.", "input_schema": {"type": "object", "properties": {"jql": {"type": "string", "description": "JQL query"}, "limit": {"type": "integer", "description": "Max results (default: 20)"}}, "required": ["jql"]}},
    {"name": "jira_create_issue", "description": "Create a new Jira issue in a project.", "input_schema": {"type": "object", "properties": {"project": {"type": "string", "description": "Jira project key"}, "summary": {"type": "string", "description": "Issue summary"}, "description": {"type": "string", "description": "Issue description"}, "issue_type": {"type": "string", "description": "Task, Bug, Story, etc."}}, "required": ["project", "summary"]}},
    {"name": "jira_update_issue", "description": "Update fields of an existing Jira issue.", "input_schema": {"type": "object", "properties": {"issue_key": {"type": "string", "description": "Jira issue key"}, "summary": {"type": "string"}, "description": {"type": "string"}, "assignee": {"type": "string"}}, "required": ["issue_key"]}},
    {"name": "jira_add_comment", "description": "Add a comment to an existing Jira issue.", "input_schema": {"type": "object", "properties": {"issue_key": {"type": "string", "description": "Jira issue key"}, "body": {"type": "string", "description": "Comment text"}}, "required": ["issue_key", "body"]}},
]
