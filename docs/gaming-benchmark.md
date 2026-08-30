# Gaming Benchmark Workflow

> Status: managed operator workflow for Windows game-performance captures.

The Windows benchmark harness is deployed by:

```bash
ansible-playbook playbooks/windows/windows-gaming-benchmark.yml
```

The persistent operator wrapper is:

```bash
bin/windows-gaming-benchmark
```

The wrapper runs `./bin/ansible-controller-guard check` before contacting Windows, then calls the managed playbook. Do not recreate one-off `/tmp` playbooks for normal benchmark start, stop, marker, status, or fetch operations.

## Common Flow

Start a capture:

```bash
bin/windows-gaming-benchmark start --label fortnite-match-baseline
```

The managed target list can include multiple games. On `lj-gaming-pc`, the
current target list includes Fortnite and Kovaak's. When more than one known
target is running, the sampler prefers the foreground game window; if no known
game is foreground, it falls back to inventory order. Target markers record
`target-started-*`, `target-switched-*`, and `target-exited-*`, and
`combined.csv` includes `TargetProcessName` so mixed captures can be split by
game later.

Before comparing FPS, lows, CPU busy, GPU busy, or stutter counts across two
captures, compare the analyzer's `process_presence.notable` sections. A capture
where normal workflow apps are missing, newly present, or present under a
different recording/overlay stack is not directly comparable until that process
delta is called out. Do not bury this in raw `process-inventory.csv`; state the
presence delta first, then interpret performance.

Start while recording preflight warnings without blocking the capture:

```bash
bin/windows-gaming-benchmark start --label fortnite-match-baseline --allow-preflight-warnings
```

Use that only when the warning is already understood and you want the capture
artifact anyway. Example: Memory Compression can be large before a benchmark
while Windows still has plenty of available RAM; in that case the warning should
be recorded in `preflight.csv` and interpreted later, not automatically cost the
session.

Benchmark preflight records available memory, Memory Compression size, stale
PowerShell diagnostics, top memory consumers, large process private/commit
memory, and recent Windows Resource Exhaustion Detector events. A recent
resource-exhaustion event or absurd process commit consumer means the capture
should be treated as a bad-state capture unless that warning is already
explained.

Mark a moment during the run:

```bash
bin/windows-gaming-benchmark mark --marker match-start
bin/windows-gaming-benchmark mark --marker stutter
bin/windows-gaming-benchmark mark --marker match-end
```

Peek at a running capture without fetching the archive:

```bash
bin/windows-gaming-benchmark peek
```

`peek` reads bounded tails from `combined.csv`, `system.csv`,
`top-processes.csv`, `target-threads.csv`, `markers.csv`, and recent Windows
Search event 10024 warnings. It deliberately does not read the active
`presentmon-console.csv`, because that file can be locked by PresentMon while a
capture is running.

After the managed script has already been deployed, use the lower-overhead form
during active gameplay:

```bash
bin/windows-gaming-benchmark peek --no-deploy
```

Even `peek --no-deploy` still runs a remote PowerShell action and can perturb a
competitive match. Prefer markers and final `stop --fetch` for authoritative
analysis, and avoid repeated live peeks unless the diagnostic value outweighs
the risk of adding its own stutter.

Stop and fetch the capture archive for local analysis:

```bash
bin/windows-gaming-benchmark stop --fetch --dest /tmp
```

Fetch the latest capture without stopping anything:

```bash
bin/windows-gaming-benchmark fetch --dest /tmp
```

As of the 2026-08-26 regression capture, fetching while a capture is still
active can fail because `presentmon-console.csv` is held open by the running
sampler/PresentMon process. If you need an authoritative archive for analysis,
use `stop --fetch`. For a quick mid-capture check, use `peek` instead of
starting duplicate fetch workers.

If `stop --fetch` fails because `presentmon-console.csv` is still locked after
stop, first check whether the analyzer reports `benchmark_sampler_failure` or
whether a capture-owned `PresentMon*.exe` process still has the target
`presentmon-console.csv` in its command line. The managed harness should clean
up those capture-owned workers, but the 2026-08-29 Reload capture exposed and
fixed a stop-path gap after a sampler crash.

Fetch a specific Windows capture directory:

```bash
bin/windows-gaming-benchmark fetch --capture-dir 'C:\Users\jn\AppData\Local\WindowsGamingBenchmark\Captures\20260523-005536-fortnite-match-highres-off-lobby-to-game' --dest /tmp
```

Analyze after unzipping locally:

```bash
python3 scripts/gaming/analyze-gaming-capture.py /tmp/fortnite-match-highres-off-lobby-to-game
```

The analyzer reads `benchmark.log` and adds a `benchmark_sampler_failure`
diagnosis when the sampler crashed before stop. Treat any capture with that
diagnosis as truncated; compare the last telemetry timestamp to the stop marker
before drawing gameplay, lobby-tail, or app-attribution conclusions.

For captures where Johnny forgets to mark the match end and then sits in the
Fortnite lobby, use `visible_sustained_120_cap_tail`. This detector works from
the end of the capture by finding the final sample above the lobby threshold
and treating the following sustained 120-FPS region as the tail. Do not cut on
the first 120-FPS window in the file, because pre-match lobby time can be
followed by real gameplay.

The analyzer also emits `process_presence`, including `all_process_names`,
`missing_notable_groups`, and a compact `notable` table for Fortnite, OBS,
Firefox, Medal, Tracker/Overwolf, Discord, Steam, Epic, Rockstar, Xbox/Game
Bar, SignalRGB app/service, iCUE/Corsair, SteelSeries, Logitech, Sonobus,
Nextcloud, NVIDIA overlay, RTSS/Afterburner, and Memory Compression. Use this
section for capture-to-capture comparability before making performance claims.

## A/B Test Options

Affinity test:

```bash
bin/windows-gaming-benchmark start --label fortnite-affinity-ccd0 --affinity ccd0
bin/windows-gaming-benchmark start --label fortnite-affinity-ccd1 --affinity ccd1
bin/windows-gaming-benchmark start --label fortnite-affinity-ccx0 --affinity ccx0
```

Priority test:

```bash
bin/windows-gaming-benchmark start --label fortnite-priority-high --priority High
```

Power-plan test:

```bash
bin/windows-gaming-benchmark start --label fortnite-ryzen-balanced --power ryzen-balanced
bin/windows-gaming-benchmark start --label fortnite-ryzen-high --power ryzen-high
```

Do not bake affinity, priority, or power-plan changes into Performance Mode until repeated captures show a clear win.

## Managed Windows Paths

- Script directory: `C:\ProgramData\Johnny\GamingTools\Benchmark`
- State directory: `C:\Users\jn\AppData\Local\WindowsGamingBenchmark`
- Capture directory: `C:\Users\jn\AppData\Local\WindowsGamingBenchmark\Captures`

The capture script writes:

- `presentmon-console.csv`
- `combined.csv`
- `system.csv`
- `nvidia-smi.csv`
- `watched-processes.csv`
- `top-processes.csv`
- `target-threads.csv`
- `process-inventory.csv`
- `markers.csv`
- `event-log.csv`
- `obs-profile.csv`
- `preflight.csv`

`process-inventory.csv` includes executable path and redacted command-line
context. It must not store raw launcher/game auth arguments; the managed
template redacts common token, password, API key, and Fortnite launch auth
fields before writing rows.

## Telemetry Sources

The benchmark harness is not supposed to rely on PresentMon as the only signal.
It can collect:

- PresentMon frame timing: `FrameTime`, `CPUBusy`, `CPUWait`, `GPUTime`, `GPUBusy`, `GPUWait`, display latency, present mode, and runtime.
- Windows system counters: CPU total/max utility, CPU DPC/interrupt time, CPU max frequency, memory pressure, disk latency/queue, network throughput, and GPU engine counters when enabled.
- NVIDIA SMI: NVIDIA GPU utilization, memory utilization, graphics/memory clocks, power, temperature, VRAM use, and PCIe link state.
- RTSS shared memory: RTSS FPS and frame-time windows when enabled.
- MSI Afterburner / MAHM shared memory: OSD FPS/frame time plus hardware-monitoring values such as CPU/GPU clocks, temperatures, power, and usage when enabled.
- Windows event logs: warning/error/critical System and Application events for the capture window, written at stop time.
- Process/thread sampling: watched-process CPU/memory/I/O deltas, top process CPU/I/O deltas, target process hot-thread samples, process inventory, OBS profile snapshot, markers, and preflight warnings.
- Preflight state: available memory, Memory Compression, top process memory, suspicious private/commit memory, recent Resource Exhaustion Detector events, and stale external PowerShell workers before the capture starts.

The process I/O columns in `watched-processes.csv` and `top-processes.csv`
come from raw Windows per-process I/O counters sampled as before/after deltas.
They are not direct per-process network counters, but they help identify
upload, cache, file, or socket churn when `system.csv` shows high network
throughput or disk activity during a bad frame-pacing window.

On `lj-gaming-pc`, the current inventory enables PresentMon, RTSS shared
memory, MAHM/Afterburner shared memory, and NVIDIA SMI:

```yaml
windows_gaming_benchmark_presentmon_enabled: true
windows_gaming_benchmark_pmdp_enabled: false
windows_gaming_benchmark_rtss_enabled: true
windows_gaming_benchmark_mahm_enabled: true
windows_gaming_benchmark_nvidia_smi_enabled: true
```

RTSS/MAHM rows depend on those shared-memory maps existing in the interactive
Windows session. RTSS must be running and tracking the game for RTSS FPS rows.
Afterburner/MAHM hardware monitoring must be running for CPU temperature and
other sensor rows. If either map is unavailable, the harness records a status
row instead of failing the benchmark.

If PresentMon's FPS disagrees with the in-game FPS graph, do not treat
PresentMon-derived FPS as authoritative. Prefer RTSS/MAHM FPS for visible FPS
and keep PresentMon for frame-pipeline details such as `CPUBusy` and `GPUBusy`
only when its cadence is believable for the capture.
Always check `present_modes` in the analyzer output:

- `Hardware: Independent Flip` can line up with RTSS/MAHM visible FPS.
- `Composed: Flip` can diverge from the visible FPS source. When it does,
  use RTSS/MAHM for visible FPS and treat PresentMon per-frame CPU/GPU busy
  timing as suspect unless another capture proves the cadence matches.
- `--no_track_display` is a diagnostic mode, not a visible-FPS replacement. It
  may show app/present submission cadence that is higher than the displayed
  frame rate.

Verified on 2026-06-13 with capture
`20260613-155840-fortnite-rtss-mahm-smoke`: RTSS produced 37 active Fortnite
FPS rows and MAHM produced 37 sensor rows, including CPU temperature. A
follow-up PresentMon debug check showed full PresentMon tracking at 119.78 FPS
in `Hardware: Independent Flip`, while the earlier composed-flip smoke capture
reported roughly 69 FPS against RTSS/MAHM's roughly 120 FPS.

## PresentMon Caveat

PresentMon is still valuable for CPU/GPU frame-pipeline diagnostics, especially
`CPUBusy` versus `GPUBusy`, but it is not always the same thing as Fortnite's
in-game FPS counter. In the 2026-06-13 Cup Zone Wars stress capture, PresentMon
reported one Fortnite swapchain with `PresentMode` mostly `Composed: Flip`,
while Johnny reported roughly 150 FPS in the Fortnite graph. Treat that
mismatch as a presentation-path validation problem, not as proof that the game
was actually running near 60 FPS.

In the 2026-06-13 real-round thermal check, PresentMon again stayed in
`Composed: Flip` and reported roughly 27 FPS while RTSS/MAHM reported roughly
194 FPS. For captures like that, the analyzer suppresses PresentMon CPU/GPU
busy bottleneck classification and relies on RTSS/MAHM, Windows counters,
thread samples, and NVIDIA SMI instead.

When this mismatch appears:

- record the user's in-game FPS observation in `docs/fortnite-performance-investigation.md`
- prefer non-FPS PresentMon data only as supporting evidence
- compare against RTSS/MAHM FPS when those shared-memory rows are present
- keep using markers so load, lobby, fight, and exit windows can be separated

If the user forgets to mark the end of a match/session and Fortnite later sits
in lobby/sleep mode, check the analyzer's `visible_sustained_120_cap_tail`
section. It identifies the first sustained 115-125 FPS tail where the following
five minutes stay below 130 FPS, then summarizes the pre-tail gameplay window
and the 120 FPS tail separately.

## CPU Upgrade Baseline

As of 2026-06-13, the installed CPU is verified as a Ryzen 7 5800X3D even though Johnny ordered a 5700X3D. Use the same wrapper flow to capture clean Fortnite baselines with labels that make the CPU state obvious, for example:

```bash
bin/windows-gaming-benchmark start --label fortnite-5800x3d-baseline
```

Before comparing results, record the verified CPU model, BIOS version, chipset driver version, temperatures, OBS state, render mode, map/match type, and whether Performance Mode was active. Compare against the saved 2026-05-23 Ryzen 9 3900X captures in `docs/fortnite-performance-investigation.md` before re-ranking remaining tweaks.

## Notes

- Use markers aggressively. Marker names are cheap and make later analysis much cleaner.
- Windows-side `Analyze` can be slow on large PresentMon CSVs. Prefer fetching and running `scripts/gaming/analyze-gaming-capture.py` locally.
- If the wrapper reports `SSH port 22 is not reachable`, fix Windows SSH reachability before treating status/fetch results as current.

## SSH Recovery

`lj-gaming-pc` is managed through normal OpenSSH on port 22. Tailscale can show the PC as online while OpenSSH is still stopped or blocked.

Do not restrict Windows OpenSSH with an active `ListenAddress 100.x.x.x` line in `C:\ProgramData\ssh\sshd_config`. On 2026-05-23, `sshd` repeatedly terminated during boot because the config was pinned to `ListenAddress 100.78.248.44` before Tailscale had finished bringing up that address. The managed `windows-ssh` tag disables active `ListenAddress` lines, validates `sshd_config`, keeps the service on delayed-auto with recovery actions, and normalizes the inbound firewall rule.

Fast local recovery from an elevated PowerShell on the gaming PC:

```powershell
Set-Service sshd -StartupType Automatic
Start-Service sshd
```

Then verify from the controller:

```bash
bin/windows-gaming-benchmark status
```

`playbooks/windows/windows-gaming-tuning.yml` also manages a startup/logon scheduled task named `\Johnny\Johnny Ensure OpenSSH Server` to nudge `sshd` back on after boot or login. Apply that playbook after SSH is reachable.

There is also a best-effort bootstrap self-heal in `windows-performance-run-hidden.vbs`: when the existing Performance Mode watcher task starts at logon, the runner attempts to set `sshd` to automatic and start it before launching the watcher. This exists specifically to recover controller access when OpenSSH is down before Ansible can apply the managed scheduled task.
