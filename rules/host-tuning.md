# Host Tuning Best Practices

## C1 CPU Tuned Profile

**When to recommend:** Any latency-sensitive workload running on OCP worker nodes — Windows MSSQL, Linux databases (PostgreSQL, MySQL), or any IO-intensive VM workload.

**Why it matters:**
By default, CPUs enter deep sleep states (C6) when idle, causing wakeup latency of ~100µs. For database VMs, this adds unpredictable latency to every IO operation. Pinning CPUs to C1 (shallow sleep) reduces wakeup latency to ~1µs, making performance more consistent.

**How to apply:**
```bash
oc apply -f skills/ocp-analysis/tuned-c1.yaml
```

This applies the `c1-lowlatency` profile to all worker nodes via the Node Tuning Operator. No reboot required. Takes effect within ~60 seconds.

**How to verify:**
```bash
oc get profile.tuned.openshift.io -n openshift-cluster-node-tuning-operator
```
Workers should show `TUNED=c1-lowlatency` and `APPLIED=True`.

**Trade-off:**
Higher power consumption — CPUs never enter deep sleep. Acceptable for performance-critical workloads.

**Applies to:** All VMs on the node (Windows and Linux).
