"""Integration tests for perfx/vm_config_tool.py"""
import textwrap
from pathlib import Path

import pytest

import perfx.vm_config_tool as vm_mod
from perfx.vm_config_tool import check_vm_config, validate_linux_vm_config, detect_os, _save_report


# ---------------------------------------------------------------------------
# Minimal Windows YAML with all required fields → should PASS (or low issues)
# ---------------------------------------------------------------------------

WINDOWS_FULL_YAML = textwrap.dedent("""\
    metadata:
      name: win-test-vm
    spec:
      template:
        spec:
          domain:
            features:
              hyperv:
                relaxed: {}
                vapic: {}
                vpindex: {}
                runtime: {}
                reset: {}
                reenlightenment: {}
                tlbflush: {}
                frequencies: {}
                ipi: {}
                synic: {}
                synictimer:
                  direct: {}
                spinlocks:
                  spinlocks: 8191
            devices:
              autoattachMemBalloon: false
              blockMultiQueue: true
              networkInterfaceMultiqueue: true
              disks:
                - name: rootdisk
                  disk:
                    bus: virtio
            clock:
              timer:
                hpet:
                  present: false
                hyperv: {}
                pit:
                  tickPolicy: delay
                rtc:
                  tickPolicy: catchup
            ioThreads:
              supplementalPoolThreadCount: 8
            ioThreadsPolicy: supplementalPool
            machine:
              type: pc-q35-rhel9.8.0
            firmware:
              bootloader:
                efi:
                  secureBoot: false
            cpu:
              sockets: 1
              cores: 1
              threads: 1
            resources:
              requests:
                memory: 8Gi
""")

LINUX_FULL_YAML = textwrap.dedent("""\
    metadata:
      name: linux-test-vm
    spec:
      template:
        spec:
          evictionStrategy: LiveMigrate
          domain:
            devices:
              disks:
                - name: rootdisk
                  disk:
                    bus: virtio
              interfaces:
                - name: default
                  model: virtio
            resources:
              requests:
                cpu: "4"
                memory: 8Gi
              limits:
                cpu: "4"
                memory: 8Gi
            cpu:
              sockets: 1
              dedicatedCpuPlacement: true
            ioThreadsPolicy: shared
            machine:
              type: q35
""")


REQUIRED_KEYS = ("severity", "vm_name", "summary", "table", "rows", "log_file")


# ---------------------------------------------------------------------------
# check_vm_config tests
# ---------------------------------------------------------------------------

class TestCheckVmConfigPass:
    def test_full_yaml_has_low_issues(self, tmp_path, monkeypatch):
        monkeypatch.setattr(vm_mod, "LOGS_DIR", tmp_path / "logs")
        f = tmp_path / "vm.yaml"
        f.write_text(WINDOWS_FULL_YAML)
        result = check_vm_config(str(f))
        assert "error" not in result
        assert result["vm_name"] == "win-test-vm"
        # With all fields present, severity should not be CRITICAL
        assert result["severity"] != "CRITICAL"

    def test_returns_required_keys(self, tmp_path, monkeypatch):
        monkeypatch.setattr(vm_mod, "LOGS_DIR", tmp_path / "logs")
        f = tmp_path / "vm.yaml"
        f.write_text(WINDOWS_FULL_YAML)
        result = check_vm_config(str(f))
        for key in REQUIRED_KEYS:
            assert key in result

    def test_rows_are_list_of_dicts(self, tmp_path, monkeypatch):
        monkeypatch.setattr(vm_mod, "LOGS_DIR", tmp_path / "logs")
        f = tmp_path / "vm.yaml"
        f.write_text(WINDOWS_FULL_YAML)
        result = check_vm_config(str(f))
        assert isinstance(result["rows"], list)
        assert all(isinstance(r, dict) for r in result["rows"])
        assert all("setting" in r and "status" in r for r in result["rows"])


class TestCheckVmConfigCritical:
    def test_missing_all_fields_is_critical(self, tmp_path, monkeypatch):
        monkeypatch.setattr(vm_mod, "LOGS_DIR", tmp_path / "logs")
        yaml_text = textwrap.dedent("""\
            metadata:
              name: bare-vm
            spec:
              template:
                spec:
                  domain: {}
        """)
        f = tmp_path / "bare.yaml"
        f.write_text(yaml_text)
        result = check_vm_config(str(f))
        assert "error" not in result
        assert result["severity"] == "CRITICAL"


class TestCheckVmConfigSpinlocks:
    def test_wrong_spinlocks_reported(self, tmp_path, monkeypatch):
        monkeypatch.setattr(vm_mod, "LOGS_DIR", tmp_path / "logs")
        yaml_text = WINDOWS_FULL_YAML.replace("spinlocks: 8191", "spinlocks: 1000")
        f = tmp_path / "vm.yaml"
        f.write_text(yaml_text)
        result = check_vm_config(str(f))
        assert "error" not in result
        # The table or rows should mention spinlocks
        statuses = " ".join(r["status"] for r in result["rows"])
        assert "spinlocks" in statuses or "spinlocks" in result["table"]


class TestCheckVmConfigSynictimer:
    def test_synictimer_missing_direct_reported(self, tmp_path, monkeypatch):
        monkeypatch.setattr(vm_mod, "LOGS_DIR", tmp_path / "logs")
        # Replace synictimer block with an empty dict (no 'direct' key)
        yaml_text = textwrap.dedent("""\
            metadata:
              name: synic-test
            spec:
              template:
                spec:
                  domain:
                    features:
                      hyperv:
                        relaxed: {}
                        vapic: {}
                        vpindex: {}
                        runtime: {}
                        reset: {}
                        reenlightenment: {}
                        tlbflush: {}
                        frequencies: {}
                        ipi: {}
                        synic: {}
                        synictimer: {}
                        spinlocks:
                          spinlocks: 8191
        """)
        f = tmp_path / "vm.yaml"
        f.write_text(yaml_text)
        result = check_vm_config(str(f))
        assert "error" not in result
        # Row for hyperv enlightenments should show a warning
        hv_row = next((r for r in result["rows"] if "hyperv" in r["setting"]), None)
        assert hv_row is not None
        assert "✅" not in hv_row["status"]


class TestCheckVmConfigBalloon:
    def test_balloon_true_flagged(self, tmp_path, monkeypatch):
        monkeypatch.setattr(vm_mod, "LOGS_DIR", tmp_path / "logs")
        yaml_text = WINDOWS_FULL_YAML.replace(
            "autoattachMemBalloon: false",
            "autoattachMemBalloon: true"
        )
        f = tmp_path / "vm.yaml"
        f.write_text(yaml_text)
        result = check_vm_config(str(f))
        assert "error" not in result
        balloon_row = next(
            (r for r in result["rows"] if "autoattach" in r["setting"].lower()), None
        )
        assert balloon_row is not None
        assert "✅" not in balloon_row["status"]


class TestCheckVmConfigFileNotFound:
    def test_missing_file_returns_error(self, tmp_path):
        result = check_vm_config(str(tmp_path / "nonexistent.yaml"))
        assert "error" in result
        assert "not found" in result["error"].lower() or "File not found" in result["error"]


class TestCheckVmConfigInvalidYaml:
    def test_invalid_yaml_returns_error(self, tmp_path):
        f = tmp_path / "bad.yaml"
        f.write_text("key: [unclosed")
        result = check_vm_config(str(f))
        assert "error" in result


# ---------------------------------------------------------------------------
# validate_linux_vm_config tests
# ---------------------------------------------------------------------------

class TestValidateLinuxVmConfigPass:
    def test_full_yaml_passes_disk_and_network(self, tmp_path, monkeypatch):
        monkeypatch.setattr(vm_mod, "LOGS_DIR", tmp_path / "logs")
        f = tmp_path / "linux.yaml"
        f.write_text(LINUX_FULL_YAML)
        result = validate_linux_vm_config(str(f))
        assert "error" not in result
        assert result["vm_name"] == "linux-test-vm"
        # Disk and network rows should show OK
        ok_statuses = [r for r in result["rows"] if "✅" in r["status"]]
        assert len(ok_statuses) > 0

    def test_returns_required_keys(self, tmp_path, monkeypatch):
        monkeypatch.setattr(vm_mod, "LOGS_DIR", tmp_path / "logs")
        f = tmp_path / "linux.yaml"
        f.write_text(LINUX_FULL_YAML)
        result = validate_linux_vm_config(str(f))
        for key in REQUIRED_KEYS:
            assert key in result


class TestValidateLinuxVmConfigWrongDiskBus:
    def test_wrong_disk_bus_flagged(self, tmp_path, monkeypatch):
        monkeypatch.setattr(vm_mod, "LOGS_DIR", tmp_path / "logs")
        yaml_text = LINUX_FULL_YAML.replace("bus: virtio", "bus: sata")
        f = tmp_path / "linux.yaml"
        f.write_text(yaml_text)
        result = validate_linux_vm_config(str(f))
        assert "error" not in result
        disk_rows = [r for r in result["rows"] if "disk" in r["setting"]]
        assert disk_rows, "Expected at least one disk row"
        fail_statuses = [r for r in disk_rows if "❌" in r["status"]]
        assert fail_statuses


class TestValidateLinuxVmConfigFileNotFound:
    def test_missing_file_returns_error(self, tmp_path):
        result = validate_linux_vm_config(str(tmp_path / "nope.yaml"))
        assert "error" in result


# ---------------------------------------------------------------------------
# Additional Windows coverage tests (clock issues, machine type variants, firmware)
# ---------------------------------------------------------------------------

class TestCheckVmConfigClockIssues:
    def test_partial_clock_timer_reported(self, tmp_path, monkeypatch):
        """Timer block present but some timers missing → covers lines 131, 138-141."""
        monkeypatch.setattr(vm_mod, "LOGS_DIR", tmp_path / "logs")
        yaml_text = textwrap.dedent("""\
            metadata:
              name: clock-test
            spec:
              template:
                spec:
                  domain:
                    clock:
                      timer:
                        hpet:
                          present: false
        """)
        f = tmp_path / "vm.yaml"
        f.write_text(yaml_text)
        result = check_vm_config(str(f))
        assert "error" not in result
        clock_row = next((r for r in result["rows"] if "clock" in r["setting"]), None)
        assert clock_row is not None
        assert "✅" not in clock_row["status"]

    def test_wrong_clock_tick_policy_reported(self, tmp_path, monkeypatch):
        """Timer present but wrong tickPolicy → covers line 136."""
        monkeypatch.setattr(vm_mod, "LOGS_DIR", tmp_path / "logs")
        yaml_text = textwrap.dedent("""\
            metadata:
              name: clock-test2
            spec:
              template:
                spec:
                  domain:
                    clock:
                      timer:
                        hpet:
                          present: false
                        hyperv: {}
                        pit:
                          tickPolicy: merge
                        rtc:
                          tickPolicy: catchup
        """)
        f = tmp_path / "vm.yaml"
        f.write_text(yaml_text)
        result = check_vm_config(str(f))
        assert "error" not in result
        clock_row = next((r for r in result["rows"] if "clock" in r["setting"]), None)
        assert clock_row is not None
        assert "✅" not in clock_row["status"]


class TestCheckVmConfigMachineType:
    def test_q35_without_rhel9_prefix(self, tmp_path, monkeypatch):
        """q35 machine type without rhel9.X suffix → covers line 189."""
        monkeypatch.setattr(vm_mod, "LOGS_DIR", tmp_path / "logs")
        yaml_text = textwrap.dedent("""\
            metadata:
              name: mtype-test
            spec:
              template:
                spec:
                  domain:
                    machine:
                      type: pc-q35
        """)
        f = tmp_path / "vm.yaml"
        f.write_text(yaml_text)
        result = check_vm_config(str(f))
        assert "error" not in result
        mtype_row = next((r for r in result["rows"] if "machine" in r["setting"]), None)
        assert mtype_row is not None

    def test_old_rhel9_machine_type(self, tmp_path, monkeypatch):
        """q35 machine with old rhel9.x (not 8 or 9) → covers lines 186-188."""
        monkeypatch.setattr(vm_mod, "LOGS_DIR", tmp_path / "logs")
        yaml_text = textwrap.dedent("""\
            metadata:
              name: mtype-old
            spec:
              template:
                spec:
                  domain:
                    machine:
                      type: pc-q35-rhel9.2.0
        """)
        f = tmp_path / "vm.yaml"
        f.write_text(yaml_text)
        result = check_vm_config(str(f))
        assert "error" not in result
        mtype_row = next((r for r in result["rows"] if "machine" in r["setting"]), None)
        assert mtype_row is not None
        assert "OLD" in mtype_row["status"] or "⚠️" in mtype_row["status"]


class TestCheckVmConfigBiosFirmware:
    def test_bios_firmware_flagged(self, tmp_path, monkeypatch):
        """bios bootloader instead of efi → covers lines 200-201."""
        monkeypatch.setattr(vm_mod, "LOGS_DIR", tmp_path / "logs")
        yaml_text = textwrap.dedent("""\
            metadata:
              name: bios-test
            spec:
              template:
                spec:
                  domain:
                    firmware:
                      bootloader:
                        bios: {}
        """)
        f = tmp_path / "vm.yaml"
        f.write_text(yaml_text)
        result = check_vm_config(str(f))
        assert "error" not in result
        fw_row = next((r for r in result["rows"] if "firmware" in r["setting"]), None)
        assert fw_row is not None
        assert "BIOS" in fw_row["status"] or "⚠️" in fw_row["status"]


# ---------------------------------------------------------------------------
# Additional Linux coverage tests
# ---------------------------------------------------------------------------

class TestValidateLinuxVmConfigInvalidYaml:
    def test_invalid_yaml_returns_error(self, tmp_path):
        """Invalid YAML → covers lines 253-254."""
        f = tmp_path / "bad.yaml"
        f.write_text("key: [unclosed")
        result = validate_linux_vm_config(str(f))
        assert "error" in result


class TestValidateLinuxVmConfigDiskNoBus:
    def test_disk_without_bus_skipped(self, tmp_path, monkeypatch):
        """Disk entry with no bus field → covers line 278 (continue)."""
        monkeypatch.setattr(vm_mod, "LOGS_DIR", tmp_path / "logs")
        yaml_text = textwrap.dedent("""\
            metadata:
              name: nobusvm
            spec:
              template:
                spec:
                  domain:
                    devices:
                      disks:
                        - name: rootdisk
                          disk: {}
        """)
        f = tmp_path / "linux.yaml"
        f.write_text(yaml_text)
        result = validate_linux_vm_config(str(f))
        assert "error" not in result
        # No disk row should be added (skipped)
        disk_rows = [r for r in result["rows"] if "disk" in r["setting"]]
        assert len(disk_rows) == 0


class TestValidateLinuxVmConfigMissingResources:
    def test_missing_cpu_requests_flagged(self, tmp_path, monkeypatch):
        """No cpu/memory requests → covers lines 293, 302."""
        monkeypatch.setattr(vm_mod, "LOGS_DIR", tmp_path / "logs")
        yaml_text = textwrap.dedent("""\
            metadata:
              name: nores-vm
            spec:
              template:
                spec:
                  domain:
                    devices:
                      interfaces:
                        - name: eth0
                          model: e1000
        """)
        f = tmp_path / "linux.yaml"
        f.write_text(yaml_text)
        result = validate_linux_vm_config(str(f))
        assert "error" not in result
        req_rows = [r for r in result["rows"] if "requests" in r["setting"]]
        assert req_rows
        fail_rows = [r for r in req_rows if "❌" in r["status"]]
        assert fail_rows


# ---------------------------------------------------------------------------
# _save_report tests
# ---------------------------------------------------------------------------

class TestCheckVmConfigNicModel:
    def test_e1000_nic_flagged(self, tmp_path, monkeypatch):
        monkeypatch.setattr(vm_mod, "LOGS_DIR", tmp_path / "logs")
        yaml_text = textwrap.dedent("""\
            metadata:
              name: linux-e1000
            spec:
              template:
                spec:
                  domain:
                    devices:
                      interfaces:
                        - name: eth0
                          model: e1000e
        """)
        f = tmp_path / "vm.yaml"
        f.write_text(yaml_text)
        result = validate_linux_vm_config(str(f))
        nic_rows = [r for r in result["rows"] if "model" in r["setting"]]
        assert nic_rows
        assert any("❌" in r["status"] for r in nic_rows)

    def test_virtio_nic_passes(self, tmp_path, monkeypatch):
        monkeypatch.setattr(vm_mod, "LOGS_DIR", tmp_path / "logs")
        yaml_text = textwrap.dedent("""\
            metadata:
              name: linux-virtio
            spec:
              template:
                spec:
                  domain:
                    devices:
                      interfaces:
                        - name: eth0
                          model: virtio
        """)
        f = tmp_path / "vm.yaml"
        f.write_text(yaml_text)
        result = validate_linux_vm_config(str(f))
        nic_rows = [r for r in result["rows"] if "model" in r["setting"]]
        assert nic_rows
        assert all("✅" in r["status"] for r in nic_rows)


class TestDetectOs:
    def test_detects_windows_via_hyperv(self, tmp_path):
        yaml_text = textwrap.dedent("""\
            metadata:
              name: win-vm
            spec:
              template:
                spec:
                  domain:
                    features:
                      hyperv:
                        relaxed: {}
        """)
        f = tmp_path / "vm.yaml"
        f.write_text(yaml_text)
        assert detect_os(str(f)) == "windows"

    def test_detects_windows_via_preference(self, tmp_path):
        yaml_text = textwrap.dedent("""\
            metadata:
              name: win-vm
            spec:
              preference:
                name: windows.2k25.virtio
              template:
                spec:
                  domain: {}
        """)
        f = tmp_path / "vm.yaml"
        f.write_text(yaml_text)
        assert detect_os(str(f)) == "windows"

    def test_detects_windows_when_ambiguous(self, tmp_path):
        yaml_text = textwrap.dedent("""\
            metadata:
              name: unknown-vm
            spec:
              template:
                spec:
                  domain:
                    devices:
                      disks: []
        """)
        f = tmp_path / "vm.yaml"
        f.write_text(yaml_text)
        # no hyperv, no preference, no OS label → default to windows (full check)
        assert detect_os(str(f)) == "windows"

    def test_detects_linux_via_os_label(self, tmp_path):
        yaml_text = textwrap.dedent("""\
            metadata:
              name: linux-vm
            spec:
              template:
                metadata:
                  annotations:
                    vm.kubevirt.io/os: rhel9
                spec:
                  domain:
                    devices:
                      disks: []
        """)
        f = tmp_path / "vm.yaml"
        f.write_text(yaml_text)
        assert detect_os(str(f)) == "linux"

    def test_windows_template_detected(self):
        assert detect_os("rules/windows-vm-example.yaml") == "windows"

    def test_linux_template_detected(self):
        assert detect_os("rules/linux-vm-example.yaml") == "linux"


class TestRunVmConfigCheck:
    """Integration tests for _run_vm_config_check routing."""

    WINDOWS_YAML = textwrap.dedent("""\
        metadata:
          name: test-win-vm
        spec:
          template:
            spec:
              domain:
                features:
                  hyperv:
                    ipi: {}
                devices:
                  disks: []
    """)

    LINUX_YAML = textwrap.dedent("""\
        metadata:
          name: test-linux-vm
        spec:
          template:
            metadata:
              annotations:
                vm.kubevirt.io/os: rhel9
            spec:
              domain:
                devices:
                  disks: []
    """)

    def test_windows_yaml_runs_windows_checker(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PERFX_LOGS_DIR", str(tmp_path))
        f = tmp_path / "win.yaml"
        f.write_text(self.WINDOWS_YAML)
        result = vm_mod.check_vm_config_from_path(str(f), os_type="windows")
        assert result["used_os"] == "windows"
        assert "WINDOWS" in result["table"] or result["severity"] in ("CRITICAL", "PASS")

    def test_linux_yaml_runs_linux_checker(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PERFX_LOGS_DIR", str(tmp_path))
        f = tmp_path / "linux.yaml"
        f.write_text(self.LINUX_YAML)
        result = vm_mod.check_vm_config_from_path(str(f), os_type="linux")
        assert result["used_os"] == "linux"
        assert "LINUX" in result["table"] or result["severity"] in ("CRITICAL", "PASS")

    def test_auto_detects_windows(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PERFX_LOGS_DIR", str(tmp_path))
        f = tmp_path / "win.yaml"
        f.write_text(self.WINDOWS_YAML)
        result = vm_mod.check_vm_config_from_path(str(f))
        assert result["detected_os"] == "windows"

    def test_auto_detects_linux(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PERFX_LOGS_DIR", str(tmp_path))
        f = tmp_path / "linux.yaml"
        f.write_text(self.LINUX_YAML)
        result = vm_mod.check_vm_config_from_path(str(f))
        assert result["detected_os"] == "linux"


class TestSaveReport:
    def test_creates_log_file_with_expected_content(self, tmp_path, monkeypatch):
        monkeypatch.setattr(vm_mod, "LOGS_DIR", tmp_path)
        rows = [
            {"setting": "hyperv", "customer": "all", "recommended": "all", "status": "✅ OK"},
            {"setting": "clock", "customer": "set", "recommended": "set", "status": "✅ OK"},
        ]
        summary = "PASS: 2 passed, 0 issues of 2 checks"
        log_path = _save_report("myvm", "windows", rows, summary)
        assert log_path.startswith(str(tmp_path))
        content = Path(log_path).read_text()
        assert "myvm" in content
        assert "WINDOWS" in content
        assert "PASS" in content
        assert "hyperv" in content

    def test_filename_follows_uuid_timestamp_format(self, tmp_path, monkeypatch):
        """Log filename follows perfx_{uuid}_{timestamp}.log format."""
        import re
        monkeypatch.setattr(vm_mod, "LOGS_DIR", tmp_path)
        rows = [{"setting": "test", "customer": "x", "recommended": "y", "status": "✅"}]
        log_path = _save_report("test-vm", "linux", rows, "OK")
        filename = Path(log_path).name
        # Format: perfx_{8-hex-chars}_{YYYY-MM-DD_HH-MM-SS}.log
        pattern = r'^perfx_[0-9a-f]{8}_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}\.log$'
        assert re.match(pattern, filename), f"Filename {filename} doesn't match expected format"

    def test_multiple_saves_create_unique_filenames(self, tmp_path, monkeypatch):
        """Each save creates a unique log file."""
        monkeypatch.setattr(vm_mod, "LOGS_DIR", tmp_path)
        rows = [{"setting": "test", "customer": "x", "recommended": "y", "status": "✅"}]
        log1 = _save_report("vm1", "linux", rows, "OK")
        log2 = _save_report("vm2", "linux", rows, "OK")
        # Different UUIDs ensure different filenames
        assert log1 != log2
        assert Path(log1).exists()
        assert Path(log2).exists()
