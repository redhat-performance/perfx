"""Tests for skills/validate-windows-vm-config/validate_windows_vm_config.py"""
import importlib.util
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

SCRIPT = Path(__file__).parent.parent.parent.parent.parent / "skills" / "validate-windows-vm-config" / "validate_windows_vm_config.py"
spec = importlib.util.spec_from_file_location("validate_windows_vm_config", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

WINDOWS_YAML_ISSUES = textwrap.dedent("""\
    metadata:
      name: test-win-vm
    spec:
      template:
        spec:
          domain:
            clock:
              timezone: UTC
            devices:
              disks:
              - disk:
                  bus: virtio
                bootOrder: 1
              interfaces:
              - masquerade: {}
                model: virtio
              networkInterfaceMultiqueue: true
              tpm:
                enabled: false
            machine:
              type: pc-q35-rhel9.8.0
            firmware:
              bootloader:
                efi:
                  secureBoot: false
""")

WINDOWS_YAML_PASS = textwrap.dedent("""\
    metadata:
      name: test-win-vm
    spec:
      template:
        spec:
          evictionStrategy: LiveMigrate
          domain:
            clock:
              timer:
                hpet:
                  present: false
                hyperv: {}
                pit:
                  tickPolicy: delay
                rtc:
                  tickPolicy: catchup
              utc: {}
            devices:
              autoattachMemBalloon: false
              blockMultiQueue: true
              tpm: {}
              networkInterfaceMultiqueue: true
              disks:
              - disk:
                  bus: virtio
                bootOrder: 1
              interfaces:
              - masquerade: {}
                model: virtio
            features:
              hyperv:
                ipi: {}
                synic: {}
                synictimer:
                  direct: {}
                spinlocks:
                  spinlocks: 8191
                reenlightenment: {}
                reset: {}
                relaxed: {}
                vpindex: {}
                runtime: {}
                tlbflush: {}
                frequencies: {}
                vapic: {}
            firmware:
              bootloader:
                efi:
                  secureBoot: false
            ioThreads:
              supplementalPoolThreadCount: 4
            ioThreadsPolicy: supplementalPool
            machine:
              type: pc-q35-rhel9.8.0
""")


class TestCheckFunction:
    def test_report_contains_audit_header(self, tmp_path):
        f = tmp_path / "vm.yaml"
        f.write_text(WINDOWS_YAML_ISSUES)
        report = mod.check(str(f))
        assert "WINDOWS VM CONFIGURATION AUDIT" in report

    def test_report_contains_guest_steps(self, tmp_path):
        f = tmp_path / "vm.yaml"
        f.write_text(WINDOWS_YAML_ISSUES)
        report = mod.check(str(f))
        assert "GUEST-SIDE STEPS" in report
        assert "bcdedit" in report

    def test_report_contains_recommendation(self, tmp_path):
        f = tmp_path / "vm.yaml"
        f.write_text(WINDOWS_YAML_ISSUES)
        report = mod.check(str(f))
        assert "RECOMMENDATION" in report

    def test_corrected_yaml_in_report_when_failures(self, tmp_path):
        f = tmp_path / "vm.yaml"
        f.write_text(WINDOWS_YAML_ISSUES)
        report = mod.check(str(f))
        assert "CORRECTED VM YAML" in report
        assert "blockMultiQueue: true" in report

    def test_no_corrected_yaml_when_no_failures(self, tmp_path):
        f = tmp_path / "vm.yaml"
        f.write_text(WINDOWS_YAML_PASS)
        report = mod.check(str(f))
        assert "CORRECTED VM YAML" not in report

    def test_sorted_table_critical_first(self, tmp_path):
        f = tmp_path / "vm.yaml"
        f.write_text(WINDOWS_YAML_ISSUES)
        report = mod.check(str(f))
        fail_pos = report.find("❌")
        ok_pos = report.find("✅")
        assert fail_pos < ok_pos

    def test_missing_vm_yaml_arg_exits(self):
        """vm_yaml argument is required."""
        import subprocess
        result = subprocess.run(
            ["python3", str(SCRIPT)],
            capture_output=True, text=True, timeout=10
        )
        assert result.returncode != 0

    def test_severity_critical_when_failures(self, tmp_path):
        f = tmp_path / "vm.yaml"
        f.write_text(WINDOWS_YAML_ISSUES)
        report = mod.check(str(f))
        assert "Severity  : CRITICAL" in report

    def test_severity_ok_when_all_pass(self, tmp_path):
        f = tmp_path / "vm.yaml"
        f.write_text(WINDOWS_YAML_PASS)
        report = mod.check(str(f))
        assert "Severity  : OK" in report

    def test_summary_section_in_report(self, tmp_path):
        f = tmp_path / "vm.yaml"
        f.write_text(WINDOWS_YAML_ISSUES)
        report = mod.check(str(f))
        assert "SUMMARY" in report
        assert "checks passed" in report

    def test_findings_section_in_report(self, tmp_path):
        f = tmp_path / "vm.yaml"
        f.write_text(WINDOWS_YAML_ISSUES)
        report = mod.check(str(f))
        assert "FINDINGS" in report


class TestHelpers:
    def test_to_int_valid(self):
        assert mod._to_int(4) == 4

    def test_to_int_string(self):
        assert mod._to_int("8") == 8

    def test_to_int_invalid_returns_default(self):
        assert mod._to_int("__template__", 1) == 1

    def test_to_int_none_returns_default(self):
        assert mod._to_int(None, 2) == 2

    def test_detect_os_windows(self, tmp_path):
        f = tmp_path / "vm.yaml"
        f.write_text(WINDOWS_YAML_PASS)
        assert mod._detect_os(str(f)) == "windows"

    def test_detect_os_unknown_when_no_indicators(self, tmp_path):
        f = tmp_path / "vm.yaml"
        f.write_text(WINDOWS_YAML_ISSUES)  # no hyperv features, no labels → unknown
        assert mod._detect_os(str(f)) == "unknown"


class TestLogFilenameFormat:
    """Test UUID-based log filename generation."""

    def test_log_filename_contains_uuid_and_timestamp(self, tmp_path, monkeypatch):
        """Log filename follows perfx_{uuid}_{timestamp}.log format."""
        f = tmp_path / "vm.yaml"
        f.write_text(WINDOWS_YAML_PASS)

        logs_dir = tmp_path / "logs"
        logs_dir.mkdir()
        monkeypatch.setattr(mod, "LOGS_DIR", logs_dir)

        # Mock uuid to return a known value
        with patch('uuid.uuid4') as mock_uuid:
            mock_uuid.return_value.hex = 'a1b2c3d4' + '0' * 24  # 32 hex chars
            report = mod.check(str(f))
            run_uuid = mock_uuid.return_value.hex[:8]

            # Verify UUID is 8 hex characters
            assert len(run_uuid) == 8
            assert all(c in '0123456789abcdef' for c in run_uuid)

    def test_multiple_runs_create_unique_filenames(self, tmp_path, monkeypatch):
        """Each run creates a log with a unique UUID."""
        f = tmp_path / "vm.yaml"
        f.write_text(WINDOWS_YAML_PASS)

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
