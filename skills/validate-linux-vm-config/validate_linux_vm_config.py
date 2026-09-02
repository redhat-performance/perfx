#!/usr/bin/env python3
"""
Validate Linux VM YAML configuration against linux-vm-validation.yaml.
Usage: python3 validate_linux_vm_config.py <customer-vm.yaml>
Add new checks by editing linux-vm-validation.yaml — no Python change needed.
"""
import os
import sys
import re
import uuid
from datetime import datetime
from pathlib import Path

try:
    import yaml
except ImportError:
    print("ERROR: pyyaml not installed. Run: pip install pyyaml", file=sys.stderr)
    sys.exit(1)


LOGS_DIR    = Path(os.environ.get("PERFX_LOGS_DIR", Path(__file__).parent.parent.parent / "logs"))
CHECKS_FILE = Path(__file__).parent / "linux-vm-validation.yaml"


def _load(path):
    with open(path) as f:
        raw = f.read()
    raw = re.sub(r'\{%-?.*?-?%\}', '', raw)
    raw = re.sub(r'\{\{.*?\}\}', '"__template__"', raw)
    docs = list(yaml.safe_load_all(raw))
    docs = [d for d in docs if d]
    for doc in docs:
        if doc.get("kind") == "VirtualMachine":
            return doc
    return docs[0] if docs else {}


def _domain(doc):
    return (doc.get("spec", {})
               .get("template", {})
               .get("spec", {})
               .get("domain", {}))


def _load_checks():
    if not CHECKS_FILE.exists():
        print(f"ERROR: rules file not found: {CHECKS_FILE}", file=sys.stderr)
        sys.exit(1)
    return yaml.safe_load(CHECKS_FILE.read_text())


def _to_int(v, default=1):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


# ── generic evaluator (data-driven checks from rules YAML) ───────────────────

def _get_path(root, path):
    """Traverse dot-separated path in a nested dict; return None if missing."""
    value = root
    for key in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _eval_rule(domain, spec, rule):
    """Evaluate one rule. Returns (ok, actual_val, actual_str, expected_str, status)."""
    path     = rule["path"]
    expected = rule["expected"]
    severity = rule.get("severity", "FAIL")
    msg      = rule.get("message", "")

    root       = spec if path.startswith("spec:") else domain
    clean_path = path[5:] if path.startswith("spec:") else path
    actual     = _get_path(root, clean_path)

    if expected == "~present~":
        ok           = actual is not None
        actual_str   = "present" if ok else "missing"
        expected_str = "required"
    elif isinstance(expected, str) and expected.startswith("~lte:"):
        n            = _to_int(expected[5:-1], 1)
        ok           = actual is None or _to_int(actual, n + 1) <= n
        actual_str   = str(actual) if actual is not None else "not set (default ≤)"
        expected_str = f"≤{n}"
    elif isinstance(expected, str) and expected.startswith("~gte:"):
        threshold    = expected[5:-1]
        ok           = bool(actual) and str(actual) >= threshold
        actual_str   = str(actual) if actual is not None else "not set"
        expected_str = f"≥{threshold}"
    else:
        ok           = actual == expected
        actual_str   = str(actual).lower() if isinstance(actual, bool) else (str(actual) if actual is not None else "not set")
        expected_str = str(expected).lower() if isinstance(expected, bool) else str(expected)

    if ok:
        status = "✅ OK"
    elif severity == "FAIL":
        status = "❌ MISSING" if actual is None else "❌ WRONG"
    else:
        status = f"⚠️ {msg}" if msg else "⚠️ CHECK"

    return ok, actual, actual_str, expected_str, status


def _eval_checks(domain, spec, checks_list):
    """Run all generic rules. Returns (findings, passes, table_rows)."""
    findings   = []
    passes     = []
    table_rows = []

    for rule in checks_list:
        ok, actual, actual_str, expected_str, status = _eval_rule(domain, spec, rule)
        label    = rule.get("label", rule["path"].split(".")[-1])
        section  = rule.get("section", rule["path"].split(".")[-1])
        msg      = rule.get("message", "")
        severity = rule.get("severity", "FAIL")

        table_rows.append((label, actual_str, expected_str, status))

        if ok:
            passes.append((section, label))
        elif severity == "FAIL":
            detail = f"={actual!r} (want {rule['expected']!r})" if actual is not None else f"missing (want {rule['expected']!r})"
            findings.append(("FAIL", section, label, detail))
        else:
            detail = f"={actual!r} — {msg}" if msg else f"={actual!r} (want {rule['expected']!r})"
            findings.append(("WARN", section, label, detail))

    return findings, passes, table_rows


# ── corrected YAML generation ─────────────────────────────────────────────────

def _generate_corrected_yaml(vm_path, findings):
    """Generate corrected VM YAML: auto-applies fix:true rules + special fixes."""
    doc    = _load(vm_path)
    domain = _domain(doc)
    spec   = (doc.get("spec") or {}).get("template", {}).setdefault("spec", {})
    rules  = _load_checks()
    changes  = []
    comments = {}

    actionable = {(sec, key) for _, sec, key, _ in findings}

    # ── auto-fix simple rules with fix: true ──────────────────────────────────
    for rule in rules.get("checks", []):
        if not rule.get("fix"):
            continue
        label    = rule.get("label", rule["path"].split(".")[-1])
        section  = rule.get("section", rule["path"].split(".")[-1])
        expected = rule["expected"]

        if (section, label) not in actionable:
            continue
        if isinstance(expected, str) and expected.startswith("~"):
            continue

        path       = rule["path"]
        root       = spec if path.startswith("spec:") else domain
        clean_path = path[5:] if path.startswith("spec:") else path
        keys       = clean_path.split(".")
        target     = root
        for key in keys[:-1]:
            if not isinstance(target.get(key), dict):
                target[key] = {}
            target = target[key]
        target[keys[-1]] = expected
        changes.append(label)
        if rule.get("message"):
            yaml_val = str(expected).lower() if isinstance(expected, bool) else str(expected)
            comments[f"{keys[-1]}: {yaml_val}"] = f"# ADDED: {rule['message']}"

    # ── ioThreads count fix (calculated) ──────────────────────────────────────
    if ("ioThreads", "supplementalPoolThreadCount") in actionable:
        cpu   = domain.get("cpu") or {}
        vcpus = _to_int(cpu.get("cores", 1), 1) * _to_int(cpu.get("sockets", 1), 1)
        rec   = max(4, min(vcpus // 4, 16)) if vcpus > 1 else 4
        domain["ioThreadsPolicy"] = "supplementalPool"
        domain["ioThreads"]       = {"supplementalPoolThreadCount": rec}
        if "ioThreadsPolicy" not in changes:
            changes.append("ioThreads")
        comments["supplementalPoolThreadCount:"] = f"# ADDED: {rec} threads for {vcpus} vCPUs"

    # ── blockMultiQueue fix (special) ─────────────────────────────────────────
    if ("devices", "blockMultiQueue") in actionable:
        domain.setdefault("devices", {})["blockMultiQueue"] = True
        changes.append("blockMultiQueue")
        comments["blockMultiQueue: true"] = "# ADDED: enables multi-queue for block devices"

    # ── networkInterfaceMultiqueue fix (special) ──────────────────────────────
    if ("devices", "networkInterfaceMultiqueue") in actionable:
        domain.setdefault("devices", {})["networkInterfaceMultiqueue"] = True
        changes.append("networkInterfaceMultiqueue")
        comments["networkInterfaceMultiqueue: true"] = "# ADDED: enables multi-queue for network"

    # ── clean kubernetes metadata ─────────────────────────────────────────────
    meta = doc.get("metadata", {})
    for field in ["managedFields", "resourceVersion", "uid", "creationTimestamp",
                  "generation", "finalizers", "annotations"]:
        meta.pop(field, None)
    doc.pop("status", None)

    raw = yaml.dump(doc, default_flow_style=False, sort_keys=False).rstrip()
    annotated = []
    for line in raw.splitlines():
        stripped = line.strip()
        comment  = next((v for k, v in comments.items()
                         if stripped == k or stripped.startswith(k + " ")
                         or stripped.startswith(k + ":") or stripped == k + ":"
                         or (": " in k and stripped == k)), None)
        if comment and not stripped.startswith("#"):
            line = f"{line}  {comment}"
        annotated.append(line)

    out = [f"# Corrected YAML — changes applied: {', '.join(changes)}"]
    out.append("# Review before applying: oc apply -f <this-file>")
    out.append("")
    out.extend(annotated)
    return "\n".join(out)


def check(vm_path):
    doc     = _load(vm_path)
    domain  = _domain(doc)
    vm_name = doc.get("metadata", {}).get("name", Path(vm_path).stem)
    rules   = _load_checks()
    spec    = (doc.get("spec") or {}).get("template", {}).get("spec", {})

    # ── generic data-driven checks ────────────────────────────────────────────
    findings, passes, gen_rows = _eval_checks(domain, spec, rules.get("checks", []))

    special = rules.get("special_checks", {})
    devices  = domain.get("devices") or {}
    cpu      = domain.get("cpu") or {}

    def _fail(section, key, detail):
        findings.append(("FAIL", section, key, detail))

    def _warn(section, key, detail):
        findings.append(("WARN", section, key, detail))

    def _ok(section, key):
        passes.append((section, key))

    # ── blockMultiQueue (special: data-driven but not in default Linux rules) ─
    if special.get("block_multi_queue"):
        bmq = devices.get("blockMultiQueue")
        if bmq is not True:
            _fail("devices", "blockMultiQueue", f"={bmq!r} (want True)")
        else:
            _ok("devices", "blockMultiQueue")

    # ── networkInterfaceMultiqueue (special) ──────────────────────────────────
    if special.get("network_multiqueue"):
        net_mq = devices.get("networkInterfaceMultiqueue")
        if net_mq is not True:
            _fail("devices", "networkInterfaceMultiqueue", f"={net_mq!r} (want True)")
        else:
            _ok("devices", "networkInterfaceMultiqueue")

    # ── NIC model (special: per-interface) ───────────────────────────────────
    if special.get("nic_model"):
        interfaces = devices.get("interfaces") or []
        nic_models = {iface.get("model", "virtio") for iface in interfaces}
        bad_nics   = nic_models & {"e1000", "e1000e", "rtl8139"}
        if bad_nics:
            _fail("devices", "NIC model", f"non-virtio NIC ({', '.join(sorted(bad_nics))}) — switch to model: virtio")
        else:
            _ok("devices", "NIC model")

    # ── disk bus (special: per-disk, FAIL if non-virtio) ─────────────────────
    if special.get("disk_bus"):
        disks      = devices.get("disks") or []
        bus_issues = []
        for disk in disks:
            bus = (disk.get("disk") or {}).get("bus", "")
            if bus and bus != "virtio":
                bus_issues.append(f"{disk.get('name','?')}: bus={bus!r}")
        if bus_issues:
            _fail("devices", "disk bus", f"non-virtio bus: {', '.join(bus_issues)}")
        else:
            _ok("devices", "disk bus")

    # ── ioThreads count (special: calculated from vCPU count) ────────────────
    if special.get("io_threads_count"):
        io_count    = (domain.get("ioThreads") or {}).get("supplementalPoolThreadCount")
        vcpus       = _to_int(cpu.get("cores", 1), 1) * _to_int(cpu.get("sockets", 1), 1)
        rec_threads = max(4, min(vcpus // 4, 16)) if vcpus > 1 else 4
        if not io_count:
            _fail("ioThreads", "supplementalPoolThreadCount",
                  f"not set (want ≥{rec_threads} based on {vcpus} vCPUs)")
        else:
            _ok("ioThreads", "supplementalPoolThreadCount")

    # ── output ────────────────────────────────────────────────────────────────
    fails    = sum(1 for s, *_ in findings if s == "FAIL")
    warns    = sum(1 for s, *_ in findings if s == "WARN")
    severity = "CRITICAL" if fails > 0 else ("WARNING" if warns > 0 else "OK")

    lines = []
    lines.append("=" * 65)
    lines.append("LINUX VM CONFIGURATION AUDIT")
    lines.append("=" * 65)
    lines.append(f"\nVM        : {vm_name}")
    lines.append(f"File      : {vm_path}")
    lines.append(f"Reference : {CHECKS_FILE}")
    lines.append(f"\nResult    : {fails} critical issue(s), {warns} warning(s), {len(passes)} check(s) passed")
    lines.append(f"Severity  : {severity}\n")

    lines.append(f"  {'Setting':<28} {'Customer VM':<45} {'Recommended':<50} Status")
    lines.append(f"  {'─'*28} {'─'*45} {'─'*50} {'─'*40}")

    # build table: generic rows + special rows
    table_rows = list(gen_rows)

    if special.get("disk_bus"):
        disks      = devices.get("disks") or []
        bus_issues = [(disk.get("disk") or {}).get("bus", "") for disk in disks
                      if (disk.get("disk") or {}).get("bus", "") not in ("", "virtio")]
        bus_vals   = list({(d.get("disk") or {}).get("bus", "") for d in disks if (d.get("disk") or {}).get("bus")})
        bus_str    = ", ".join(sorted(bus_vals)) if bus_vals else "not set"
        table_rows.append(("disk bus", bus_str, "virtio",
                           "✅ OK" if not bus_issues else "❌ WRONG BUS"))

    if special.get("io_threads_count"):
        io_count    = (domain.get("ioThreads") or {}).get("supplementalPoolThreadCount")
        vcpus       = _to_int(cpu.get("cores", 1), 1) * _to_int(cpu.get("sockets", 1), 1)
        rec_threads = max(4, min(vcpus // 4, 16)) if vcpus > 1 else 4
        rec_str     = f"≥{rec_threads} (based on {vcpus} vCPUs)"
        table_rows.append(("ioThreads", str(io_count) if io_count else "None", rec_str,
                           "✅ OK" if io_count else "❌ MISSING (requires OCP 4.19+)"))

    for setting, customer, recommended, status in table_rows:
        lines.append(f"  {setting:<28} {customer:<45} {recommended:<50} {status}")

    lines.append("")
    lines.append("─" * 65)
    lines.append("FINDINGS")
    lines.append("─" * 65)
    if findings:
        lines.append(f"  Reference: {CHECKS_FILE.relative_to(CHECKS_FILE.parent.parent)}")
        lines.append("")
        lines.append(f"  {'Setting':<35} {'Issue'}")
        lines.append(f"  {'─'*35} {'─'*40}")
        for sev, section, key, detail in findings:
            prefix = "❌" if sev == "FAIL" else "⚠️"
            lines.append(f"  {prefix} {section+'.'+key:<33} {detail}")
    else:
        lines.append("  No issues found.")

    lines.append("")
    lines.append("─" * 65)
    lines.append("RECOMMENDATION")
    lines.append("─" * 65)
    if findings:
        lines.append("  Apply the fixes shown in CORRECTED VM YAML section below.")
    else:
        lines.append("  Configuration matches recommended template.")

    if findings:
        lines.append("")
        lines.append("─" * 65)
        lines.append("CORRECTED VM YAML")
        lines.append("─" * 65)
        lines.append(_generate_corrected_yaml(vm_path, findings))

    total_checks = len(findings) + len(passes)
    lines.append("")
    lines.append("─" * 65)
    lines.append("SUMMARY")
    lines.append("─" * 65)
    lines.append(f"  {len(passes)}/{total_checks} checks passed — {fails} critical, {warns} warning(s)")

    return "\n".join(lines)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Check Linux VM configuration against best practices")
    parser.add_argument("vm_yaml", help="Path to VM YAML file")
    args = parser.parse_args()

    report = check(args.vm_yaml)
    print(report)

    LOGS_DIR.mkdir(exist_ok=True)
    run_uuid = uuid.uuid4().hex[:8]
    ts   = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    out  = LOGS_DIR / f"perfx_{run_uuid}_{ts}.log"
    out.write_text(report, encoding="utf-8")
    print(f"\nReport saved to: {out}")


if __name__ == "__main__":
    main()
