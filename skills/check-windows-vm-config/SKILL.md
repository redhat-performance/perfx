# /check-windows-vm-config

Check Windows VM YAML configuration against `rules/windows-vm-checks.yaml`.

## Rules

- `rules/windows-vm-checks.yaml` — defines all required Windows VM settings to validate
- `rules/windows-vm-example.yaml` — reference Windows VM configuration

## Methodology

- Read `methodology/vm-tuning-guide.md` for background on Windows VM performance tuning (hyperv enlightenments, ioThreads, C-states)

## Steps

1. Run the check:
   ```bash
   python3 skills/check-windows-vm-config/check_windows_vm_config.py <vm.yaml>
   ```

2. Report findings to the user — include table, recommendations, and guest-side steps

## Output Sections

- Audit table: per-setting PASS/FAIL/WARN (sorted: ❌ first, ⚠️ second, ✅ last)
- SEVERITY: CRITICAL / WARNING / OK derived from fails and warns
- RECOMMENDATION → FINDINGS: all critical and warning issues listed
- GUEST-SIDE STEPS: bcdedit, VBS, C1 tuned
- CORRECTED VM YAML: auto-generated fix (only when critical failures exist)
- SUMMARY: X/N checks passed count

## Notes

- For Linux VMs use `skills/check-linux-vm-config/`
- Corrected YAML is valid YAML-only — apply with `oc apply -f <yaml_file>`
