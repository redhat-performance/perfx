import sys
import os
import argparse
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from perfx.logger import setup_logging, get_logger
from perfx.client import Agent

_env_path = Path(__file__).parent.parent / ".env"
load_dotenv(_env_path)

log = get_logger("main")

REPORTS_DIR = Path(os.environ.get("PERFX_LOGS_DIR", Path(__file__).parent.parent / "logs"))


def _save_report(content: str, fmt: str, output_dir: str = None):
    report_dir = Path(output_dir) if output_dir else REPORTS_DIR
    report_dir.mkdir(exist_ok=True)
    ext = "md" if fmt == "markdown" else "log"
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    path = report_dir / f"perfx_report_{timestamp}.{ext}"
    path.write_text(content)
    log.info("Report saved to %s", path)
    print(f"\nReport saved to: {path}")


def _cmd_logs(args):
    from perfx.analyzer import analyze
    from perfx.skills.registry import SkillRegistry

    if getattr(args, "list_skills", False):
        registry = SkillRegistry()
        print("Available skills:")
        for skill in registry.list():
            print(f"  {skill.name:15s} — {skill.description}")
        return

    source = args.logs
    if not source:
        log.error("provide a folder/file path with --logs")
        sys.exit(1)

    skill_names = [s.strip() for s in args.skill.split(",")] if args.skill else None
    fmt = args.output or "summary"

    log.info("Analyzing: %s", source)
    report = analyze(source, skill_names=skill_names)

    if fmt == "markdown":
        content = report.to_markdown()
    elif fmt == "text":
        content = report.to_text()
    else:
        content = report.to_summary()

    print(content)
    _save_report(content, fmt, output_dir=getattr(args, "output_dir", None))


def _cluster_available():
    """Return True if oc is available and logged into a cluster."""
    import subprocess
    try:
        result = subprocess.run(
            ["oc", "whoami"], capture_output=True, text=True, timeout=5
        )
        return result.returncode == 0
    except Exception:
        return False


def _collect_cluster_summary():
    """Run the ocp-analysis skill to print a full cluster summary including C1 tuned check."""
    import subprocess
    import tempfile
    import os

    script = Path(__file__).parent.parent / "skills" / "ocp-analysis" / "analyze_ocp.py"
    if not script.exists():
        return
    try:
        # collect nodes.json live
        nodes_result = subprocess.run(
            ["oc", "get", "nodes", "-o", "json"],
            capture_output=True, text=True, timeout=15
        )
        if nodes_result.returncode != 0:
            print("⚠️  Could not reach cluster (oc not logged in or unavailable)\n")
            return

        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
            f.write(nodes_result.stdout)
            nodes_file = f.name

        subprocess.run(["python3", str(script), "--nodes", nodes_file])
        os.unlink(nodes_file)

    except Exception as exc:
        log.debug("Cluster summary failed: %s", exc)


def main():
    setup_logging()

    parser = argparse.ArgumentParser(description="PerfX — performance knowledge base agent")
    parser.add_argument("--model", "-m", choices=["gemini", "claude"], default=None)
    parser.add_argument("--logs", metavar="PATH", help="Analyze log files (no agent required)")
    parser.add_argument("--skill", "-s", help="Comma-separated skill names (default: all)")
    parser.add_argument("--output", "-o", choices=["text", "markdown", "summary"], default="summary")
    parser.add_argument("--output-dir", metavar="DIR", help="Directory to save report (default: logs/)")
    args = parser.parse_args()

    if args.model:
        os.environ["PERFBOT_MODEL"] = args.model

    if args.logs:
        _cmd_logs(args)
        return

    model_name = os.environ.get("PERFBOT_MODEL", "claude").lower()
    print(f"PerfX Agent (powered by {model_name.capitalize()}). Type 'exit' or Ctrl-C to quit.")
    from perfx.client import _parse_repos
    repos = [r for r in _parse_repos() if "your-org" not in r]
    if repos:
        print(f"Configured repos: {', '.join(repos)}")
    print()

    REPORTS_DIR.mkdir(exist_ok=True)
    session_ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    session_log = REPORTS_DIR / f"perfx_session_{session_ts}.log"
    session_file = None

    try:
        if _cluster_available():
            answer = input("I noticed a running cluster — analyze it? (y/N): ").strip().lower()
            if answer in ("y", "yes"):
                _collect_cluster_summary()
    except (KeyboardInterrupt, EOFError):
        pass

    agent = Agent()
    while True:
        try:
            user_input = input("You: ").strip()
        except (KeyboardInterrupt, EOFError):
            if session_file:
                session_file.close()
            print("\nBye!")
            sys.exit(0)

        if not user_input:
            continue
        if user_input.lower() in {"exit", "quit"}:
            if session_file:
                session_file.close()
            print("Bye!")
            sys.exit(0)

        try:
            response = agent.chat(user_input)
            print(f"\nAgent: {response}\n")
            # only write log when a skill is invoked (starts with /)
            if user_input.startswith("/"):
                if session_file is None:
                    session_file = open(session_log, "w")
                    session_file.write(f"PerfX Session — {session_ts}\n{'='*60}\n\n")
                    print(f"Session log: {session_log}\n")
                session_file.write(f"You: {user_input}\n\nAgent: {response}\n\n{'─'*60}\n\n")
                session_file.flush()
        except Exception as exc:
            log.exception("Agent error")
            print(f"\n[Error] {exc}\n")


if __name__ == "__main__":
    main()
