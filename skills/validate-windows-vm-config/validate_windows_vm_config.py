#!/usr/bin/env python3
"""
Validate Windows VM YAML configuration against windows-vm-validation.yaml.
Usage: python3 validate_windows_vm_config.py <customer-vm.yaml>
Add new checks by editing windows-vm-validation.yaml — no Python change needed.
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
CHECKS_FILE = Path(__file__).parent / "windows-vm-validation.yaml"


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


def _version_gte(actual, threshold):
    """Compare version strings like 'pc-q35-rhel9.10.0' using integer tuple comparison."""
    import re
    def _parts(s):
        return tuple(int(x) if x.isdigit() else x for x in re.split(r'(\d+)', s))
    try:
        return _parts(actual) >= _parts(threshold)
    except TypeError:
        return actual >= threshold


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
    """Evaluate one rule. Returns (ok, actual_val, actual_str, expected_str, status).
    Returns None when a 'requires:' path guard is not satisfied (rule is skipped)."""
    path     = rule["path"]
    expected = rule["expected"]
    label    = rule.get("label", path.split(".")[-1])
    severity = rule.get("severity", "FAIL")
    msg      = rule.get("message", "")

    # optional guard: skip this rule if the required parent path is absent
    requires = rule.get("requires")
    if requires:
        req_root = spec if requires.startswith("spec:") else domain
        req_path = requires[5:] if requires.startswith("spec:") else requires
        if _get_path(req_root, req_path) is None:
            return None

    root       = spec if path.startswith("spec:") else domain
    clean_path = path[5:] if path.startswith("spec:") else path
    actual     = _get_path(root, clean_path)

    if expected == "~present~":
        ok          = actual is not None
        actual_str  = "present" if ok else "missing"
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
        result = _eval_rule(domain, spec, rule)
        if result is None:
            continue  # requires: guard not satisfied — skip
        ok, actual, actual_str, expected_str, status = result
        label   = rule.get("label", rule["path"].split(".")[-1])
        section = rule.get("section", rule["path"].split(".")[-1])
        msg     = rule.get("message", "")
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
    """Evaluate one rule. Returns (ok, actual_val, actual_str, expected_str, status).
    Returns None when a 'requires:' path guard is not satisfied (rule is skipped)."""
    path     = rule["path"]
    expected = rule["expected"]
    label    = rule.get("label", path.split(".")[-1])
    severity = rule.get("severity", "FAIL")
    msg      = rule.get("message", "")

    # optional guard: skip this rule if the required parent path is absent
    requires = rule.get("requires")
    if requires:
        req_root = spec if requires.startswith("spec:") else domain
        req_path = requires[5:] if requires.startswith("spec:") else requires
        if _get_path(req_root, req_path) is None:
            return None

    root       = spec if path.startswith("spec:") else domain
    clean_path = path[5:] if path.startswith("spec:") else path
    actual     = _get_path(root, clean_path)

    if expected == "~present~":
        ok          = actual is not None
        actual_str  = "present" if ok else "missing"
        expected_str = "required"
    elif isinstance(expected, str) and expected.startswith("~lte:"):
        n            = _to_int(expected[5:-1], 1)
        ok           = actual is None or _to_int(actual, n + 1) <= n
        actual_str   = str(actual) if actual is not None else "not set (default ≤)"
        expected_str = f"≤{n}"
    elif isinstance(expected, str) and expected.startswith("~gte:"):
        threshold    = expected[5:-1]
        ok           = bool(actual) and _version_gte(str(actual), threshold)
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
        result = _eval_rule(domain, spec, rule)
        if result is None:
            continue  # requires: guard not satisfied — skip
        ok, actual, actual_str, expected_str, status = result
        label   = rule.get("label", rule["path"].split(".")[-1])
        section = rule.get("section", rule["path"].split(".")[-1])
        msg     = rule.get("message", "")
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
    changes = []
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
            continue  # calculated / comparison — handled by special blocks below

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

    # ── clock group fix (if any clock rule failed, replace whole clock block) ─
    clock_labels = {"clock.hpet", "clock.hpet.present", "clock.hyperv",
                    "clock.pit", "clock.pit.tickPolicy", "clock.rtc", "clock.rtc.tickPolicy"}
    if any(lbl in clock_labels for _, _, lbl, _ in findings if _ or True):
        clock_failed = any(lbl in clock_labels for _, sec, lbl, _ in findings)
        if clock_failed and "clock" not in changes:
            domain["clock"] = {
                "timer": {
                    "hpet":  {"present": False},
                    "hyperv": {},
                    "pit":   {"tickPolicy": "delay"},
                    "rtc":   {"tickPolicy": "catchup"},
                },
                "utc": {},
            }
            changes.append("clock")
            comments.update({
                "present: false":      "# ADDED: HPET must be disabled",
                "hyperv: {}":          "# ADDED: hypervclock must be present",
                "tickPolicy: delay":   "# ADDED: PIT timer policy",
                "tickPolicy: catchup": "# ADDED: RTC timer policy",
                "utc: {}":             "# ADDED: UTC clock",
            })

    # ── ioThreads count fix (calculated) ──────────────────────────────────────
    if ("ioThreads", "supplementalPoolThreadCount") in actionable:
        cpu   = domain.get("cpu") or {}
        vcpus = _to_int(cpu.get("cores", 1), 1) * _to_int(cpu.get("sockets", 1), 1)
        rec   = max(2, min(vcpus // 4, 16)) if vcpus > 1 else 2
        domain["ioThreadsPolicy"] = "supplementalPool"
        domain["ioThreads"]       = {"supplementalPoolThreadCount": rec}
        if "ioThreadsPolicy" not in changes:
            changes.append("ioThreads")
        comments["supplementalPoolThreadCount:"] = f"# ADDED: {rec} threads for {vcpus} vCPUs"

    # ── hyperv enlightenments fix ─────────────────────────────────────────────
    hyperv_rules   = rules.get("features", {}).get("hyperv", {})
    hyperv_missing = [key for _, sec, key, _ in findings if sec == "hyperv"]
    if hyperv_missing:
        features = domain.setdefault("features", {})
        hyperv   = features.setdefault("hyperv", {})
        for key in hyperv_missing:
            if key == "spinlocks":
                hyperv[key] = {"spinlocks": hyperv_rules.get("spinlocks", {}).get("spinlocks", 8191)}
            elif key == "synictimer":
                hyperv[key] = {"direct": {}}
            else:
                hyperv[key] = {}
        features.setdefault("acpi", {})
        features.setdefault("apic", {})
        features.setdefault("smm", {})
        changes.append("hyperv enlightenments")
        comments.update({
            "ipi: {}":             "# ADDED: hyperv enlightenment",
            "synic: {}":           "# ADDED: hyperv enlightenment",
            "synictimer:":         "# ADDED: hyperv enlightenment",
            "direct: {}":          "# ADDED: synictimer direct mode",
            "spinlocks:":          "# ADDED: hyperv enlightenment",
            "spinlocks: 8191":     "# ADDED: must be 8191",
            "reenlightenment: {}": "# ADDED: hyperv enlightenment",
            "reset: {}":           "# ADDED: hyperv enlightenment",
            "relaxed: {}":         "# ADDED: hyperv enlightenment",
            "vpindex: {}":         "# ADDED: hyperv enlightenment",
            "runtime: {}":         "# ADDED: hyperv enlightenment",
            "tlbflush: {}":        "# ADDED: hyperv enlightenment",
            "frequencies: {}":     "# ADDED: hyperv enlightenment",
            "vapic: {}":           "# ADDED: hyperv enlightenment",
        })

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
    devices = domain.get("devices") or {}
    cpu     = domain.get("cpu") or {}
    features   = domain.get("features") or {}
    hyperv_cfg = features.get("hyperv") or {}

    def _fail(section, key, detail):
        findings.append(("FAIL", section, key, detail))

    def _warn(section, key, detail):
        findings.append(("WARN", section, key, detail))

    def _ok(section, key):
        passes.append((section, key))

    # ── NIC model (special: per-interface) ───────────────────────────────────
    if special.get("nic_model"):
        interfaces = devices.get("interfaces") or []
        nic_models = {iface.get("model", "virtio") for iface in interfaces}
        bad_nics   = nic_models & {"e1000", "e1000e", "rtl8139"}
        if bad_nics:
            _fail("devices", "NIC model", f"non-virtio NIC ({', '.join(sorted(bad_nics))}) — switch to model: virtio")
        else:
            _ok("devices", "NIC model")

    # ── disk bus (special: per-disk, WARN if non-virtio/scsi) ────────────────
    if special.get("disk_bus"):
        disks    = devices.get("disks") or []
        bus_vals = list({(d.get("disk") or {}).get("bus", "?") for d in disks})
        ok_bus   = all(b in ("virtio", "scsi") for b in bus_vals)
        if not ok_bus:
            _warn("devices", "disk bus", f"non-virtio/scsi bus: {', '.join(bus_vals)}")
        else:
            _ok("devices", "disk bus")

    # ── ioThreads count (special: calculated from vCPU count) ────────────────
    if special.get("io_threads_count"):
        io_count  = (domain.get("ioThreads") or {}).get("supplementalPoolThreadCount")
        vcpus     = _to_int(cpu.get("cores", 1), 1) * _to_int(cpu.get("sockets", 1), 1)
        rec_threads = max(2, min(vcpus // 4, 16)) if vcpus > 1 else 2
        if not io_count:
            _fail("ioThreads", "supplementalPoolThreadCount",
                  f"not set (want ≥{rec_threads} based on {vcpus} vCPUs)")
        else:
            _ok("ioThreads", "supplementalPoolThreadCount")

    # ── hyperv enlightenments (special: dynamic key list + nested validation) ─
    if special.get("hyperv_enlightenments"):
        hyperv_rules = rules.get("features", {}).get("hyperv", {})
        required_hv  = [k for k, v in hyperv_rules.items() if v == "required" or isinstance(v, dict)]
        for key in required_hv:
            if key not in hyperv_cfg:
                _fail("hyperv", key, "missing from features.hyperv")
            elif key == "spinlocks":
                val      = (hyperv_cfg[key] or {}).get("spinlocks") if isinstance(hyperv_cfg[key], dict) else None
                exp_val  = hyperv_rules.get("spinlocks", {}).get("spinlocks", 8191)
                if val != exp_val:
                    _fail("hyperv", key, f"spinlocks={val} (want {exp_val})")
                else:
                    _ok("hyperv", key)
            elif key == "synictimer":
                direct = isinstance(hyperv_cfg.get(key), dict) and "direct" in hyperv_cfg[key]
                if not direct:
                    _fail("hyperv", key, "missing 'direct: {}' inside synictimer")
                else:
                    _ok("hyperv", key)
            else:
                _ok("hyperv", key)

    # ── output ────────────────────────────────────────────────────────────────
    fails    = sum(1 for s, *_ in findings if s == "FAIL")
    warns    = sum(1 for s, *_ in findings if s == "WARN")
    severity = "CRITICAL" if fails > 0 else ("WARNING" if warns > 0 else "OK")

    lines = []
    lines.append("=" * 65)
    lines.append("WINDOWS VM CONFIGURATION AUDIT")
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

    if special.get("nic_model"):
        nic_models = {iface.get("model", "virtio") for iface in (devices.get("interfaces") or [])}
        bad_nics   = nic_models & {"e1000", "e1000e", "rtl8139"}
        nic_str    = ", ".join(sorted(nic_models)) if nic_models else "virtio (default)"
        table_rows.append(("NIC model", nic_str, "virtio",
                           "❌ WRONG MODEL" if bad_nics else "✅ OK"))

    if special.get("disk_bus"):
        disks    = devices.get("disks") or []
        bus_vals = list({(d.get("disk") or {}).get("bus", "?") for d in disks})
        ok_bus   = all(b in ("virtio", "scsi") for b in bus_vals)
        bus_str  = ", ".join(bus_vals) if bus_vals else "not set"
        table_rows.append(("disk bus", bus_str, "virtio (or scsi for OCP 4.22)",
                           "✅ OK" if ok_bus else "⚠️ CHECK"))

    if special.get("io_threads_count"):
        io_count    = (domain.get("ioThreads") or {}).get("supplementalPoolThreadCount")
        vcpus       = _to_int(cpu.get("cores", 1), 1) * _to_int(cpu.get("sockets", 1), 1)
        rec_threads = max(2, min(vcpus // 4, 16)) if vcpus > 1 else 2
        rec_str     = f"≥{rec_threads} (based on {vcpus} vCPUs)"
        table_rows.append(("ioThreads", str(io_count) if io_count else "None", rec_str,
                           "✅ OK" if io_count else "❌ MISSING (requires OCP 4.19+)"))

    if special.get("hyperv_enlightenments"):
        hyperv_rules = rules.get("features", {}).get("hyperv", {})
        required_hv  = [k for k, v in hyperv_rules.items() if v == "required" or isinstance(v, dict)]
        present_hv   = [k for k in required_hv if k in hyperv_cfg]
        missing_hv   = [k for k in required_hv if k not in hyperv_cfg]
        all_hv_str   = f"all {len(required_hv)} enlightenments"
        if not missing_hv:
            table_rows.append(("hyperv enlightenments", f"all {len(required_hv)} present", all_hv_str, "✅ OK"))
        elif not present_hv:
            table_rows.append(("hyperv enlightenments", "None", all_hv_str,
                               "❌ MISSING — no hyperv features at all"))
        else:
            table_rows.append(("hyperv enlightenments", f"{len(present_hv)}/{len(required_hv)} present",
                               all_hv_str, f"❌ PARTIAL — missing: {', '.join(missing_hv[:3])}..."))

    def _sort_key(r):
        s = r[3]
        if s.startswith("❌"): return 0
        if s.startswith("⚠️"): return 1
        return 2

    for setting, customer, recommended, status in sorted(table_rows, key=_sort_key):
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

    lines.append("")
    lines.append("─" * 65)
    lines.append("GUEST-SIDE STEPS (always required for Windows VMs)")
    lines.append("─" * 65)
    lines.append("  1. Remove platform clock override (run inside guest, then reboot):")
    lines.append("       bcdedit /deletevalue useplatformclock")
    lines.append("  2. Verify VBS is disabled (run inside Windows guest, then reboot):")
    lines.append("       msinfo32 → Virtualization-based security: Not enabled")
    lines.append("     To disable: Windows Security → Device Security → Core isolation")
    lines.append("                 → Memory integrity → Off  (then reboot)")
    lines.append("  3. Apply C1 tuned profile on worker nodes (pins CPUs to C1 for low latency):")
    lines.append("       oc apply -f skills/ocp-analysis/tuned-c1.yaml")
    lines.append("     Verify: oc get profile.tuned.openshift.io -n openshift-cluster-node-tuning-operator")

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


def _detect_os(vm_path):
    """Detect VM OS — returns 'windows', 'linux', or 'unknown'."""
    doc    = _load(vm_path)
    domain = (doc.get("spec", {}).get("template", {}).get("spec", {}).get("domain", {}))
    if domain.get("features", {}).get("hyperv"):
        return "windows"
    preference = (doc.get("spec") or {}).get("preference", {}).get("name", "")
    if "windows" in preference.lower():
        return "windows"
    os_label = ((doc.get("spec") or {}).get("template", {})
                .get("metadata", {}).get("annotations", {})
                .get("vm.kubevirt.io/os", ""))
    if os_label and "windows" in os_label.lower():
        return "windows"
    if os_label and os_label not in ("", "__template__"):
        return "linux"
    return "unknown"


def _list_vms():
    """List all running VMs across all namespaces via oc CLI."""
    import subprocess
    try:
        result = subprocess.run(
            ["oc", "get", "vm", "--all-namespaces", "-o", "wide"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            print(f"ERROR: {result.stderr.strip()}", file=sys.stderr)
            sys.exit(1)
        print(result.stdout)
    except FileNotFoundError:
        print("ERROR: 'oc' not found — is OpenShift CLI installed?", file=sys.stderr)
        sys.exit(1)


def _fetch_vm_yaml(name, namespace):
    """Fetch VM YAML from cluster via oc CLI and return a temp file path."""
    import subprocess
    import tempfile
    try:
        result = subprocess.run(
            ["oc", "get", "vm", name, "-n", namespace, "-o", "yaml"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            print(f"ERROR: {result.stderr.strip()}", file=sys.stderr)
            sys.exit(1)
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False)
        tmp.write(result.stdout)
        tmp.close()
        return tmp.name
    except FileNotFoundError:
        print("ERROR: 'oc' not found — is OpenShift CLI installed?", file=sys.stderr)
        sys.exit(1)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Check Windows VM YAML against best practices")
    parser.add_argument("vm_yaml", help="Path to VM YAML file")
    parser.add_argument("--os", choices=["windows", "linux"], help="Override OS detection")
    args = parser.parse_args()

    vm_path    = args.vm_yaml
    detected_os = args.os or _detect_os(vm_path)
    if detected_os == "linux":
        print("ERROR: VM detected as Linux — use validate_linux_vm_config.py for Linux VMs.",
              file=sys.stderr)
        sys.exit(1)
    if detected_os == "unknown":
        print("Note: OS not detected from YAML — running Windows check (use --os to override).")

    report = check(vm_path)
    print(report)

    LOGS_DIR.mkdir(exist_ok=True)
    run_uuid = uuid.uuid4().hex[:8]
    ts  = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    out = LOGS_DIR / f"perfx_{run_uuid}_{ts}.log"
    out.write_text(report, encoding="utf-8")
    print(f"\nReport saved to: {out}")


if __name__ == "__main__":
    main()
