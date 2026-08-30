#!/usr/bin/env python3
"""
Analyze pre-collected OCP cluster data from local JSON files.

Usage:
  python3 collect_ocp_data.py --nodes nodes.json [--version version.json] [--vmis vmis.json]

Collect the input files with:
  oc get nodes -o json > nodes.json
  oc version -o json  > version.json
  oc get vmi -A -o json > vmis.json
"""
import json
import sys
from pathlib import Path


def parse_ocp_version(version_data: dict) -> str:
    """Extract OCP version string from oc version JSON."""
    return version_data.get("openshiftVersion", "unknown")


def parse_cnv_version(csv_data: dict) -> str:
    """Extract CNV version from oc get csv JSON."""
    for item in csv_data.get("items", []):
        name = item.get("metadata", {}).get("name", "")
        if "kubevirt-hyperconverged" in name:
            return item.get("spec", {}).get("version", name)
    return "not installed"


def parse_nodes(nodes_data: dict) -> list:
    """Parse oc get nodes -o json into a list of node summary dicts."""
    nodes = []
    for item in nodes_data.get("items", []):
        meta   = item.get("metadata", {})
        status = item.get("status", {})
        labels = meta.get("labels", {})

        name = meta.get("name", "unknown")
        role = "worker"
        if "node-role.kubernetes.io/control-plane" in labels or "node-role.kubernetes.io/master" in labels:
            role = "control-plane"

        capacity  = status.get("capacity", {})
        alloc     = status.get("allocatable", {})
        node_info = status.get("nodeInfo", {})

        nodes.append({
            "name":      name,
            "role":      role,
            "cpu":       capacity.get("cpu", "?"),
            "memory":    _to_gib(capacity.get("memory", "0Ki")),
            "alloc_cpu": alloc.get("cpu", "?"),
            "alloc_mem": _to_gib(alloc.get("memory", "0Ki")),
            "kernel":    node_info.get("kernelVersion", "?"),
            "os":        node_info.get("osImage", "?"),
        })
    return nodes


def parse_vm_counts(vmis_data: dict) -> dict:
    """Parse oc get vmi -A -o json into per-node VM counts."""
    counts = {}
    for item in vmis_data.get("items", []):
        node = item.get("status", {}).get("nodeName", "")
        if node:
            counts[node] = counts.get(node, 0) + 1
    return counts


def _to_gib(mem_str: str) -> str:
    """Convert a Kubernetes memory quantity to a human-readable GiB string."""
    try:
        if mem_str.endswith("Ki"):
            gib = int(mem_str[:-2]) / (1024 * 1024)
        elif mem_str.endswith("Mi"):
            gib = int(mem_str[:-2]) / 1024
        elif mem_str.endswith("Gi"):
            return mem_str
        else:
            return mem_str
        return f"{gib:.1f}Gi" if gib != int(gib) else f"{int(gib)}Gi"
    except Exception:
        return mem_str


def print_table(nodes: list, counts: dict) -> None:
    """Print a formatted node summary table."""
    col = [28, 14, 8, 10, 14, 14, 22, 16, 10]
    headers = ["Node", "Role", "CPU", "Memory", "Alloc CPU", "Alloc Mem", "Kernel", "OS", "VMs"]
    sep = "─" * sum(col)

    def row(*vals):
        return "  " + "".join(str(v)[:col[i]].ljust(col[i]) for i, v in enumerate(vals))

    print(sep)
    print(row(*headers))
    print(sep)
    for n in nodes:
        vms = counts.get(n["name"], 0)
        os_short = n["os"].replace("Red Hat Enterprise Linux CoreOS ", "RHCOS ")
        print(row(n["name"], n["role"], n["cpu"], n["memory"],
                  n["alloc_cpu"], n["alloc_mem"], n["kernel"], os_short, vms))
    print(sep)


def analyze(nodes: list, counts: dict, ocpv: str = "unknown", cnvv: str = "unknown") -> None:
    """Print structured SEVERITY/FINDINGS/RECOMMENDATION/SUMMARY report."""
    if not nodes:
        print("SEVERITY: UNKNOWN")
        print("\nFINDINGS:")
        print("  - No node data available")
        print("\nRECOMMENDATION:")
        print("  - Collect node data: oc get nodes -o json > nodes.json")
        print("\nSUMMARY: No cluster data available.")
        return

    findings = []
    if "ec." in ocpv or "alpha" in ocpv or "beta" in ocpv:
        findings.append(f"OCP {ocpv} is a pre-release version")

    kernels = {n["kernel"] for n in nodes}
    if len(kernels) > 1:
        findings.append("Mixed kernel versions across nodes")

    os_versions = {n["os"] for n in nodes}
    if len(os_versions) > 1:
        findings.append("Mixed OS versions across nodes")

    severity = "WARNING" if findings else "PASS"

    print("=" * 50)
    print(f"  OCP Version    {ocpv}")
    print(f"  CNV Version    {cnvv}")
    print(f"  Total Nodes    {len(nodes)}")
    print(f"  Total VMs      {sum(counts.values())}")
    print("=" * 50)
    print()

    print_table(nodes, counts)
    print()

    print(f"SEVERITY: {severity}")
    print("\nFINDINGS:")
    for f in findings:
        print(f"  - {f}")
    if not findings:
        print("  - No issues detected")

    print("\nRECOMMENDATION:")
    if any("pre-release" in f for f in findings):
        print("  - Upgrade to a stable OCP release for production workloads")
    elif any("Mixed" in f for f in findings):
        print("  - Update all nodes to the same version before investigating performance issues")
    else:
        print("  - Cluster looks healthy")

    workers = [n for n in nodes if n["role"] == "worker"]
    print(f"\nSUMMARY: {len(nodes)} nodes ({len(workers)} workers), "
          f"{sum(counts.values())} VMs running, severity: {severity}")


def _load(path: str) -> dict:
    """Load a JSON file."""
    with open(path) as f:
        return json.load(f)


def main():
    """Parse pre-collected OCP JSON artifacts and print a structured report."""
    import argparse
    parser = argparse.ArgumentParser(description="Analyze pre-collected OCP cluster data")
    parser.add_argument("--nodes",   required=True, help="Path to: oc get nodes -o json")
    parser.add_argument("--version", help="Path to: oc version -o json")
    parser.add_argument("--vmis",    help="Path to: oc get vmi -A -o json")
    parser.add_argument("--cnv",     help="Path to: oc get csv -n openshift-cnv -o json")
    args = parser.parse_args()

    nodes_data = _load(args.nodes)
    nodes = parse_nodes(nodes_data)
    if not nodes:
        print("SEVERITY: UNKNOWN")
        print("\nFINDINGS:\n  - No node data found in provided file")
        print("\nRECOMMENDATION:\n  - Verify: oc get nodes -o json > nodes.json")
        print("\nSUMMARY: No cluster data available.")
        return

    counts = parse_vm_counts(_load(args.vmis)) if args.vmis else {}
    ocpv   = parse_ocp_version(_load(args.version)) if args.version else "unknown"
    cnvv   = parse_cnv_version(_load(args.cnv)) if args.cnv else "unknown"

    analyze(nodes, counts, ocpv, cnvv)

    # ── C1 tuned check ────────────────────────────────────────────────────────
    import subprocess
    r = subprocess.run(
        ["oc", "get", "profile.tuned.openshift.io",
         "-n", "openshift-cluster-node-tuning-operator", "--no-headers"],
        capture_output=True, text=True, timeout=15
    )
    print("\nHost Tuning")
    print("─" * 50)
    if r.returncode != 0:
        print("  ℹ️   Cannot check C1 tuned — oc not available")
    elif any("c1-lowlatency" in line for line in r.stdout.splitlines()):
        print("  ✅  c1-lowlatency applied — CPUs pinned to C1 for low latency")
    else:
        print("  ⚠️   c1-lowlatency NOT applied")
        print("       → Run: oc apply -f skills/ocp-analysis/tuned-c1.yaml")


if __name__ == "__main__":
    main()
