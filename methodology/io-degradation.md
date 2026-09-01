# I/O Degradation Investigation Guide

I/O performance degradation can have multiple root causes. This guide covers systematic investigation steps.

## Key Principle

**I/O degradation is often NOT a storage problem** — the issue is frequently CPU scheduling, interrupt handling, or virtualization overhead masquerading as I/O issues.

---

## Investigation Workflow

### Check virsh domstats for I/O patterns

Collect baseline metrics:
```bash
virsh domstats <vm_name>
```

**Key metrics to examine:**

| Metric | What to look for | Diagnosis |
|---|---|---|
| `block.*.wr_operations` vs `block.*.fl_operations` | 1:1 ratio (every write = flush) | Forced fsync — guest or application issue |
| `block.*.wr_times` | High values | Write latency — check storage backend |
| `block.*.rd_times` | High values | Read latency — check storage backend |
| `block.*.wr_bytes` / `wr_operations` | Very small (< 4KB) | Small I/O pattern — inefficient |
| `cpu.time` vs `cpu.user` | Low user time % | CPU waiting, not computing — check HLT vmexits |

---

### Check vmexit stats for I/O-related exits

Collect vmexit data from KVM host:
```bash
cat /sys/kernel/debug/kvm/*/vcpu*/vmexit > vmexit_stats.txt
```

**I/O-related exit patterns:**

| Exit Type | Impact on I/O | Action |
|---|---|---|
| **HLT dominates time %** | CPU idle while waiting for I/O — normal for I/O-bound workloads | If workload should be CPU-bound, investigate why guest is waiting |
| **EPT_VIOLATION high** | Page faults during I/O buffer access — memory pressure | Disable memory balloon, check host memory |
| **EXTERNAL_INTERRUPT high** | Many interrupts from I/O devices | Check for interrupt storms, verify IRQ affinity |

See `methodology/vmexit-analysis.md` for detailed vmexit interpretation.

---

### Check host C-state configuration

**Critical**: Deep C-states delay interrupt handling, causing I/O latency spikes.

**Symptoms of C-state-related I/O degradation:**
- I/O latency is inconsistent (varies over time)
- Storage backend metrics look fine, but VM sees high latency
- Problem improves when host CPU load increases (keeps CPUs awake)

**Investigation steps:**

**Check current C-states:**
```bash
# On KVM host
cat /sys/devices/system/cpu/cpu0/cpuidle/state*/name
cat /sys/devices/system/cpu/cpu0/cpuidle/state*/latency

# Expected for latency-sensitive workloads: only POLL and C1
```

**Check intel_c1_demotion (Intel CPUs only):**
```bash
cat /sys/devices/system/cpu/cpuidle/intel_c1_demotion
# Expected: 1 (enabled)
```

**Troubleshooting C-state-related I/O degradation:**

**Step 1: Enable intel_c1_demotion** (try this first)
```bash
echo 1 > /sys/devices/system/cpu/cpuidle/intel_c1_demotion
```
- Rerun I/O tests
- If performance improves → C-states were causing the degradation

**Step 2: Force C1 pinning** (triage ONLY, not for production)
```bash
# Dynamically disable deep C-states
for cpu in /sys/devices/system/cpu/cpu*/cpuidle/state{2,3}; do
  echo 1 > $cpu/disable
done
```
- Rerun I/O tests
- If performance improves → confirms C-states are the root cause
- Investigate underlying issue (kernel patch, BIOS settings, etc.)

**Production fix**: Use intel_c1_demotion, NOT C1 pinning (lower power consumption).

See `methodology/vm-tuning-guide.md` Step 5 for detailed C-state tuning.

---

### Check VM configuration

**Common VM config issues that cause I/O degradation:**

**ioThreads not configured:**
```bash
# Check if ioThreadsPolicy is set in VM YAML
oc get vm <vm_name> -o yaml | grep -A2 ioThreadsPolicy
```

**Expected** (OCP 4.19+):
```yaml
ioThreadsPolicy: supplementalPool
ioThreads:
  supplementalPoolThreadCount: 4  # ~vCPUs/4 to vCPUs/6
```

**Missing**: Add ioThreadsPolicy (see `methodology/vm-tuning-guide.md` Step 2).

**blockMultiQueue disabled:**
```bash
oc get vm <vm_name> -o yaml | grep blockMultiQueue
```

**Expected**: `blockMultiQueue: true`

**Missing**: Enable it (see `methodology/vm-tuning-guide.md` Step 2 for Windows, Step 16 for Linux).

**Disk cache mode issues (Linux VMs):**
```bash
oc get vm <vm_name> -o yaml | grep -A2 "bus: virtio"
```

**Expected for Linux**:
```yaml
disk:
  bus: virtio
  cache: none  # Critical for data integrity
```

**Missing**: Set `cache: none` (see `methodology/vm-tuning-guide.md` Step 17).

**Memory balloon enabled:**
```bash
oc get vm <vm_name> -o yaml | grep autoattachMemBalloon
```

**Expected**: `autoattachMemBalloon: false` (for performance workloads)

**Enabled**: Disable it (see `methodology/vm-tuning-guide.md` Step 12).

---

### Check storage backend

**Only after ruling out CPU/vmexit/config issues**, check storage:

**Storage latency:**
```bash
# On storage node or from Prometheus
# Look for backend latency metrics
```

**Storage queue depth:**
- Check if storage is saturated
- Monitor IOPS vs capacity

**Network storage (NFS, Ceph):**
- Check network latency between host and storage
- Verify MTU settings (jumbo frames for performance)

---

## Common Root Causes and Fixes

### Forced fsync (1:1 flush:write ratio)

**Symptom**: `block.*.wr_operations` ≈ `block.*.fl_operations` in domstats

**Root cause**: Application or filesystem forcing sync after every write

**Action**:
- Check application settings (database WAL mode, etc.)
- Check filesystem mount options (`sync` vs `async`)
- For databases: tune fsync frequency (PostgreSQL `wal_writer_delay`, MySQL `innodb_flush_log_at_trx_commit`)

---

### Deep C-states delaying I/O interrupt handling

**Symptom**: I/O latency spikes, inconsistent performance, backend storage metrics look fine

**Root cause**: CPUs in deep C-states (C3/C6) take 80-200μs to wake up for I/O interrupts

**Action**:
- Enable `intel_c1_demotion`: `echo 1 > /sys/devices/system/cpu/cpuidle/intel_c1_demotion`
- Verify with I/O tests
- If confirmed: investigate kernel patches, BIOS settings causing excessive C-state entry

**Production fix**: Keep intel_c1_demotion enabled, NOT C1 pinning.

---

### Missing ioThreads configuration

**Symptom**: Single-threaded I/O processing, low throughput on multi-queue devices

**Root cause**: VM not configured with `ioThreadsPolicy: supplementalPool`

**Action**:
- Add ioThreadsPolicy to VM YAML (see `methodology/vm-tuning-guide.md` Step 2)
- Requires `blockMultiQueue: true`
- OCP 4.19+ feature

---

### EPT_VIOLATION exits during I/O

**Symptom**: High EPT_VIOLATION count in vmexit stats, domstats shows memory pressure

**Root cause**: Memory ballooning or host memory pressure causing page faults during I/O buffer access

**Action**:
- Disable memory balloon: `autoattachMemBalloon: false`
- Check host memory: `free -h` on KVM host
- Enable hugepages for large memory workloads (see `methodology/vm-tuning-guide.md` Step 6)

---

### Small I/O pattern inefficiency

**Symptom**: `block.*.wr_bytes / wr_operations` < 4KB — many small writes

**Root cause**: Application writing small chunks, filesystem/disk alignment issues

**Action**:
- Tune application I/O buffering
- Check filesystem block size alignment
- For databases: tune buffer pool size, checkpoint frequency

---

## Correlation Matrix

Use this matrix to correlate symptoms across different data sources:

| domstats Pattern | vmexit Pattern | C-state Check | Likely Root Cause |
|---|---|---|---|
| High wr_times | EXTERNAL_INTERRUPT high | Deep C-states enabled | C-state delays interrupt handling |
| 1:1 flush:write | HLT dominates time | Any | Forced fsync — app/filesystem issue |
| Low wr_bytes/op | Normal exits | Any | Small I/O pattern — app issue |
| Normal I/O metrics | EPT_VIOLATION high | Any | Memory pressure from balloon |
| cpu.user low % | HLT dominates time | Any | CPU waiting on I/O (or blocked) |

---

## Investigation Checklist

When investigating I/O degradation, check in this order:

- [ ] Collect virsh domstats baseline
- [ ] Collect vmexit stats from KVM host
- [ ] Check host C-state configuration (`cpuidle/state*/name`)
- [ ] Check `intel_c1_demotion` value (Intel CPUs)
- [ ] Try enabling `intel_c1_demotion` if disabled
- [ ] Check VM config: ioThreadsPolicy, blockMultiQueue, cache mode, memory balloon
- [ ] Correlate domstats + vmexit patterns using matrix above
- [ ] Only after ruling out config/C-state issues: check storage backend

**Most I/O degradation is NOT storage** — check CPU/interrupt/config first.

---

## Reference Commands

```bash
# Collect I/O metrics
virsh domstats <vm_name> > domstats.log

# Collect vmexit stats
cat /sys/kernel/debug/kvm/*/vcpu*/vmexit > vmexit_stats.txt

# Check C-states
cat /sys/devices/system/cpu/cpu0/cpuidle/state*/name
cat /sys/devices/system/cpu/cpu0/cpuidle/state*/latency

# Check intel_c1_demotion
cat /sys/devices/system/cpu/cpuidle/intel_c1_demotion

# Enable intel_c1_demotion
echo 1 > /sys/devices/system/cpu/cpuidle/intel_c1_demotion

# Check VM config
oc get vm <vm_name> -o yaml | grep -E "ioThreadsPolicy|blockMultiQueue|autoattachMemBalloon"
```

---

## Integration with Other Guides

- **VM configuration**: `methodology/vm-tuning-guide.md` — Steps 2, 5, 6, 12, 16, 17
- **Vmexit analysis**: `methodology/vmexit-analysis.md` — HLT, EPT_VIOLATION, EXTERNAL_INTERRUPT
- **VM config checks**: `/check-windows-vm-config`, `/check-linux-vm-config` — validate ioThreads, blockMultiQueue
