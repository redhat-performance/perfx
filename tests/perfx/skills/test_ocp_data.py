"""Tests for skills/ocp-analysis/analyze_ocp.py — integration tests using local JSON fixtures."""
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent.parent.parent / "skills" / "ocp-analysis" / "analyze_ocp.py"
spec = importlib.util.spec_from_file_location("analyze_ocp", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

# ── JSON fixtures (no mocks — local data only) ────────────────────────────────

NODES_DATA = {
    "items": [
        {
            "metadata": {
                "name": "worker-0",
                "labels": {}
            },
            "status": {
                "capacity":    {"cpu": "64", "memory": "524288000Ki"},
                "allocatable": {"cpu": "63", "memory": "520192000Ki"},
                "nodeInfo": {
                    "kernelVersion": "5.14.0-427.el9.x86_64",
                    "osImage": "Red Hat Enterprise Linux CoreOS 9.4"
                }
            }
        },
        {
            "metadata": {
                "name": "master-0",
                "labels": {"node-role.kubernetes.io/control-plane": ""}
            },
            "status": {
                "capacity":    {"cpu": "16", "memory": "65536Mi"},
                "allocatable": {"cpu": "15", "memory": "63488Mi"},
                "nodeInfo": {
                    "kernelVersion": "5.14.0-427.el9.x86_64",
                    "osImage": "Red Hat Enterprise Linux CoreOS 9.4"
                }
            }
        }
    ]
}

VMIS_DATA = {
    "items": [
        {"status": {"nodeName": "worker-0"}},
        {"status": {"nodeName": "worker-0"}},
        {"status": {"nodeName": "master-0"}},
    ]
}

VERSION_DATA = {"openshiftVersion": "4.18.3"}
CSV_DATA = {
    "items": [
        {"metadata": {"name": "kubevirt-hyperconverged-operator.v4.18.1"},
         "spec": {"version": "4.18.1"}}
    ]
}


class TestToGib:
    def test_ki_large(self):
        assert mod._to_gib("524288000Ki") == "500Gi"

    def test_ki_nonzero_preserves_value(self):
        result = mod._to_gib("524288Ki")
        assert result != "0Gi"
        assert "Gi" in result

    def test_gi(self):
        assert mod._to_gib("256Gi") == "256Gi"

    def test_mi(self):
        assert mod._to_gib("2048Mi") == "2Gi"

    def test_mi_fractional(self):
        assert mod._to_gib("1536Mi") == "1.5Gi"

    def test_unknown(self):
        assert mod._to_gib("unknown") == "unknown"


class TestParseNodes:
    def test_parses_worker_and_control_plane(self):
        nodes = mod.parse_nodes(NODES_DATA)
        assert len(nodes) == 2
        worker = next(n for n in nodes if n["name"] == "worker-0")
        master = next(n for n in nodes if n["name"] == "master-0")
        assert worker["role"] == "worker"
        assert master["role"] == "control-plane"
        assert worker["cpu"] == "64"

    def test_memory_not_zero_for_large_ki(self):
        nodes = mod.parse_nodes(NODES_DATA)
        worker = next(n for n in nodes if n["name"] == "worker-0")
        assert worker["memory"] != "0Gi"
        assert "Gi" in worker["memory"]

    def test_empty_returns_empty(self):
        assert mod.parse_nodes({}) == []


class TestParseVmCounts:
    def test_counts_vms_per_node(self):
        counts = mod.parse_vm_counts(VMIS_DATA)
        assert counts["worker-0"] == 2
        assert counts["master-0"] == 1

    def test_empty_returns_empty(self):
        assert mod.parse_vm_counts({}) == {}


class TestParseVersions:
    def test_ocp_version(self):
        assert mod.parse_ocp_version(VERSION_DATA) == "4.18.3"

    def test_ocp_version_unknown(self):
        assert mod.parse_ocp_version({}) == "unknown"

    def test_cnv_version(self):
        assert mod.parse_cnv_version(CSV_DATA) == "4.18.1"

    def test_cnv_not_installed(self):
        assert mod.parse_cnv_version({"items": []}) == "not installed"
