# /validate-linux-vm-config

Validate Linux VM YAML configuration against validation rules.

## Steps

1. Run the validation:
   ```bash
   python3 skills/validate-linux-vm-config/validate_linux_vm_config.py <vm.yaml>
   ```

2. Report findings to the user

## Rules

- `linux-vm-validation.yaml` — defines all required settings (in this skill directory)

## Output Sections

- SEVERITY: based on critical issue count
- Table: per-setting PASS/FAIL/WARN
- RECOMMENDATION: list of issues with details
- SUMMARY: one-line verdict
