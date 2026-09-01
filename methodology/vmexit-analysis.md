# VM Exit Analysis Guide

VM exits (vmexits) occur when a guest VM traps into the hypervisor. Analyzing vmexit patterns helps identify virtualization overhead and configuration issues.

## Key Principle: Count vs Time

**Critical distinction**: High vmexit **count** doesn't always mean high **time impact**.

- **Exit count**: How many times the guest trapped to the hypervisor
- **Exit time**: How much time was spent handling those exits

Example:
- IO_INSTRUCTION: 68% of exits, but only 13% of time → many fast exits
- HLT: 32% of exits, but 87% of time → fewer exits, but guest is idle

**Always analyze both metrics** — count alone can be misleading.

---

## Data Collection

VM exit stats are available via debugfs on the KVM host:

```bash
# Per-VM vmexit stats
cat /sys/kernel/debug/kvm/*/vcpu*/vmexit

# Example output:
# HLT                   12345678  98765432100 ns
# IO_INSTRUCTION        45678912   5432109876 ns
# EPT_VIOLATION          1234567    987654321 ns
```

**Format**: `<exit_type>  <count>  <total_time_ns>`

---

## Common Exit Types and What They Mean

### HLT (Halt)

**What it is**: Guest executed HLT instruction — CPU is idle, giving control back to hypervisor.

**When to worry**:
- **High time %**: Normal for idle VMs — the guest has nothing to do
- **Low time %**: If HLT exits are frequent but take little time, investigate why the guest is waking up so often

**When it's a problem**:
- If the workload SHOULD be CPU-bound but HLT dominates → guest is waiting on something (I/O, locks, external events)

**Action**: Not usually a tuning target — indicates guest behavior, not misconfiguration.

---

### IO_INSTRUCTION

**What it is**: Guest executed I/O port instruction (IN/OUT) — typically for legacy device access.

**When to worry**:
- **High count + moderate time**: Many fast traps to emulated devices
- **On Windows VMs**: Often caused by `useplatformclock` forcing Windows to use PIT (slow legacy timer)

**Known root causes**:

| Exit Pattern | Root Cause | Fix |
|---|---|---|
| IO_INSTRUCTION dominates count | `useplatformclock` on Windows | `bcdedit /deletevalue useplatformclock` + reboot |
| High IO exits to port 0x40 | PIT (Programmable Interval Timer) access | Use hyperv clock instead |
| High IO exits to port 0x70/0x71 | RTC (Real-Time Clock) access | Ensure hyperv clock is configured |

**Action**:
- Check Windows VM: is `useplatformclock` set?
- Verify hyperv clock is configured in VM YAML (see `methodology/vm-tuning-guide.md` Step 10)
- Verify guest sees hyperv clock: `Get-ComputerInfo | Select "HyperV*"`

---

### EPT_VIOLATION (Extended Page Table Violation)

**What it is**: Guest accessed memory that wasn't mapped in the hypervisor's page tables.

**When to worry**:
- **High count**: Can indicate memory pressure or frequent page table updates
- **High time**: Expensive page fault handling

**Common causes**:
- Memory overcommit
- Guest memory ballooning
- Transparent hugepages not working

**Action**:
- Check host memory pressure
- Disable memory balloon: `autoattachMemBalloon: false`
- Enable hugepages if workload has large memory footprint (see `methodology/vm-tuning-guide.md` Step 6)

---

### EXTERNAL_INTERRUPT

**What it is**: Physical interrupt arrived while guest was running — hypervisor must handle it.

**When to worry**:
- **High count**: Can indicate interrupt storm or poor IRQ affinity

**Action**:
- Check for interrupt storms on host: `cat /proc/interrupts`
- Ensure network/disk interrupts are spread across CPUs
- For latency-sensitive workloads: use dedicated CPU placement (see `methodology/vm-tuning-guide.md` Step 7)

---

### PAUSE_INSTRUCTION

**What it is**: Guest executed PAUSE (spinlock hint) — indicates guest is spinning waiting for a lock.

**When to worry**:
- **High count**: Guest is contending on locks — possible CPU overcommit or oversubscription

**Action**:
- Check CPU allocation ratio (default 10:1)
- For latency-sensitive workloads: set requests = limits to guarantee CPU (see `methodology/vm-tuning-guide.md` Step 8)
- Pin vCPUs to dedicated pCPUs if needed (see `methodology/vm-tuning-guide.md` Step 7)

---

## Analysis Workflow

### Calculate percentages

From the raw stats, calculate:
- **Count %**: `(exit_type_count / total_exits) * 100`
- **Time %**: `(exit_type_time / total_time) * 100`

### Identify critical exits

**Critical = High time %**, not just high count %.

Sort by **time %** descending — focus on the top 2-3 exit types.

### Cross-reference with workload behavior

| Workload Type | Expected HLT Time % | Expected IO_INSTRUCTION % |
|---|---|---|
| CPU-bound (benchmark, compile) | <10% | <5% |
| I/O-bound (database, file server) | 20-40% | <10% |
| Idle VM | 80-95% | <5% |
| Windows VM with useplatformclock | 30-60% | 20-40% ⚠️ |

**Red flags**:
- CPU-bound workload with >50% HLT time → guest is blocked, not computing
- Windows VM with >15% IO_INSTRUCTION time → likely `useplatformclock` issue

### Correlate with domstats

Combine vmexit analysis with `virsh domstats` metrics:

| Vmexit Pattern | Domstats Signal | Diagnosis |
|---|---|---|
| High IO_INSTRUCTION | Low block.*.wr_bytes | Not disk I/O — likely timer/clock issue |
| High HLT | cpu.user < 50% | Guest is idle or waiting |
| High EPT_VIOLATION | balloon.available increasing | Memory pressure from ballooning |
| High EXTERNAL_INTERRUPT | net.*.rx.pkts very high | Interrupt storm from network |

---

## Interpreting Results

### IO_INSTRUCTION dominates count, low time %

**Example**: 68% of exits, 13% of time

**Diagnosis**: Many fast traps to emulated I/O ports — likely Windows VM with `useplatformclock`.

**Action**:
- Inside Windows VM: `bcdedit /deletevalue useplatformclock`
- Reboot
- Verify hyperv clock: `Get-ComputerInfo | Select "HyperV*"`

**Expected outcome**: IO_INSTRUCTION drops to <5% of exits.

---

### HLT dominates time, workload should be CPU-bound

**Example**: HLT is 87% of time, but this is a CPU benchmark

**Diagnosis**: Guest is idle when it shouldn't be — something is blocking execution.

**Possible causes**:
- Waiting on I/O (slow storage)
- Waiting on network
- CPU overcommit (guest scheduled out)

**Action**:
- Check domstats: is block I/O latency high?
- Check CPU allocation: are requests = limits? (see `methodology/vm-tuning-guide.md` Step 8)
- Check node CPU usage: is the host overloaded?

---

### EPT_VIOLATION high count and time

**Example**: EPT_VIOLATION is 30% of exits, 25% of time

**Diagnosis**: Frequent page faults — memory pressure or THP issues.

**Action**:
- Disable memory balloon: `autoattachMemBalloon: false`
- Enable hugepages for large memory workloads (see `methodology/vm-tuning-guide.md` Step 6)
- Check host memory: `free -h` — is the node swapping?

---

## Important Caveats

**Vmexit analysis is nuanced**:
- **Not all workloads have vmexit signatures** — some issues won't show up in vmexit stats
- **High vmexits ≠ always a problem** — HLT exits on an idle VM are normal
- **Context matters** — compare vmexit patterns to expected workload behavior
- **Combine with other data** — use domstats, pidstat, perf to triangulate the issue

**Known patterns** (like IO_INSTRUCTION from `useplatformclock`) are easier to diagnose. Novel patterns require deeper investigation.

---

## Reference Commands

```bash
# Collect vmexit stats on KVM host
cat /sys/kernel/debug/kvm/*/vcpu*/vmexit > vmexit_stats.txt

# Collect domstats for correlation
virsh domstats <vm_name> > domstats.log

# Check Windows clock source (inside Windows VM)
Get-ComputerInfo | Select-Object -Property "HyperV*"

# Check for useplatformclock (inside Windows VM)
bcdedit | findstr useplatformclock

# Remove useplatformclock (inside Windows VM, as Administrator)
bcdedit /deletevalue useplatformclock
```

---

## Integration with PerfX Skills

- **VM config checks**: `/check-windows-vm-config` and `/check-linux-vm-config` validate clock settings
- **VM tuning guide**: `methodology/vm-tuning-guide.md` — Steps 9-10 for Windows clock configuration
- **IO analysis**: `/io-analysis` — correlate vmexit with block I/O metrics from domstats

---

## Sources

- Red Hat KCS articles on vmexit analysis
- Internal case analysis (jpmc pattern: IO_INSTRUCTION from useplatformclock)
- KVM debugfs documentation
