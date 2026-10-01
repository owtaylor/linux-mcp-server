# Performance Co-Pilot (PCP) metrics guide

Performance Co-Pilot records system metrics continuously and stores them in archives,
so you can see what a system was doing hours or days ago, not just now.

Metric names are exact strings. A plausible-looking but wrong name returns an error or
no data, so take names from the catalog below rather than recalling them from memory.

This text is served twice over, as the `docs://pcp` resource and by the `pcp_guide`
tool, so that whichever one a client makes easy is enough. They are identical; having
read one, do not fetch the other.

## Choosing a tool

1. `get_system_information` — reports whether PCP is installed and running, and what
   time ranges its archives cover. Check the range before asking for a time outside it.
2. `pcp_performance_summary` — one broad snapshot (CPU, memory, disk, network, top
   processes), live or at a single moment in the past. Start here when you do not yet
   know which subsystem is at fault.
3. `pcp_query_metrics` — a time series of specific metrics. Use it once you know what
   to look at.
4. `pcp_list_metrics` — browse the metric namespace for something this guide does not
   cover. It lists one level at a time, so start broad and drill in, and it lists only
   what this system records, so everything in it can be queried.

## Time arguments

`start_time` and `end_time` accept an absolute timestamp (`2026-08-14 14:00:00`) or an
offset (`-2hours`, `-30min`, `now`). A time given without a UTC offset is read in the
**target system's** timezone, and results come back in that timezone.

Pass `start_time`, `end_time` and `interval` together for an exact window. If you omit
`interval`, one is chosen to give roughly 20 samples across the range, which is usually
what you want. Omitting both times gives the last hour.

A long range at a short interval produces a lot of output. Use a coarse interval first
to find when something happened, then re-query that narrower window finely.

## Reading the results

`pcp_query_metrics` returns JSON samples:

```json
[{"time": "2026-08-14T14:00:00+10:00", "metrics": {"<column>": "<value>"}}]
```

**Per-instance columns.** Many metrics carry one value per CPU, disk, interface or
filesystem. Each instance becomes its own column, named `metric-instance`:

```
disk.dev.read_bytes-sda            disk.dev.read_bytes-nvme0n1
network.interface.in.bytes-eth0    filesys.full-/dev/mapper/rhel-root
kernel.all.load-1 minute           kernel.all.load-5 minute
```

The catalog marks these `[per-X]`. Unmarked metrics have a single value.

**Counters are already rate-converted.** Metrics marked `[counter]` are cumulative
since boot, but are reported to you as a **per-second rate**. `disk.dev.read_bytes` is
bytes read per second during that sample, not bytes read since boot. Do not subtract
consecutive samples — that would give you the rate of a rate.

Metrics marked `[gauge]` are instantaneous readings, reported as-is.

**Prefer the ready-made percentages.** Where both exist, use the derived metric instead
of doing arithmetic on raw counters: the kernel.cpu.util metrics rather than the
kernel.all.cpu ones, and `disk.dev.util` and `disk.dev.await` rather than
`disk.dev.avactive` and `disk.dev.read_rawactive`.

**Units are not implied by the name.** A `_bytes` metric is not necessarily in bytes:
`disk.dev.read_bytes` and the mem.util metrics are in **Kbytes**, while
`network.interface.in.bytes` and `swap.used` really are in bytes. The catalog gives the
unit wherever it is not obvious; use it rather than assuming.

**Missing values.** A metric with no value at a given sample is omitted from that sample
rather than reported as null. A column absent from every sample usually means the
metric is not recorded on this system.

## Metric catalog

These are recorded by a default `pmlogger` configuration on a recent RHEL system, so
they are normally available for historical queries. A few marked `[live only]` exist on
the system but are not archived; those work only for the live case.

### CPU utilization

Prefer these. They are percentages across all CPUs and need no conversion.

- `kernel.cpu.util.user` — percentage of user time, including guest `[gauge]`
- `kernel.cpu.util.sys` — percentage of system time `[gauge]`
- `kernel.cpu.util.idle` — percentage of idle time `[gauge]`
- `kernel.cpu.util.wait` — percentage of time blocked on I/O `[gauge]`
- `kernel.cpu.util.steal` — percentage taken by the hypervisor; high values mean the
  host is oversubscribed `[gauge]`
- `kernel.cpu.util.nice` — percentage of nice user time `[gauge]`
- `kernel.cpu.util.intr` — percentage of interrupt time `[gauge]`

Raw CPU time counters, for per-CPU detail or a breakdown the above lacks:

- `kernel.all.cpu.user`, `kernel.all.cpu.sys`, `kernel.all.cpu.idle`,
  `kernel.all.cpu.nice`, `kernel.all.cpu.steal`, `kernel.all.cpu.guest` `[counter]`
- `kernel.all.cpu.wait.total` — time blocked on I/O `[counter]`
- `kernel.all.cpu.irq.hard`, `kernel.all.cpu.irq.soft` — interrupt time `[counter]`
- `kernel.percpu.cpu.user`, `kernel.percpu.cpu.sys`, `kernel.percpu.cpu.idle`,
  `kernel.percpu.cpu.wait.total`, `kernel.percpu.cpu.steal` — per logical CPU
  `[counter]` `[per-CPU]`
- `kernel.pernode.cpu.user`, `kernel.pernode.cpu.sys`, `kernel.pernode.cpu.idle`,
  `kernel.pernode.cpu.steal` — per NUMA node `[counter]` `[per-node]`

### Load and scheduling

- `kernel.all.load` — load average `[gauge]` `[per-interval: 1 minute, 5 minute,
  15 minute]`
- `kernel.all.runnable` — processes on a run queue; compare against `hinv.ncpu` `[gauge]`
- `kernel.all.running` — processes currently running `[gauge]`
- `kernel.all.blocked` — processes in uninterruptible sleep, usually waiting on I/O
  `[gauge]`
- `kernel.all.nprocs` — total processes and threads `[gauge]`
- `kernel.all.pswitch` — context switches per second `[counter]`
- `kernel.all.intr` — interrupts per second `[counter]`
- `kernel.all.sysfork` — forks per second `[counter]`
- `kernel.all.uptime` — seconds since boot; a drop means the system rebooted `[gauge]`

### Pressure stall information (PSI)

The clearest signal that a resource is actually hurting the workload. `some` means at
least one task was delayed; `full` means nothing could make progress.

- `kernel.all.pressure.cpu.some.avg` — percentage of time tasks were delayed waiting
  for CPU `[gauge]` `[per-window: 10 second, 1 minute, 5 minute]`
- `kernel.all.pressure.memory.some.avg` — delayed on memory `[gauge]` `[per-window]`
- `kernel.all.pressure.memory.full.avg` — all work stalled on memory `[gauge]`
  `[per-window]`
- `kernel.all.pressure.io.some.avg` — delayed on I/O `[gauge]` `[per-window]`
- `kernel.all.pressure.io.full.avg` — all work stalled on I/O `[gauge]` `[per-window]`

### Memory

All in Kbytes unless noted.

- `mem.physmem` — total usable physical memory `[gauge]`
- `mem.util.available` — memory available for new work without swapping; **this is the
  one to watch**, not `mem.util.free` `[gauge]`
- `mem.util.used` — used memory; counts page cache as used `[gauge]`
- `mem.util.free` — genuinely unallocated memory; low is normal and not a problem on
  its own `[gauge]`
- `mem.util.cached` — page cache `[gauge]`
- `mem.util.bufmem` — I/O buffers `[gauge]`
- `mem.util.anonpages` — anonymous pages, i.e. real process memory `[gauge]`
- `mem.util.slab` — kernel slab allocations `[gauge]`
- `mem.util.dirty` — dirty pages awaiting writeback `[gauge]`
- `mem.util.shmem` — shared memory and tmpfs `[gauge]`
- `mem.util.committed_AS` — memory committed to address spaces `[gauge]`
- `mem.util.commitLimit` — commit ceiling; compare with `mem.util.committed_AS`
  `[gauge]`

Memory pressure and reclaim:

- `mem.vmstat.pgmajfault` — major faults per second, i.e. faults served from disk; the
  key sign of thrashing `[counter]`
- `mem.vmstat.pgfault` — all page faults per second `[counter]`
- `mem.vmstat.pgscan_direct_total` — pages scanned by direct reclaim per second;
  nonzero means allocation is stalling `[counter]`
- `mem.vmstat.pgscan_kswapd_total` — pages scanned by kswapd per second `[counter]`
- `mem.vmstat.pgsteal_total` — pages reclaimed per second `[counter]`
- `mem.vmstat.oom_kill` — OOM kills per second `[counter]`
- `mem.vmstat.pswpin` — pages swapped in per second `[counter]`
- `mem.vmstat.pswpout` — pages swapped out per second `[counter]`

### Swap

- `swap.length` — total swap configured, bytes `[gauge]`
- `swap.used` — swap in use, bytes; a high but static value is usually harmless
  `[gauge]`
- `swap.free` — swap free, bytes `[gauge]`
- `swap.pagesin` — pages read from swap per second `[counter]`
- `swap.pagesout` — pages written to swap per second; sustained traffic here is the
  real sign of swap trouble `[counter]`

### Disk I/O

Per-device metrics are instanced by device name (`sda`, `nvme0n1`). Use the disk.dm
metrics for LVM and device-mapper volumes, and `hinv.map.dmname` to map `dm-N` to a
friendly name.

- `disk.dev.util` — percentage of time the device was busy `[gauge]` `[per-device]`
- `disk.dev.await` — average time a request spent queued and serviced, milliseconds
  `[gauge]` `[per-device]`
- `disk.dev.r_await` — the same for reads `[gauge]` `[per-device]`
- `disk.dev.w_await` — the same for writes `[gauge]` `[per-device]`
- `disk.dev.read`, `disk.dev.write`, `disk.dev.total` — operations per second
  `[counter]` `[per-device]`
- `disk.dev.read_bytes`, `disk.dev.write_bytes`, `disk.dev.total_bytes` — **Kbytes**
  per second, not bytes `[counter]` `[per-device]`
- `disk.dev.aveq` — time-averaged request queue length `[counter]` `[per-device]`
- `disk.all.read`, `disk.all.write`, `disk.all.total` — operations per second summed
  over all disks `[counter]`
- `disk.all.read_bytes`, `disk.all.write_bytes`, `disk.all.total_bytes` — **Kbytes**
  per second summed over all disks `[counter]`
- `disk.dm.util` — percentage busy, per device-mapper volume `[gauge]`
  `[per-dm-device]`
- `disk.dm.await` — average request time in milliseconds, per device-mapper volume
  `[gauge]` `[per-dm-device]`
- `disk.dm.read_bytes`, `disk.dm.write_bytes` — Kbytes per second, per device-mapper
  volume `[counter]` `[per-dm-device]`

### Filesystems

Instanced by device; `filesys.mountdir` gives the mount point for each.

- `filesys.full` — percentage of the filesystem in use; the quickest check `[gauge]`
  `[per-filesystem]`
- `filesys.capacity`, `filesys.used`, `filesys.free` — Kbytes `[gauge]`
  `[per-filesystem]`
- `filesys.avail` — Kbytes free to non-root; what ordinary processes can actually use
  `[gauge]` `[per-filesystem]`
- `filesys.maxfiles`, `filesys.usedfiles`, `filesys.freefiles` — inode counts; a
  filesystem can run out of inodes while still having free space `[gauge]`
  `[per-filesystem]`
- `filesys.mountdir` — mount point `[gauge]` `[per-filesystem]`
- `filesys.type` — filesystem type `[gauge]` `[per-filesystem]`

### Network

Instanced by interface name.

- `network.interface.in.bytes`, `network.interface.out.bytes` — bytes per second
  `[counter]` `[per-interface]`
- `network.interface.in.packets`, `network.interface.out.packets` — packets per second
  `[counter]` `[per-interface]`
- `network.interface.in.errors`, `network.interface.out.errors` — errors per second;
  should be zero `[counter]` `[per-interface]`
- `network.interface.in.drops`, `network.interface.out.drops` — dropped packets per
  second `[counter]` `[per-interface]`
- `network.interface.speed` — link speed in Mbytes per second; use it to turn byte
  rates into link utilization `[gauge]` `[per-interface]`
- `network.interface.up` — whether the link is up `[gauge]` `[per-interface]`

TCP and UDP, system-wide:

- `network.tcp.retranssegs` — segments retransmitted per second; compare against
  `network.tcp.outsegs` for a loss rate `[counter]`
- `network.tcp.insegs`, `network.tcp.outsegs` — segments per second `[counter]`
- `network.tcp.activeopens` — outgoing connections established per second `[counter]`
- `network.tcp.passiveopens` — incoming connections accepted per second `[counter]`
- `network.tcp.attemptfails` — failed connection attempts per second `[counter]`
- `network.tcp.listendrops` — SYNs dropped because the accept queue was full, i.e. a
  backlogged server `[counter]`
- `network.tcp.listenoverflows` — listen queue overflows per second `[counter]`
- `network.udp.indatagrams`, `network.udp.outdatagrams` — datagrams per second
  `[counter]`
- `network.udp.inerrors` — UDP receive errors per second `[counter]`
- `network.sockstat.tcp.inuse` — TCP sockets in use `[gauge]`
- `network.sockstat.tcp.tw` — sockets in TIME_WAIT `[gauge]`
- `network.sockstat.tcp.orphan` — orphaned sockets `[gauge]`
- `network.sockstat.total` — all sockets in use `[gauge]`
- `network.tcpconn.established`, `network.tcpconn.time_wait`,
  `network.tcpconn.close_wait` — connection counts by state `[gauge]` `[live only]`

### Processes

- `proc.nprocs` — number of processes `[gauge]`
- `proc.runq.runnable` — processes on a run queue `[gauge]`
- `proc.runq.blocked` — processes in uninterruptible sleep `[gauge]`
- `vfs.files.count`, `vfs.files.max` — open file handles against the system limit
  `[gauge]`
- `vfs.inodes.count`, `vfs.dentry.count` — in-use inode and dentry structures `[gauge]`

Per-process history is thin. Archives keep only these three, instanced once per
process, and **each produces one column per process, so a busy system yields hundreds
of columns.** Query them over a short window with a coarse interval, and only after the
system-wide metrics have told you which resource is under strain.

- `proc.memory.rss` — resident set size, Kbytes `[gauge]` `[per-process]`
- `proc.memory.size` — virtual size, Kbytes `[gauge]` `[per-process]`
- `proc.psinfo.maj_flt` — major faults per second `[counter]` `[per-process]`

There is no archived per-process CPU time, so historical questions of the form "which
process was burning the CPU" cannot be answered from metrics alone. Use
`pcp_performance_summary` at the time of interest instead; it reports top processes.

### System inventory

Constant or slow-changing values, useful for turning rates into ratios.

- `hinv.ncpu` — number of logical CPUs; divide `kernel.all.runnable` by this `[gauge]`
- `hinv.physmem` — total physical memory, Mbytes `[gauge]`
- `hinv.ndisk`, `hinv.nfilesys`, `hinv.ninterface` — device counts `[gauge]`
- `hinv.nnode` — NUMA nodes `[gauge]`
- `hinv.pagesize` — page size in bytes `[gauge]`
- `hinv.machine` — hardware architecture `[gauge]`
- `hinv.cpu.model_name` — CPU model `[gauge]` `[per-CPU]`
- `hinv.map.dmname` — maps `dm-N` to its persistent name, for reading the disk.dm
  instances `[gauge]` `[per-dm-device]`
- `kernel.uname.release` — kernel release recorded in the archive `[gauge]`
- `kernel.uname.distro` — distribution name `[gauge]`
- `kernel.uname.nodename` — hostname `[gauge]`

## If a metric you need is not listed

Anything outside this catalog — XFS internals, NFS, KVM, IPC, per-CPU interrupts,
SCSI or fibre channel — may still be reachable through `pcp_list_metrics`. Call it
with no prefix for the top-level namespaces, then again with the one you want in
order to see inside it. Narrow the problem down with the metrics above first, so
that you know which subsystem to browse.

`pcp_list_metrics` lists only what this system's `pmlogger` records, which is what
`pcp_query_metrics` can return. That is well under half of what PCP defines, and
whole subsystems of it: on a default configuration cgroups, containers, process
accounting and per-process `hotproc` metrics are not recorded at all. A subsystem
missing from the listing has no history to query, so do not guess names into it.

A metric marked `[live only]` above, or absent from the listing, returns no data
historically. Fall back to the closest metric that does return data rather than
retrying variations on the name.
