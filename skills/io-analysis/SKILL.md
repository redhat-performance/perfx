# /io-analysis

Investigate I/O performance degradation in VMs.

## Methodology

- Read `methodology/io-degradation.md` for systematic I/O investigation workflow

## Key Principle

**I/O degradation is often NOT a storage problem** — check CPU scheduling, C-states, interrupt handling, and VM config first before blaming storage.

## Investigation Workflow

**Check in this order:**

- Collect virsh domstats baseline
- Collect vmexit stats from KVM host
- Check host C-state configuration
- Check `intel_c1_demotion` (Intel CPUs)
- Check VM config: ioThreadsPolicy, blockMultiQueue, cache mode, memory balloon
- Correlate patterns across domstats + vmexits
- Only after ruling out config/C-state issues: check storage backend

## Common Root Causes

### C-state-related I/O degradation

**Symptoms:**
- I/O latency is inconsistent (varies over time)
- Storage backend metrics look fine, but VM sees high latency
- Problem improves when host CPU load increases

**Diagnosis:**
- Deep C-states (C3/C6) delay interrupt handling (80-200μs wake latency)
- CPUs must wake from deep sleep to handle I/O completion interrupts

**Fix:**
- Enable `intel_c1_demotion`: `echo 1 > /sys/devices/system/cpu/cpuidle/intel_c1_demotion`
- Rerun tests — if performance improves, C-states were the issue
- For triage: can force C1 pinning temporarily (NOT for production)

See `methodology/vm-tuning-guide.md` Step 5 for detailed C-state troubleshooting.

---

### Forced fsync (1:1 flush:write ratio)

**Symptom**: `block.*.wr_operations` ≈ `block.*.fl_operations` in domstats

**Root cause**: Application or filesystem forcing sync after every write

**Fix**: Tune application fsync frequency or filesystem mount options

---

### Missing ioThreads configuration

**Symptom**: Single-threaded I/O processing, low throughput

**Fix**: Add `ioThreadsPolicy: supplementalPool` to VM YAML (OCP 4.19+)

See `methodology/vm-tuning-guide.md` Step 2.

---

### Memory pressure (EPT_VIOLATION exits)

**Symptom**: High EPT_VIOLATION count in vmexit stats during I/O

**Fix**: Disable memory balloon (`autoattachMemBalloon: false`), enable hugepages

See `methodology/vm-tuning-guide.md` Steps 6, 12.

---

## Data Sources

**virsh domstats:**
```bash
virsh domstats <vm_name>
```

**vmexit stats:**
```bash
cat /sys/kernel/debug/kvm/*/vcpu*/vmexit
```

**C-state check:**
```bash
cat /sys/devices/system/cpu/cpu0/cpuidle/state*/name
cat /sys/devices/system/cpu/cpuidle/intel_c1_demotion
```

**VM config:**
```bash
oc get vm <vm_name> -o yaml
```

---

## Steps

**Automated analysis script**: Not yet implemented — manual workflow:

- Collect domstats, vmexit stats, C-state info
- Check for forced fsync (1:1 flush:write ratio)
- Check for C-state issues (deep states enabled, intel_c1_demotion disabled)
- Check VM config (ioThreads, blockMultiQueue, cache mode, balloon)
- Correlate patterns using methodology/io-degradation.md correlation matrix
- Provide diagnosis and fix recommendations

## Integration

- **Vmexit analysis**: `methodology/vmexit-analysis.md` — HLT, EPT_VIOLATION, EXTERNAL_INTERRUPT
- **VM tuning**: `methodology/vm-tuning-guide.md` — Steps 2, 5, 6, 12, 16, 17
- **VM config validation**: `/validate-windows-vm-config`, `/validate-linux-vm-config`
