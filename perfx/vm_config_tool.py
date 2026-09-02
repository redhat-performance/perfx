import os
import re
import uuid
import tempfile
from datetime import datetime
from pathlib import Path

LOGS_DIR = Path(__file__).parent.parent / "logs"

HYPERV_KEYS = [
    "relaxed", "vapic", "vpindex", "runtime", "reset",
    "reenlightenment", "tlbflush", "frequencies", "ipi",
    "synic", "synictimer", "spinlocks",
]

def detect_os(path: str) -> str:
    """Detect whether a VM YAML is for Windows or Linux.

    Returns 'windows' if hyperv features, a windows preference, or a windows
    OS label are present. Returns 'linux' only when the OS label explicitly
    confirms it. Falls back to 'windows' when detection is ambiguous so the
    more comprehensive Windows check runs rather than being silently skipped.
    """
    try:
        doc = _load_yaml(path)
    except Exception:
        return "windows"
    domain = (
        (doc.get("spec") or {})
        .get("template", {})
        .get("spec", {})
        .get("domain", {})
    )
    # hyperv features present → Windows
    if domain.get("features", {}).get("hyperv"):
        return "windows"
    # preference name contains 'windows' → Windows
    preference = (doc.get("spec") or {}).get("preference", {}).get("name", "")
    if "windows" in preference.lower():
        return "windows"
    # vm.kubevirt.io/os label — only trust an explicit non-empty value
    os_label = (
        (doc.get("spec") or {})
        .get("template", {})
        .get("metadata", {})
        .get("annotations", {})
        .get("vm.kubevirt.io/os", "")
    )
    if os_label and "windows" in os_label.lower():
        return "windows"
    if os_label and os_label not in ("", "__template__"):
        return "linux"
    # ambiguous — default to windows so the full check runs
    return "windows"


CLOCK_CHECKS = {
    "hpet":   ("present", False),
    "hyperv": None,
    "pit":    ("tickPolicy", "delay"),
    "rtc":    ("tickPolicy", "catchup"),
}


def _load_yaml(path: str) -> dict:
    import yaml
    raw = Path(path).read_text()
    raw = re.sub(r'\{%-?.*?-?%\}', '', raw)
    raw = re.sub(r'\{\{.*?\}\}', '"__template__"', raw)
    return yaml.safe_load(raw)


def _row(setting, customer, recommended, status):
    return {"setting": setting, "customer": customer, "recommended": recommended, "status": status}


def _save_report(vm_name: str, os_type: str, rows: list, summary: str) -> str:
    LOGS_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    run_uuid = uuid.uuid4().hex[:8]
    ts_file = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    path = LOGS_DIR / f"perfx_{run_uuid}_{ts_file}.log"
    col_w = [28, 45, 48, 38]
    header = (
        f"  {'Setting':<{col_w[0]}} {'Customer VM':<{col_w[1]}} {'Recommended':<{col_w[2]}} {'Status'}\n"
        f"  {'─'*col_w[0]} {'─'*col_w[1]} {'─'*col_w[2]} {'─'*col_w[3]}\n"
    )
    table_rows = "".join(
        f"  {r['setting']:<{col_w[0]}} {r['customer']:<{col_w[1]}} {r['recommended']:<{col_w[2]}} {r['status']}\n"
        for r in rows
    )
    entry = f"\n{'='*80}\nVM Config Audit — {os_type.upper()} — {vm_name}\nTimestamp: {timestamp}\n{summary}\n\n{header}{table_rows}"
    with open(path, "a") as f:
        f.write(entry)
    return str(path)


def _format_table(rows: list) -> str:
    col_w = [28, 45, 48, 38]
    lines = [
        f"  {'Setting':<{col_w[0]}} {'Customer VM':<{col_w[1]}} {'Recommended':<{col_w[2]}} {'Status'}",
        f"  {'─'*col_w[0]} {'─'*col_w[1]} {'─'*col_w[2]} {'─'*col_w[3]}",
    ]
    for r in rows:
        lines.append(
            f"  {r['setting']:<{col_w[0]}} {r['customer']:<{col_w[1]}} {r['recommended']:<{col_w[2]}} {r['status']}"
        )
    return "\n".join(lines)


def check_vm_config(path: str) -> dict:
    """Audit a KubeVirt Windows VM YAML and return a comparison table."""
    try:
        doc = _load_yaml(path)
    except FileNotFoundError:
        return {"error": f"File not found: {path}"}
    except Exception as e:
        return {"error": f"Failed to parse YAML: {e}"}

    domain = (
        (doc.get("spec") or {})
        .get("template", {})
        .get("spec", {})
        .get("domain", {})
    )
    devices  = domain.get("devices") or {}
    features = domain.get("features") or {}
    clock    = domain.get("clock") or {}
    cpu      = domain.get("cpu") or {}
    machine  = domain.get("machine") or {}
    firmware = domain.get("firmware") or {}
    resources = domain.get("resources") or {}
    vm_name  = (doc.get("metadata") or {}).get("name", "unknown")

    rows = []
    issues = 0

    # ── hyperv enlightenments ─────────────────────────────────────────────────
    hyperv = features.get("hyperv") or {}
    present_keys = [k for k in HYPERV_KEYS if k in hyperv]
    missing_keys = [k for k in HYPERV_KEYS if k not in hyperv]
    customer_hv = ",".join(present_keys) if present_keys else "None"
    recommended_hv = ",".join(HYPERV_KEYS)
    if missing_keys:
        rows.append(_row("hyperv enlightenments", customer_hv, recommended_hv,
                         f"❌ MISSING — {','.join(missing_keys)}"))
        issues += 1
    else:
        # check spinlocks value
        spinlocks_val = (hyperv.get("spinlocks") or {}).get("spinlocks")
        synictimer_ok = isinstance(hyperv.get("synictimer"), dict) and "direct" in hyperv["synictimer"]
        if spinlocks_val != 8191:
            rows.append(_row("hyperv enlightenments", customer_hv, recommended_hv,
                             f"⚠️ spinlocks={spinlocks_val!r} (want 8191)"))
            issues += 1
        elif not synictimer_ok:
            rows.append(_row("hyperv enlightenments", customer_hv, recommended_hv,
                             "⚠️ synictimer missing direct: {}"))
            issues += 1
        else:
            rows.append(_row("hyperv enlightenments", customer_hv, recommended_hv, "✅ OK"))

    # ── clock timers ─────────────────────────────────────────────────────────
    timer = clock.get("timer") or {}
    clock_offset = clock.get("utc") if "utc" in clock else clock.get("offset", "")
    customer_clock = f"UTC" if "utc" in clock else (clock_offset or "not set")
    if not timer:
        rows.append(_row("clock", customer_clock,
                         "hpet:false + hyperv + pit + rtc",
                         "❌ MISSING — no timer config"))
        issues += 1
    else:
        clock_issues = []
        for tname, check in CLOCK_CHECKS.items():
            if tname not in timer:
                clock_issues.append(f"{tname} missing")
            elif check:
                attr, want = check
                got = (timer[tname] or {}).get(attr) if isinstance(timer[tname], dict) else None
                if got != want:
                    clock_issues.append(f"{tname}.{attr}={got!r}")
        if clock_issues:
            rows.append(_row("clock", customer_clock,
                             "hpet:false + hyperv + pit + rtc",
                             f"⚠️ {', '.join(clock_issues)}"))
            issues += 1
        else:
            rows.append(_row("clock", "configured", "hpet:false + hyperv + pit + rtc", "✅ OK"))

    # ── ioThreads ─────────────────────────────────────────────────────────────
    iothreads_cfg = domain.get("ioThreads") or {}
    pool_count = iothreads_cfg.get("supplementalPoolThreadCount")
    vcpus = (cpu.get("cores", 1) or 1) * (cpu.get("sockets", 1) or 1)
    recommended_threads = max(4, min(vcpus // 4, 16))  # start at 4, scale with vCPUs, cap at 16
    rec_io = f"≥{recommended_threads} (based on {vcpus} vCPUs; start at 4, scale up for fast storage)"
    customer_io = f"supplementalPoolThreadCount: {pool_count}" if pool_count else "None"
    if not pool_count:
        status_io = "❌ MISSING (requires OCP 4.19+)"
        issues += 1
    elif pool_count < recommended_threads:
        status_io = f"⚠️ LOW — {pool_count} set, ≥{recommended_threads} recommended for {vcpus} vCPUs"
    else:
        status_io = "✅ OK"
    rows.append(_row("ioThreads", customer_io, rec_io, status_io))

    # ── ioThreadsPolicy ───────────────────────────────────────────────────────
    policy = domain.get("ioThreadsPolicy")
    rows.append(_row("ioThreadsPolicy", policy or "None", "supplementalPool",
                     "✅ OK" if policy == "supplementalPool" else "❌ MISSING (requires OCP 4.19+)"))
    if policy != "supplementalPool":
        issues += 1

    # ── autoattachMemBalloon ──────────────────────────────────────────────────
    balloon = devices.get("autoattachMemBalloon")
    if balloon is False:
        rows.append(_row("autoattachMemBalloon", "false", "false", "✅ OK"))
    elif balloon is None:
        rows.append(_row("autoattachMemBalloon", "Not set (defaults to true)", "false", "❌ MISSING"))
        issues += 1
    else:
        rows.append(_row("autoattachMemBalloon", str(balloon), "false", "❌ FAIL"))
        issues += 1

    # ── disk bus ──────────────────────────────────────────────────────────────
    disks = devices.get("disks") or []
    buses = list({(d.get("disk") or {}).get("bus", "") for d in disks if d.get("disk")})
    customer_bus = ", ".join(b for b in buses if b) or "not set"
    rows.append(_row("disk bus", customer_bus, "virtio (or scsi for OCP 4.22)",
                     "✅ OK" if "virtio" in buses or "scsi" in buses else "⚠️ check bus type"))

    # ── machine type ──────────────────────────────────────────────────────────
    mtype = machine.get("type", "not set")
    if "q35" not in mtype:
        status = "❌ not q35-based"
        issues += 1
    elif any(f"rhel9.{v}" in mtype for v in ["8", "9"]):
        status = "✅ OK"
    elif "rhel9." in mtype:
        status = "⚠️ OLD — too old for OCP 4.22 coalescing"
    else:
        status = "✅ OK"
    rows.append(_row("machine type", mtype, "pc-q35-rhel9.8.0+", status))

    # ── firmware ──────────────────────────────────────────────────────────────
    bootloader = (firmware.get("bootloader") or {})
    efi = bootloader.get("efi")
    bios = bootloader.get("bios")
    if efi is not None:
        customer_fw = f"efi: {efi}"
        fw_status = "✅ OK"
    elif bios is not None:
        customer_fw = "bios: {}"
        fw_status = "⚠️ Using legacy BIOS, not EFI"
    else:
        customer_fw = "not set"
        fw_status = "⚠️ Using legacy BIOS, not EFI"
    rows.append(_row("firmware", customer_fw, "efi: {secureBoot: false}", fw_status))

    # ── networkInterfaceMultiqueue ─────────────────────────────────────────────
    nmq = devices.get("networkInterfaceMultiqueue")
    rows.append(_row("networkInterfaceMultiqueue", str(nmq) if nmq is not None else "Not set",
                     "true", "✅ OK" if nmq is True else "❌ MISSING"))
    if nmq is not True:
        issues += 1

    # ── blockMultiQueue ───────────────────────────────────────────────────────
    bmq = devices.get("blockMultiQueue")
    rows.append(_row("blockMultiQueue", str(bmq) if bmq is not None else "Not set",
                     "true", "✅ OK" if bmq is True else "❌ MISSING"))
    if bmq is not True:
        issues += 1

    severity = "PASS" if issues == 0 else ("CRITICAL" if issues > 5 else "NEEDS ATTENTION")
    passed  = sum(1 for r in rows if "✅" in r["status"])
    failed  = len(rows) - passed
    summary = f"{severity}: {passed} passed, {failed} issues of {len(rows)} checks"

    log_file = _save_report(vm_name, "windows", rows, summary)

    return {
        "severity": severity,
        "vm_name": vm_name,
        "summary": summary,
        "table": _format_table(rows),
        "rows": rows,
        "log_file": log_file,
    }


def validate_linux_vm_config(path: str) -> dict:
    """Audit a KubeVirt Linux VM YAML and return a comparison table."""
    try:
        doc = _load_yaml(path)
    except FileNotFoundError:
        return {"error": f"File not found: {path}"}
    except Exception as e:
        return {"error": f"Failed to parse YAML: {e}"}

    domain = (
        (doc.get("spec") or {})
        .get("template", {})
        .get("spec", {})
        .get("domain", {})
    )
    devices   = domain.get("devices") or {}
    cpu       = domain.get("cpu") or {}
    machine   = domain.get("machine") or {}
    resources = domain.get("resources") or {}
    spec      = (doc.get("spec") or {}).get("template", {}).get("spec", {})
    vm_name   = (doc.get("metadata") or {}).get("name", "unknown")

    rows = []
    issues = 0

    # ── disk bus and cache ────────────────────────────────────────────────────
    disks = devices.get("disks") or []
    for disk in disks:
        disk_spec = disk.get("disk") or {}
        bus   = disk_spec.get("bus", "")
        cache = disk_spec.get("cache", "")
        name  = disk.get("name", "unnamed")
        if not bus:
            continue
        ok_bus = bus == "virtio"
        rows.append(_row(f"disk '{name}' bus", bus, "virtio",
                         "✅ OK" if ok_bus else f"❌ FAIL (got {bus!r})"))
        if not ok_bus:
            issues += 1
        ok_cache = cache == "none"
        rows.append(_row(f"disk '{name}' cache", cache if cache else "not set", "none",
                         "✅ OK" if ok_cache else "⚠️ NOT SET — risk of buffered IO after live migration"))
        if not ok_cache:
            issues += 1

    # ── blockMultiQueue ───────────────────────────────────────────────────────
    bmq = devices.get("blockMultiQueue")
    rows.append(_row("blockMultiQueue", str(bmq).lower() if bmq is not None else "not set", "true",
                     "✅ OK" if bmq is True else "⚠️ NOT SET (OCP 4.19+)"))
    if bmq is not True:
        issues += 1

    # ── ioThreads ─────────────────────────────────────────────────────────────
    iothreads_cfg = domain.get("ioThreads") or {}
    pool_count = iothreads_cfg.get("supplementalPoolThreadCount")
    rows.append(_row("ioThreads.supplementalPoolThreadCount",
                     str(pool_count) if pool_count else "not set", "≥4 (OCP 4.19+)",
                     "✅ OK" if pool_count and pool_count >= 4 else "⚠️ NOT SET — IO on vCPU threads"))
    if not pool_count:
        issues += 1

    # ── network model ─────────────────────────────────────────────────────────
    for iface in devices.get("interfaces") or []:
        model = iface.get("model", "not set")
        name = iface.get("name", "unnamed")
        ok = model == "virtio"
        rows.append(_row(f"interface '{name}' model", model, "virtio",
                         "✅ OK" if ok else f"❌ FAIL (got {model!r})"))
        if not ok:
            issues += 1

    # ── cpu requests / limits ─────────────────────────────────────────────────
    req = resources.get("requests") or {}
    lim = resources.get("limits") or {}
    for field, val in [("cpu", req.get("cpu")), ("memory", req.get("memory"))]:
        rows.append(_row(f"resources.requests.{field}", val or "not set", "set",
                         "✅ OK" if val else "❌ MISSING"))
        if not val:
            issues += 1
    for field, val in [("cpu", lim.get("cpu")), ("memory", lim.get("memory"))]:
        rows.append(_row(f"resources.limits.{field}", val or "not set",
                         "same as requests (guaranteed QoS)",
                         "✅ OK" if val else "⚠️ not set"))

    # ── dedicatedCpuPlacement ─────────────────────────────────────────────────
    dcp = cpu.get("dedicatedCpuPlacement")
    rows.append(_row("cpu.dedicatedCpuPlacement", str(dcp) if dcp is not None else "not set",
                     "true (for benchmarks)", "✅ OK" if dcp is True else "⚠️ not set"))

    # ── ioThreadsPolicy ───────────────────────────────────────────────────────
    policy = domain.get("ioThreadsPolicy")
    ok = policy in ("shared", "auto", "supplementalPool")
    rows.append(_row("ioThreadsPolicy", policy or "not set", "shared or supplementalPool",
                     "✅ OK" if ok else "⚠️ not set"))

    # ── machine type ──────────────────────────────────────────────────────────
    mtype = machine.get("type", "not set")
    rows.append(_row("machine type", mtype, "q35 or empty (default)",
                     "✅ OK" if ("q35" in mtype or mtype in ("", "not set")) else f"⚠️ {mtype!r}"))

    # ── evictionStrategy ─────────────────────────────────────────────────────
    eviction = spec.get("evictionStrategy")
    rows.append(_row("evictionStrategy", eviction or "not set", "LiveMigrate",
                     "✅ OK" if eviction == "LiveMigrate" else "⚠️ not set"))

    # ── cpu topology ─────────────────────────────────────────────────────────
    sockets = cpu.get("sockets", "not set")
    cores   = cpu.get("cores", "not set")
    rows.append(_row("cpu topology", f"{cores} cores, {sockets} sockets",
                     "1 socket, 1 thread", "✅ OK"))

    severity = "PASS" if issues == 0 else ("CRITICAL" if issues > 5 else "NEEDS ATTENTION")
    passed  = sum(1 for r in rows if "✅" in r["status"])
    failed  = len(rows) - passed
    summary = f"{severity}: {passed} passed, {failed} issues of {len(rows)} checks"

    log_file = _save_report(vm_name, "linux", rows, summary)

    return {
        "severity": severity,
        "vm_name": vm_name,
        "summary": summary,
        "table": _format_table(rows),
        "rows": rows,
        "log_file": log_file,
    }


def check_vm_config_from_path(path: str, os_type: str = None) -> dict:
    """Check VM config from a local file path.

    Preferred over check_vm_config_from_content when a file path is available —
    avoids passing the full YAML as a string argument.
    os_type: 'windows' or 'linux'. Auto-detects if not provided.
    """
    return _run_vm_config_check(path, os_type, cleanup=False)


def _run_vm_config_check(path: str, os_type: str = None, cleanup: bool = False) -> dict:
    """Run the appropriate VM config skill script (validate-windows-vm-config or validate-linux-vm-config).

    Routes to validate_linux_vm_config.py for Linux, validate_windows_vm_config.py for Windows/unknown.
    Returns a compact dict with severity, findings, and log path.
    """
    import subprocess
    try:
        detected = detect_os(path)
        resolved = os_type if os_type in ("windows", "linux") else detected
        if resolved == "linux":
            skill_script = Path(__file__).parent.parent / "skills" / "validate-linux-vm-config" / "validate_linux_vm_config.py"
        else:
            skill_script = Path(__file__).parent.parent / "skills" / "validate-windows-vm-config" / "validate_windows_vm_config.py"
        result = subprocess.run(
            ["python3", str(skill_script), path],
            capture_output=True, text=True, encoding="utf-8", timeout=30,
            env={**os.environ, "PYTHONUTF8": "1"}
        )
        full_output = result.stdout if result.stdout else result.stderr
        lines = full_output.splitlines()

        # extract key metrics
        result_line = next((l for l in lines if l.startswith("Result")), "")
        severity_line = next((l for l in lines if l.startswith("Severity")), "")
        summary_line = next((l for l in lines if "checks passed" in l), "")
        log_line = next((l for l in lines if "Report saved to:" in l), "")

        # extract only the FINDINGS lines (skip table — too many rows)
        findings = []
        in_findings = False
        for ln in lines:
            if ln.strip() == "FINDINGS" or "FINDINGS:" in ln:
                in_findings = True
                continue
            if in_findings:
                stripped = ln.strip()
                # Skip separators, headers, and empty "No issues found" messages
                if not stripped or stripped.startswith("─") or stripped.startswith("Setting") or "No issues found" in stripped or "Reference:" in stripped:
                    continue
                # Found a finding line
                if stripped.startswith("❌") or stripped.startswith("⚠️"):
                    findings.append(stripped)
                # Stop when we hit the next section
                elif findings and (stripped == "RECOMMENDATION" or stripped.startswith("─")):
                    break

        critical_count = sum(1 for f in findings if f.startswith("❌"))
        warn_count = sum(1 for f in findings if f.startswith("⚠️"))

        compact = []
        if result_line:
            compact.append(result_line)
        if severity_line:
            compact.append(severity_line)
        compact.append(f"IMPORTANT: There are exactly {critical_count} critical (❌) and {warn_count} warning (⚠️) issues. Do not recount.")
        if findings:
            compact.append("\nFindings:")
            compact.extend(f"  {f}" for f in findings)
        # extract GUEST-SIDE STEPS verbatim so agent does not rephrase them
        guest_steps = []
        in_guest = False
        passed_header_sep = False
        for ln in lines:
            if "GUEST-SIDE STEPS" in ln:
                in_guest = True
                continue
            if in_guest:
                if ln.startswith("─"):
                    if not passed_header_sep:
                        passed_header_sep = True  # skip the separator under the header
                        continue
                    break  # next section separator — stop
                guest_steps.append(ln)

        if summary_line:
            compact.append(f"\n{summary_line.strip()}")
        if guest_steps:
            compact.append("")
            compact.extend(guest_steps)
        if log_line:
            compact.append(log_line)
        compact.append("\nINSTRUCTION: Show the GUEST-SIDE STEPS above exactly as written. State severity in 1 sentence. Do not rephrase or use emoji codes like :wrench:.")

        return {
            "severity": "CRITICAL" if "❌" in full_output else "PASS",
            "detected_os": detected,
            "used_os": resolved,
            "table": "\n".join(compact),
            "summary": f"VM config checked as {resolved}. Full report: {log_line}",
        }
    finally:
        if cleanup:
            Path(path).unlink(missing_ok=True)


def check_vm_config_from_content(yaml_content: str, os_type: str = None) -> dict:
    """Check VM config from YAML content string.

    Prefer check_vm_config_from_path when a file path is available.
    os_type: 'windows' or 'linux'. Auto-detects if not provided.
    """
    tmp = tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False)
    tmp.write(yaml_content)
    tmp.close()
    return _run_vm_config_check(tmp.name, os_type, cleanup=True)
