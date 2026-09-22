# /validate-windows-vm-config

Validate Windows VM YAML configuration against validation rules.

## Rules

- `windows-vm-validation.yaml` — defines all required Windows VM settings to validate (in this skill directory)
- `rules/windows-vm-example.yaml` — reference Windows VM configuration

## Methodology

- Read `methodology/vm-tuning-guide.md` for background on Windows VM performance tuning (hyperv enlightenments, ioThreads, C-states)

## Steps

1. Run the validation:
   ```bash
   python3 skills/validate-windows-vm-config/validate_windows_vm_config.py <vm.yaml>
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

- For Linux VMs use `skills/validate-linux-vm-config/`
- Corrected YAML is valid YAML-only — apply with `oc apply -f <yaml_file>`
- **MSSQL balloon consideration**: For VMs running SQL Server (MSSQL), `autoattachMemBalloon` must be `false`. SQL Server manages its own memory pool aggressively via its buffer pool — an in-memory cache of data and index pages. When the virtio-balloon driver reclaims guest memory, the guest OS evicts pages from SQL Server's buffer pool, forcing expensive disk re-reads and degrading query performance. This also applies to other memory-intensive workloads that pre-allocate large regions (Java heaps, in-memory databases). The validation script flags this as a critical failure.
