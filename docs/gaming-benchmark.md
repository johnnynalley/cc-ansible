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

Mark a moment during the run:

```bash
bin/windows-gaming-benchmark mark --marker match-start
bin/windows-gaming-benchmark mark --marker stutter
bin/windows-gaming-benchmark mark --marker match-end
```

Stop and fetch the capture archive for local analysis:

```bash
bin/windows-gaming-benchmark stop --fetch --dest /tmp
```

Fetch the latest capture without stopping anything:

```bash
bin/windows-gaming-benchmark fetch --dest /tmp
```

Fetch a specific Windows capture directory:

```bash
bin/windows-gaming-benchmark fetch --capture-dir 'C:\Users\jn\AppData\Local\WindowsGamingBenchmark\Captures\20260523-005536-fortnite-match-highres-off-lobby-to-game' --dest /tmp
```

Analyze after unzipping locally:

```bash
python3 scripts/gaming/analyze-gaming-capture.py /tmp/fortnite-match-highres-off-lobby-to-game
```

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
- `obs-profile.csv`
- `preflight.csv`

## Telemetry Sources

The benchmark harness is not supposed to rely on PresentMon as the only signal.
It can collect:

- PresentMon frame timing: `FrameTime`, `CPUBusy`, `CPUWait`, `GPUTime`, `GPUBusy`, `GPUWait`, display latency, present mode, and runtime.
- Windows system counters: CPU total/max utility, CPU DPC/interrupt time, CPU max frequency, memory pressure, disk latency/queue, network throughput, and GPU engine counters when enabled.
- NVIDIA SMI: NVIDIA GPU utilization, memory utilization, graphics/memory clocks, power, temperature, VRAM use, and PCIe link state.
- RTSS shared memory: RTSS FPS and frame-time windows when enabled.
- MSI Afterburner / MAHM shared memory: OSD FPS/frame time plus hardware-monitoring values such as CPU/GPU clocks, temperatures, power, and usage when enabled.
- Process/thread sampling: watched-process CPU/memory, top process deltas, target process hot-thread samples, process inventory, OBS profile snapshot, markers, and preflight warnings.

On `lj-gaming-pc`, the current inventory intentionally enables PresentMon and NVIDIA SMI but disables RTSS and MAHM capture:

```yaml
windows_gaming_benchmark_presentmon_enabled: true
windows_gaming_benchmark_pmdp_enabled: false
windows_gaming_benchmark_rtss_enabled: false
windows_gaming_benchmark_mahm_enabled: false
windows_gaming_benchmark_nvidia_smi_enabled: true
```

That means a capture can still have GPU sensor data from NVIDIA SMI and CPU/system data from Windows counters, but it will not have RTSS/Afterburner visible-FPS or CPU-temperature rows. If PresentMon's FPS disagrees with the in-game FPS graph, do not treat PresentMon-derived FPS as authoritative until RTSS/MAHM or another visible-FPS source is enabled for the same test.

## PresentMon Caveat

PresentMon is still valuable for CPU/GPU frame-pipeline diagnostics, especially
`CPUBusy` versus `GPUBusy`, but it is not the same thing as Fortnite's in-game
FPS counter. In the 2026-06-13 Cup Zone Wars stress capture, PresentMon reported
one Fortnite swapchain with `PresentMode` mostly `Composed: Flip`, while Johnny
reported roughly 150 FPS in the Fortnite graph. Treat that mismatch as a harness
validation problem, not as proof that the game was actually running near 60 FPS.

When this mismatch appears:

- record the user's in-game FPS observation in `docs/fortnite-performance-investigation.md`
- prefer non-FPS PresentMon data only as supporting evidence
- enable or capture a second FPS source for the next run, such as RTSS shared memory, Afterburner/MAHM logging, or another reliable visible-FPS counter
- keep using markers so load, lobby, fight, and exit windows can be separated

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
