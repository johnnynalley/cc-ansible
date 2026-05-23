# Fortnite Performance Investigation

> Status: investigation and test planning. Do not treat untested candidates as applied wins.

## Working Rules For This Investigation

- Update this document after every meaningful benchmark, setting change, driver/chipset/BIOS change, or conclusion.
- Before suggesting a tweak or A/B test, check this document and saved benchmark state first.
- Record capture label, Windows capture path, local analysis path/archive, test conditions, key metrics, interpretation, and the next action.
- Do not re-suggest a test as if it is new when it is already listed here. If prior evidence is missing, say that the idea lacks a durable benchmark artifact rather than treating it as untested or proven.
- Distinguish between:
  - applied and verified changes
  - tested ideas with results
  - untested candidates
  - rejected/deprioritized ideas

## Current Hardware Snapshot

- Gaming PC: `lj-gaming-pc`
- CPU: AMD Ryzen 9 3900X, 12 cores / 24 threads
- Motherboard: MSI MPG B550 Gaming Plus
- BIOS: `1.L1`
- RAM: 32 GB, 4x8 GB Corsair `CMW16GX4M2C3200C16`
- Memory clock: 1600 MHz, DDR4-3200 effective
- Fabric clock: 1600 MHz
- GPU: NVIDIA GeForce RTX 3070
- Display mode observed from Windows: 1920x1080 at 200 Hz

## Already Applied / Verified

- AMD chipset software installed: `8.05.04.516`
- Active Windows power plan: AMD Ryzen High Performance
- Processor power-plan internals are performance-biased:
  - min/max processor state: 100% AC
  - boost mode: aggressive AMD value
  - EPP: 0
  - core parking min/max: 100%
- Fortnite Defender path exclusion is present: `Z:\Epic Games\Fortnite`
- Game DVR capture and historical capture are disabled.
- Hardware-accelerated GPU scheduling is currently disabled (`HwSchMode=1`).
- Multiplane overlay is currently disabled (`OverlayTestMode=5`).
- NIC power-saving features and interrupt moderation are disabled by the gaming tuning playbook.
- Performance Mode closes/stops known background clients and services while Fortnite/OBS triggers are active.
- BCDEdit does not show obvious HPET/platform-clock/dynamic-tick tweak pollution.
- High-resolution textures were turned off in Epic Games Launcher on 2026-05-22 and verified by disk state.

## Ryzen Findings

Ryzen Master full UI is not installed, but the Ryzen Master SDK CLI is present.

Read-only SDK telemetry showed:

- PBO supported: yes
- Current OC mode: PBO Mode
- Board limits: PPT 1000 W, EDC 220 A, TDC 140 A
- Fused limits: PPT 142 W, EDC 140 A, TDC 95 A
- PBO scalar: disabled
- Curve Optimizer: unsupported through the SDK on this CPU
- SMT: enabled
- Core parking: 0 cores parked
- RAM timings observed: 3200 CL16-18-18-36, GearDown enabled

Implication: the machine is not stuck in stock power-plan behavior. Ryzen Master is useful for telemetry here, but the newer Curve Optimizer style of tuning is probably not available for the 3900X. Any meaningful Ryzen tuning is likely BIOS-side PBO/scalar/AutoOC and memory/FCLK tuning.

## Fortnite Install Findings

Fortnite is installed at:

```text
Z:\Epic Games\Fortnite
```

Before disabling high-resolution textures, the Epic manifest install tags were empty, the Paks directory contained many large `optional` chunks, and the Pak total was roughly 97.4 GB.

After disabling high-resolution textures through Epic Games Launcher options on 2026-05-22:

- Pak file count dropped from 315 to 191.
- Pak total dropped from 97.4 GB to 64.5 GB.
- The `optional`/texture-named pak list became empty.
- Net reduction was roughly 33 GB.

Do not manually delete paks. Use Epic Games Launcher options for this setting.

## Current Best Candidates

1. Fortnite priority A/B, with no affinity change:
   - run the same Fortnite + OBS recording/streaming workload with `--priority High`
   - compare against the 2026-05-23 OBS recording captures below
   - do not bake priority into Performance Mode unless it wins clearly
2. HAGS A/B if the user approves another reboot-level graphics test:
   - current managed state disables HAGS with `HwSchMode=1`
   - Epic's FPS guide recommends enabling HAGS when available
3. BIOS-side Ryzen/RAM tuning:
   - PBO/scalar/AutoOC and memory/FCLK/timing work are more likely to move the single-thread ceiling than more background-app cleanup
4. VBS/HVCI remains a possible security-performance tradeoff, but the user declined it for now.
5. Affinity/CCD/CCX tests are not the immediate next recommendation. The current saved benchmark state files all show `AffinityPreset: none`; if affinity was tried earlier, there is no durable capture artifact in the harness. Only revisit with a controlled, documented A/B if the user explicitly wants that path.

## 2026-05-23 Match Capture: High-Res Textures Off

Capture:

```text
C:\Users\jn\AppData\Local\WindowsGamingBenchmark\Captures\20260523-005536-fortnite-match-highres-off-lobby-to-game
```

Local archive analyzed from:

```text
/tmp/fortnite-match-highres-off-lobby-to-game
```

Markers:

- `start`: 2026-05-23 00:55:36 -05:00
- `target-started-6492`: 2026-05-23 00:55:42 -05:00
- `lobby-120fps-cap`: 2026-05-23 00:55:45 -05:00
- `match-finished`: 2026-05-23 01:13:50 -05:00
- `stop-requested`: 2026-05-23 01:13:53 -05:00

Trimmed gameplay window, excluding the first 60 seconds and last 30 seconds:

- Average FPS from PresentMon frame time: 151.0
- 1% low: 84.7 FPS
- 0.1% low: 53.8 FPS
- Average frame time: 6.62 ms
- p99 frame time: 11.81 ms
- p99.9 frame time: 18.60 ms
- Frames over 16.67 ms: 221
- Frames over 25 ms: 57
- Frames over 33.33 ms: 22
- Frames over 50 ms: 5
- Average CPU busy: 6.31 ms
- Average GPU busy: 3.64 ms
- Average GPU wait: 2.88 ms

All-window numbers are slightly worse because the end-of-match/stop window contains a large transition spike:

- Average FPS: 147.1
- 1% low: 82.2 FPS
- 0.1% low: 46.9 FPS
- Worst frame: 5432.86 ms

System observations:

- CPU total utility averaged 50.0%, but p95 max logical CPU utility was 91.9% and p99 was 95.7%.
- Fortnite had hot target-thread samples at roughly 97-104% of one full logical processor.
- NVIDIA GPU utilization averaged 56.4%, p95 was 65.5%, and VRAM peaked at 2290 MB.
- GPU clocks stayed high at about 1995 MHz average, with max GPU temperature 55 C.
- Available memory stayed healthy, with a minimum of 17.6 GB available.
- Disk latency was not a bottleneck.

Interpretation:

Fortnite is CPU-frame-time limited in this capture, not GPU limited. The 200 FPS frame budget is 5.0 ms, while trimmed gameplay averaged 6.31 ms CPU busy and only 3.64 ms GPU busy. That explains why total CPU/GPU usage can look low while the game still fails to hold 200 FPS: one or a few frame-critical CPU threads are close to saturated.

OBS was present but modest in this run. The OBS profile snapshot showed replay buffer configured, but the user later clarified replay buffer is off for streaming; treat this as a recording-profile observation, not a streaming-path conclusion.

## 2026-05-23 OBS Recording Captures

These were run after OBS finally captured Fortnite again, while the user was recording locally to work on audio before streaming.

Capture 1:

```text
C:\Users\jn\AppData\Local\WindowsGamingBenchmark\Captures\20260523-165938-fortnite-obs-capture-working
/tmp/LJ-GAMING-PC-20260523-165938-fortnite-obs-capture-working
/tmp/LJ-GAMING-PC-20260523-165938-fortnite-obs-capture-working.zip
```

Conditions:

- Fortnite running and OBS successfully capturing.
- OBS recording was active for at least part of the run.
- Benchmark state: `AffinityPreset=none`, `Priority=none`, `PowerPlanPreset=current`.
- No preflight warnings and no process-inventory pollution warnings.

Key metrics:

- PresentMon rows: 79,770
- Total duration: about 763 seconds
- All-window average FPS: 104.7
- Trimmed gameplay average FPS:
  - first 60 seconds / last 30 seconds removed: 101.7
  - first 60 seconds / last 90 seconds removed: 100.6
  - first 120 seconds / last 120 seconds removed: 98.8
- Trimmed p99 frame time:
  - 23.86 ms for 60/30 trim
  - 24.17 ms for 60/90 trim
  - 24.58 ms for 120/120 trim
- Trimmed average CPU busy: roughly 9.55-9.85 ms
- Trimmed average GPU busy: roughly 3.52-3.63 ms
- GPU busy never crossed 16.67 ms in the trimmed windows.
- p95 max logical CPU utility: 95.3%
- p95 context switches: about 155,430/sec
- Fortnite hot target-thread samples reached about 95.7% of one logical processor.
- OBS max process CPU total was about 4.0%.
- SonoBus, Sonar, audiodg, Discord, and Defender were not dominant CPU users.

Interpretation:

This recording run was still CPU-frame-time dominant. GPU busy time was far below the 5 ms / 200 FPS frame budget most of the time, while CPU busy was roughly double that budget. OBS was not the main bottleneck in this capture.

Capture 2:

```text
C:\Users\jn\AppData\Local\WindowsGamingBenchmark\Captures\20260523-171424-fortnite-obs-recording-audio-test-match2
/tmp/LJ-GAMING-PC-20260523-171424-fortnite-obs-recording-audio-test-match2
/tmp/LJ-GAMING-PC-20260523-171424-fortnite-obs-recording-audio-test-match2.zip
```

Conditions:

- Fortnite running, OBS capturing and recording.
- User was testing audio setup before streaming.
- Benchmark state: `AffinityPreset=none`, `Priority=none`, `PowerPlanPreset=current`.
- No preflight warnings and no process-inventory pollution warnings.

Key metrics:

- PresentMon rows: 106,823
- Total duration: about 1097 seconds
- All-window average FPS: 97.4
- Trimmed gameplay average FPS:
  - first 60 seconds / last 30 seconds removed: 98.2
  - first 60 seconds / last 90 seconds removed: 98.8
  - first 120 seconds / last 120 seconds removed: 98.8
- Trimmed p99 frame time:
  - 22.09 ms for 60/30 trim
  - 22.02 ms for 60/90 trim
  - 22.00 ms for 120/120 trim
- Trimmed average CPU busy: roughly 9.80-9.86 ms
- Trimmed average GPU busy: roughly 4.42 ms
- p95 max logical CPU utility: 93.1%
- p95 context switches: about 122,490/sec
- Fortnite hot target-thread samples reached about 97.5% of one logical processor.
- OBS max process CPU total was about 4.1%.
- Memory Compression briefly showed CPU activity but remained below the configured warning threshold; available memory stayed healthy.

Interpretation:

This second OBS recording run confirms the same bottleneck: Fortnite's frame-critical CPU work is the limiter. GPU busy was still around a 226 FPS-equivalent average in trimmed gameplay, while CPU busy was around a 102 FPS-equivalent average. OBS/audio overhead was visible but not large enough to explain the missing path to 200 FPS.

OBS profile observation:

- The captured OBS profile had `Output.Mode=Simple`.
- Recording format was `hybrid_mp4`.
- Stream encoder was `nvenc`.
- Recording encoder was `nvenc_hevc`.
- Replay Buffer keys appeared enabled in the captured profile, but the user clarified Replay Buffer is off for streaming. Do not keep recommending Replay Buffer as a streaming fix unless a live stream capture proves it is active.

Current conclusion from all 2026-05-23 captures:

The observed 100-150 FPS range is not caused by GPU saturation, disk latency, RAM pressure, OBS CPU load, or obvious background app pollution. The durable pattern is CPU-frame-time dominance with one hot Fortnite thread/logical processor near saturation.

### 1. Priority A/B Test

Reason: the captures show a hot Fortnite frame thread while OBS and background audio processes are modest. Raising Fortnite's process priority is low-risk and reversible.

Test:

```bash
bin/windows-gaming-benchmark start --label fortnite-obs-priority-high --priority High
```

Use the same Fortnite + OBS recording or streaming workload as the 2026-05-23 OBS captures. Do not change affinity in the same test.

Success criteria:

- Average FPS improves meaningfully against the OBS recording captures.
- p99/p99.9 frame time and frames over 16.67/25/33.33 ms do not regress.
- OBS remains stable and audio/capture remain clean.

### 2. HAGS A/B Test

Reason: Epic's current FPS troubleshooting page recommends enabling Hardware-accelerated GPU scheduling when available, but our current managed state disables it.

Cost:

- Registry change
- Reboot required
- Needs A/B benchmark before and after

Test:

1. Baseline benchmark with current `HwSchMode=1`.
2. Set `HwSchMode=2`.
3. Reboot.
4. Repeat the same Fortnite benchmark.
5. Compare average FPS, 1% lows, 0.1% lows, PresentMon CPU busy/wait/GPU busy, and stutter markers.

### 3. Affinity A/B Test

Reason: Ryzen 9 3900X is a multi-CCD Zen 2 CPU. Fortnite may behave better when its heavy threads stay within one CCD/CCX instead of bouncing across CCDs.

Existing benchmark presets:

- `ccd0`
- `ccd1`
- `ccx0`
- `ccx1`
- `ccx2`
- `ccx3`
- `all`
- `none`

Test:

Run the same Fortnite scenario using the existing benchmark harness with affinity presets. Do not bake affinity into Performance Mode until one preset wins clearly.

Current evidence state:

- Saved benchmark state files currently present on the gaming PC all show `AffinityPreset=none`.
- If affinity was tried earlier, it was not preserved as a durable capture in the current harness.
- Do not re-suggest affinity as the next obvious move unless the user explicitly wants a controlled affinity A/B.

### 4. VBS/HVCI A/B Test

Reason: VBS and HVCI are enabled and running. Disabling them can improve some CPU-bound gaming workloads.

Cost:

- Security tradeoff
- Reboot required
- User has previously been hesitant, so do not apply without explicit approval.

### 5. BIOS-Side Ryzen / RAM Tuning

Potential:

- PBO scalar / AutoOC tuning
- memory/FCLK tuning toward 3600/1800 if the four-DIMM kit and CPU memory controller tolerate it
- tighter DDR4 timings if stable

Risk:

- BIOS-only work
- boot/stability risk
- requires manual recovery path
- must be stability-tested before calling it a win

## Lower-Confidence Tweaks

MMCSS `Games` task currently shows:

- `Scheduling Category=Medium`
- `Priority=2`
- `GPU Priority=8`
- `SFIO Priority=Normal`

Microsoft documents `GPU Priority` and `SFIO Priority` as not used, and `High` scheduling category treats `Priority` as `2`. Do not prioritize this over the current documented test queue.

## Sources

- Epic Fortnite FPS troubleshooting recommends HAGS, high-performance GPU preference, Delivery Optimization off, High Performance power, Game Mode on, and Xbox Game Bar off: https://www.epicgames.com/help/en-US/fortnite-battle-royale-c-202300000001636/technical-support-c-202300000001719/improve-low-fps-in-fortnite-on-pc-a202300000014026
- Epic Performance Mode article documents removing high-resolution textures through Epic Launcher options: https://www.epicgames.com/help/en-US/c-Category_Fortnite/c-Fortnite_TechnicalSupport/how-do-i-change-graphic-performance-to-increase-frame-rate-fps-a000089646
- AMD Ryzen Master docs describe PBO, PBO Advanced, and Curve Optimizer behavior and limits: https://docs.amd.com/r/en-US/68886-ryzen-master-user-guide/CPU
- AMD Ryzen Master product page notes overclocking/PBO warranty caveats: https://www.amd.com/en/products/software/ryzen-master.html
- Microsoft MMCSS docs: https://learn.microsoft.com/en-us/windows/win32/procthread/multimedia-class-scheduler-service
