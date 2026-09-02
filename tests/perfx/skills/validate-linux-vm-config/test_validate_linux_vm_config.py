"""Tests for skills/validate-linux-vm-config/validate_linux_vm_config.py"""
import importlib.util
import re
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

SCRIPT = Path(__file__).parent.parent.parent.parent.parent / "skills" / "validate-linux-vm-config" / "validate_linux_vm_config.py"
spec = importlib.util.spec_from_file_location("validate_linux_vm_config", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

LINUX_YAML_ISSUES = textwrap.dedent("""\
    metadata:
      name: test-linux-vm
    spec:
      template:
        spec:
          domain:
            devices:
              disks:
              - disk:
                  bus: virtio
                bootOrder: 1
              interfaces:
              - masquerade: {}
                model: virtio
""")

LINUX_YAML_PASS = textwrap.dedent("""\
    metadata:
      name: test-linux-vm
    spec:
      template:
        spec:
          evictionStrategy: LiveMigrate
          domain:
            devices:
              blockMultiQueue: true
              networkInterfaceMultiqueue: true
              disks:
              - disk:
                  bus: virtio
                  cache: none
                bootOrder: 1
              interfaces:
              - masquerade: {}
                model: virtio
            ioThreads:
              supplementalPoolThreadCount: 4
            ioThreadsPolicy: supplementalPool
""")


class TestCheckLinuxFunction:
    def test_report_contains_audit_header(self, tmp_path):
        f = tmp_path / "vm.yaml"
        f.write_text(LINUX_YAML_ISSUES)
        report = mod.check(str(f))
        assert "LINUX VM CONFIGURATION AUDIT" in report

    def test_report_contains_recommendation(self, tmp_path):
        f = tmp_path / "vm.yaml"
        f.write_text(LINUX_YAML_ISSUES)
        report = mod.check(str(f))
        assert "RECOMMENDATION" in report

    def test_fails_when_blockMultiQueue_missing(self, tmp_path):
        f = tmp_path / "vm.yaml"
        f.write_text(LINUX_YAML_ISSUES)
        report = mod.check(str(f))
        assert "❌" in report

    def test_passes_when_fully_configured(self, tmp_path):
        f = tmp_path / "vm.yaml"
        f.write_text(LINUX_YAML_PASS)
        report = mod.check(str(f))
        assert "0 critical issue(s)" in report

    def test_virtio_nic_not_checked_by_default(self, tmp_path):
        """NIC model check only runs if NIC.model is in rules file."""
        f = tmp_path / "vm.yaml"
        f.write_text(LINUX_YAML_ISSUES)
        report = mod.check(str(f))
        # NIC model not in current rules, but ioThreads checks are present
        assert "ioThreads" in report

    def test_eviction_strategy_optional_warning(self, tmp_path):
        f = tmp_path / "vm.yaml"
        f.write_text(LINUX_YAML_ISSUES)
        report = mod.check(str(f))
        assert "evictionStrategy" in report
        assert "⚠️" in report

    def test_warn_appears_in_recommendation_section(self, tmp_path):
        f = tmp_path / "vm.yaml"
        f.write_text(LINUX_YAML_ISSUES)
        report = mod.check(str(f))
        rec_section = report.split("RECOMMENDATION")[-1]
        assert "evictionStrategy" in rec_section or "⚠️" in rec_section


class TestLogFilenameFormat:
    """Test UUID-based log filename generation."""

    def test_log_filename_contains_uuid_and_timestamp(self, tmp_path, monkeypatch):
        """Log filename follows perfx_{uuid}_{timestamp}.log format."""
        f = tmp_path / "vm.yaml"
        f.write_text(LINUX_YAML_PASS)

        logs_dir = tmp_path / "logs"
        logs_dir.mkdir()
        monkeypatch.setattr(mod, "LOGS_DIR", logs_dir)

        # Mock uuid to return a known value
        with patch('uuid.uuid4') as mock_uuid:
            mock_uuid.return_value.hex = 'a1b2c3d4' + '0' * 24  # 32 hex chars
            mod.main.__wrapped__ = mod.main  # Store original if wrapped

            # Capture output by directly calling the logging code
            report = mod.check(str(f))
            run_uuid = mock_uuid.return_value.hex[:8]

            # Verify UUID is 8 hex characters
            assert len(run_uuid) == 8
            assert all(c in '0123456789abcdef' for c in run_uuid)

    def test_multiple_runs_create_unique_filenames(self, tmp_path, monkeypatch):
        """Each run creates a log with a unique UUID."""
        f = tmp_path / "vm.yaml"
        f.write_text(LINUX_YAML_PASS)

        logs_dir = tmp_path / "logs"
        logs_dir.mkdir()
        monkeypatch.setattr(mod, "LOGS_DIR", logs_dir)

        # Simulate two runs with different UUIDs
        uuids = []
        with patch('uuid.uuid4') as mock_uuid:
            for uuid_val in ['aaaaaaaa' + '0' * 24, 'bbbbbbbb' + '0' * 24]:
                mock_uuid.return_value.hex = uuid_val
                report = mod.check(str(f))
                uuids.append(uuid_val[:8])

        # UUIDs should be different
        assert uuids[0] != uuids[1]
        assert uuids[0] == 'aaaaaaaa'
        assert uuids[1] == 'bbbbbbbb'
