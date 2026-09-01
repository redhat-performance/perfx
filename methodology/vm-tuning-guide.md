# VM Configuration and Tuning Guide

Reference: https://developers.redhat.com/blog/2026/05/06/best-practice-configuration-and-tuning-linux-and-windows-vms#vm_definition
Tuning & Scaling Guide: https://access.redhat.com/articles/6994974
VirtualMachinePreference customization: https://access.redhat.com/solutions/7123335

---

## Step 1 — Apply a VirtualMachineClusterPreference

Always apply a `VirtualMachineClusterPreference` to every VM — it automatically applies
critical optimizations (hyperv enlightenments, clock config, bus type, etc.).

```bash
# List available preferences
oc get VirtualMachineClusterPreference

# Common preferences
windows.2k25.virtio   # Windows Server 2025
windows.2k22.virtio   # Windows Server 2022
rhel.9.virtio         # RHEL 9
```

Apply in the VM spec:
```yaml
spec:
  preference:
    name: windows.2k25.virtio
```

> A reboot is required if the VM is already running when preferences are applied.

Inspect what settings are active on a running VM:
```bash
oc get vmi <vm_name> -o yaml
```

---

## Step 2 — Disk configuration

| Setting | Recommended | Avoid |
|---|---|---|
| Bus type | `bus: virtio` | `bus: sata` — poor performance |
| IO threads | `ioThreadsPolicy: supplementalPool` (OCP 4.19+) | none |
| Block volumes | `io: native` applied automatically | — |
| Filesystem volumes | Use **preallocation** to enable `io: native` | — |

**io: native** bypasses the page cache and issues direct IO to the block device,
reducing latency and CPU overhead. For filesystem-backed PVCs, preallocation
must be enabled at PVC creation time to unlock this mode.

**ioThreads supplementalPool** (introduced OCP 4.19):
Reference: https://developers.redhat.com/blog/2025/06/23/feature-introduction-multiple-iothreads-openshift-virtualization
- Spreads VM disk IO across multiple submission threads mapped to multiple disk queues
- Requires `blockMultiQueue: true` and `bus: virtio`
- Recommended: 16 vCPUs + 4 IOthreads as a starting point; up to 8-16 on fast storage
- Up to 2× improvement in microbenchmarks
- Thread count adds to vCPU count for CPU request calculations
- Not compatible with `dedicatedCpuPlacement` or `isolateEmulatorThread`
- Storage live migration unsupported before 4.21

---

## Step 3 — Network configuration

| Setting | Recommended | Avoid |
|---|---|---|
| Model | `model: virtio` | `model: e1000e` — poor performance |
| Throughput | `networkInterfaceMultiqueue: true` | — |

---

## Step 4 — Host Tuned profile

OpenShift nodes default to a **"throughput performance"** Tuned profile, suitable
for broad workload types. This is managed via the Node Tuning Operator.

For latency-sensitive workloads (MSSQL, real-time), additional profiles are available.
Check the active profile on a node:
```bash
tuned-adm active
```

---

## Step 5 — Host C-state tuning (latency-sensitive workloads)

For MSSQL and other latency-sensitive workloads, limit CPU sleep depth to C1.
The OCP-native way (no reboot required) is via the Node Tuning Operator:

```yaml
apiVersion: tuned.openshift.io/v1
kind: Tuned
metadata:
  name: c1-lowlatency
  namespace: openshift-cluster-node-tuning-operator
spec:
  profile:
  - data: |
      [main]
      summary=Pins to C1 cstate for low latency
      include=openshift-node
      [cpu]
      force_latency=1
    name: c1-lowlatency
  recommend:
  - machineConfigLabels:
      machineconfiguration.openshift.io/role: "worker"
    priority: 20
    profile: c1-lowlatency
```

Verify C-states after applying:
```bash
# From sosreport or live host:
cat /sys/devices/system/cpu/cpu0/cpuidle/state*/name
cat /sys/devices/system/cpu/cpu0/cpuidle/state*/latency
# Expected: only POLL (0us) and C1 (1us)
```

---

## Step 6 — Hugepages (for workloads with large memory footprint)

Default RHEL kernels use THP (Transparent HugePages) with auto-promotion.
For workloads sensitive to TLB misses (large MSSQL buffer pools):

```yaml
# In VM spec:
domain:
  memory:
    hugepages:
      pageSize: 1Gi   # 1GB hugepages
```

Pre-allocate on the node via MachineConfig or Node Tuning Operator.

---

## Step 7 — CPU isolation and pinning

For workloads sensitive to scheduler disruptions or requiring very low latency
(e.g. MSSQL on large VMs):

- Pin vCPUs to dedicated physical CPUs to prevent scheduler interference
- Isolate CPUs from the host OS scheduler using `isolcpus` or CPU Manager
- Use `dedicatedCpuPlacement: true` in the VM spec

```yaml
spec:
  domain:
    cpu:
      dedicatedCpuPlacement: true
```

See: https://access.redhat.com/articles/6994974 — Pinning sections for full details.

---

## Step 8 — CPU Allocation Ratio

Default overcommit is 10:1. For latency-sensitive MSSQL workloads, reduce or
set exact CPU requests/limits to guarantee CPU resources:

```yaml
resources:
  requests:
    cpu: "24"
  limits:
    cpu: "24"    # requests == limits = guaranteed QoS
```

---

# Windows VM-Specific Configuration

Reference: https://developers.redhat.com/blog/2026/05/06/best-practice-configuration-and-tuning-linux-and-windows-vms#vm_definition

## Step 9 — Hyperv Enlightenments (Windows Only)

Hyperv enlightenments are paravirtualization features that dramatically improve Windows VM performance.

**Required enlightenments** (30-40% performance improvement):
```yaml
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
      direct: {}    # Must include direct mode
    spinlocks:
      spinlocks: 8191    # Must be exactly 8191
```

**Why each matters:**
- **relaxed**: Reduces overhead of timer checks
- **vapic**: Virtual APIC for interrupt handling
- **spinlocks**: Prevents guest spinning on locks (must be 8191)
- **synictimer**: Synthetic timer with direct mode for lower latency
- **ipi/tlbflush**: Inter-processor interrupts and TLB management
- **frequencies**: Exposes TSC frequency to guest
- **reenlightenment**: Maintains TSC across live migration

**Verification inside Windows VM:**
```powershell
# Check if hyperv is detected
Get-ComputerInfo | Select-Object -Property "HyperV*"

# Or via msinfo32 GUI
msinfo32
# Look for "Hyper-V Requirements" section
```

---

## Step 10 — Clock Configuration (Windows Only)

Windows VMs require specific timer configuration to avoid time drift and performance issues.

```yaml
clock:
  timer:
    hpet:
      present: false    # HPET must be disabled
    hyperv: {}          # Hyperv clock required
    pit:
      tickPolicy: delay
    rtc:
      tickPolicy: catchup
  utc: {}
```

**Why this matters:**
- **HPET disabled**: High Precision Event Timer causes overhead in virtualized environments
- **Hyperv clock**: Paravirtualized clock source (most accurate)
- **PIT/RTC policies**: Prevent time drift under load

---

## Step 11 — Guest-Side Windows Configuration

**CRITICAL**: These steps must be performed inside the Windows guest OS after VM deployment.

### Remove Platform Clock Override
```powershell
# Run as Administrator, then reboot
bcdedit /deletevalue useplatformclock
```

**Why**: The platform clock override forces Windows to use a slow clock source. Removing it allows Windows to use the hyperv clock.

### Disable VBS (Virtualization-Based Security)

**Impact**: VBS causes 30-50% performance penalty for benchmarks/performance testing.

**How to check:**
```
msinfo32 → Look for "Virtualization-based security: Not enabled"
```

**How to disable:**
1. Windows Security → Device Security → Core isolation
2. Memory integrity → **Off**
3. Reboot

**When to keep VBS enabled:**
- Production security workloads
- Compliance requirements
- NOT for performance benchmarks

---

## Step 12 — Memory Balloon (Windows)

Disable memory balloon for performance workloads:

```yaml
devices:
  autoattachMemBalloon: false
```

**Why**: Memory ballooning can cause:
- Unpredictable memory pressure
- Guest paging/swapping
- Performance degradation

---

## Step 13 — Machine Type (Windows)

Use the latest Q35 machine type for I/O performance:

```yaml
machine:
  type: pc-q35-rhel9.8.0    # OCP 4.22+ recommended
```

**Why Q35:**
- PCIe topology (vs legacy PCI)
- Better I/O performance
- Required for some hyperv features

**Minimum**: `pc-q35-rhel9.8.0` (OCP 4.22+) for I/O coalescing support

---

## Step 14 — Firmware (Windows)

Use EFI firmware (not legacy BIOS):

```yaml
firmware:
  bootloader:
    efi:
      secureBoot: false    # Disable for performance testing
```

**Why EFI:**
- Modern boot process
- Required for some Windows features
- Better performance than legacy BIOS

---

## Step 15 — TPM (Optional, Windows)

For Windows 11 or security workloads:

```yaml
devices:
  tpm: {}
```

**Note**: Not required for performance benchmarks, but needed for Windows 11 installation.

---

## Complete Windows VM Example

Minimal optimized Windows VM configuration:

```yaml
apiVersion: kubevirt.io/v1
kind: VirtualMachine
metadata:
  name: windows-perf-vm
spec:
  preference:
    name: windows.2k25.virtio    # Auto-applies most settings
  template:
    spec:
      evictionStrategy: LiveMigrate
      domain:
        devices:
          autoattachMemBalloon: false
          blockMultiQueue: true
          networkInterfaceMultiqueue: true
          disks:
          - name: rootdisk
            disk:
              bus: virtio
        cpu:
          sockets: 1
          cores: 24
          threads: 1
        ioThreads:
          supplementalPoolThreadCount: 6    # ~vCPUs/4
        ioThreadsPolicy: supplementalPool
        machine:
          type: pc-q35-rhel9.8.0
        firmware:
          bootloader:
            efi:
              secureBoot: false
        resources:
          requests:
            memory: 64Gi
            cpu: "24"
          limits:
            memory: 64Gi
            cpu: "24"
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
```

**After deployment, inside Windows guest:**
1. `bcdedit /deletevalue useplatformclock` (reboot)
2. Disable VBS via Windows Security (reboot)
3. Verify hyperv detected: `Get-ComputerInfo | Select "HyperV*"`
