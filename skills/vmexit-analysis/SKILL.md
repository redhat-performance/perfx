# /vmexit-analysis

Analyze KVM vmexit statistics to identify virtualization overhead and configuration issues.

## Methodology

- Read `methodology/vmexit-analysis.md` for vmexit interpretation guide (HLT vs IO_INSTRUCTION, count vs time impact)

## Data Source

VM exit stats from KVM debugfs:
```bash
cat /sys/kernel/debug/kvm/*/vcpu*/vmexit > vmexit_stats.txt
```

## What to analyze

- **HLT exits**: High time % indicates guest is idle — expected for idle VMs, investigate if workload should be CPU-bound
- **IO_INSTRUCTION exits**: High count on Windows VMs indicates `useplatformclock` issue (force Windows to use PIT)
- **EPT_VIOLATION**: Memory pressure or hugepage issues
- **EXTERNAL_INTERRUPT**: Interrupt storms or poor IRQ affinity
- **PAUSE_INSTRUCTION**: Lock contention, possible CPU overcommit

## Key principle

**Count ≠ Time impact**. Example:
- IO_INSTRUCTION: 68% of exits, but only 13% of time
- HLT: 32% of exits, but 87% of time ← **this is the critical exit**

Always report both count % and time % when analyzing vmexits.

## Steps

**Automated analysis script**: Not yet implemented — manual analysis workflow:

- Collect vmexit stats from KVM host
- Calculate count % and time % for each exit type
- Sort by **time %** (not count %) to identify critical exits
- Cross-reference with workload type (CPU-bound vs I/O-bound vs idle)
- Correlate with domstats metrics (see `/io-analysis`)
- Provide diagnosis and fix recommendations

## Common fixes

- **IO_INSTRUCTION high**: Inside Windows VM run `bcdedit /deletevalue useplatformclock` then reboot
- **EPT_VIOLATION high**: Disable memory balloon (`autoattachMemBalloon: false`), enable hugepages
- **PAUSE high**: Reduce CPU overcommit, set requests = limits for guaranteed QoS

## Integration

- Windows VM clock config: see `methodology/vm-tuning-guide.md` Steps 9-10
- CPU allocation: see `methodology/vm-tuning-guide.md` Steps 7-8
- Hugepages: see `methodology/vm-tuning-guide.md` Step 6
