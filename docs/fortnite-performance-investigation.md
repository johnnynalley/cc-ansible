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

> Updated 2026-05-24 after Astra/Vega/Antares review. Treat this as a benchmark queue, not applied wins. The goal is to preserve modern-Fortnite-valid paths for holding as close to 200 FPS as possible on the current Ryzen 9 3900X system while waiting on a possible AM4 X3D upgrade.

1. OBS capture-pipeline A/B, before more BIOS work:
   - the biggest measured delta is non-OBS gameplay around 151 FPS vs OBS recording around 99-102 FPS
   - OBS process CPU was only about 4%, so the likely overhead is capture hook / compositor / preview / scene path rather than x264-style CPU encoding
   - first tests: Game Capture vs Display Capture vs Window Capture, then preview enabled vs disabled
   - then test stripped scene vs normal scene, overlays/browser sources disabled, OBS admin vs normal, OBS priority normal vs above-normal, and NVENC options
2. VBS/HVCI diagnostic A/B if Johnny approves the reversible security tradeoff:
   - VBS/HVCI is still a plausible Windows 11 tax on Zen 2 CPU-bound gaming
   - document current `msinfo32` / Core Isolation state before changing anything
   - if disabled for a test, reboot, run the same capture, and re-enable if there is no meaningful win
3. Render-mode sanity checks, not a likely FPS unlock:
   - do not expect DX12 to beat Performance Mode for raw average FPS on this CPU-limited setup
   - DX11 or any legacy DX11 Performance path may be worth identifying only if it is still exposed/supported, but it is not expected to beat current Performance Mode for CPU frame time
   - keep render-mode tests as frame-pacing/stutter/OBS-interaction sanity checks, not likely 200 FPS paths
   - compare current Performance Mode against DX12 all-low/competitive only after multiple shader warm-up matches; if DX11 is still selectable, benchmark it separately
   - compare average FPS, 1%/0.1% lows, CPU Busy, GPU Busy, stutter markers, and input feel
4. HAGS A/B if the user approves another reboot-level graphics test:
   - current managed state disables HAGS with `HwSchMode=1`
   - Epic's FPS guide recommends enabling HAGS when available
   - test HAGS with MPO still disabled first, and do not combine with render-mode changes in the same run
5. NVIDIA driver/profile sanity:
   - record the current NVIDIA driver version in this document before more A/B tests
   - if captures regress after a driver update, consider a clean install or known-stable driver branch as a measured test
   - this is a sanity check, not a magic tweak
6. Fortnite priority A/B remains low-risk but is now behind OBS/VBS/render-mode/HAGS tests:
   - run the same Fortnite + OBS recording/streaming workload with `--priority High`
   - compare against the 2026-05-23 OBS recording captures below
   - do not bake priority into Performance Mode unless it wins clearly
7. BIOS-side Ryzen/RAM tuning:
   - PBO/scalar/AutoOC and memory/FCLK/timing work are more likely to move the single-thread ceiling than more background-app cleanup
   - current DDR4-3200/FCLK1600 CL16 is already sane, so memory work is latency refinement, not fixing a broken config
   - any BIOS/memory change needs stability testing before calling it a Fortnite win
8. Affinity/CCD/CCX tests are not the immediate recommendation. The current saved benchmark state files all show `AffinityPreset: none`; if affinity was tried earlier, there is no durable capture artifact in the harness. Only revisit with a controlled, documented A/B if Johnny explicitly wants that path or telemetry shows cross-CCD/thread-migration cost.

## Upgrade Watch

Johnny's current plan is to hold the Ryzen 9 3900X until a possible AM4 X3D upgrade is available and affordable. Rumors as of 2026-05-24 say AMD may re-release the Ryzen 7 5800X3D as an AM4 10th Anniversary Edition around Q2 2026, with early retailer sightings around the low-$300 range. Treat this as a rumor until AMD or retail availability is confirmed.

If the anniversary 5800X3D is unavailable, scalped, or overpriced, the practical fallback is a Ryzen 7 5700X3D or used 5800X3D. For Fortnite and other cache-sensitive games, 5700X3D/5800X3D are much better upgrade targets from a 3900X than a 5900X. A 5900X adds cores but does not solve the cache/game-thread limitation that the captures are pointing at.

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

### 1. OBS Capture Pipeline A/B Test

Reason: the captures show the largest practical gap when OBS is involved: non-OBS gameplay averaged about 151 FPS, while OBS recording captures averaged about 99-102 FPS. OBS process CPU was only about 4%, so the likely overhead is Game Capture hook / compositor / preview / scene path rather than the encoder process itself.

First tests:

- Game Capture vs Display Capture vs Window Capture.
- OBS preview enabled vs disabled.
- Normal scene vs stripped scene with overlays/browser sources disabled.
- OBS normal vs admin.
- OBS process priority normal vs above-normal.

Use the same Fortnite route/mode and markers as the 2026-05-23 OBS captures. Do not combine with render-mode, HAGS, VBS, or BIOS changes in the same run.

Success criteria:

- CPU Busy moves materially back toward the non-OBS 6.31 ms result.
- Average FPS improves meaningfully against the OBS recording captures.
- p99/p99.9 frame time and frames over 16.67/25/33.33 ms do not regress.
- OBS capture, recording/stream output, and audio remain stable.

### 2. VBS/HVCI A/B Test

Reason: VBS and HVCI are enabled and running. Disabling them can improve some CPU-bound gaming workloads, especially on Windows 11 systems where virtualization-based security is active. This is a reversible diagnostic test, not a default permanent recommendation.

Cost:

- Security tradeoff while disabled
- Reboot required
- User approval required before applying

Test:

1. Record the current VBS/Core Isolation state from `msinfo32` and Windows Security.
2. Baseline benchmark with current state.
3. Disable Memory Integrity / HVCI and VBS using the managed security-performance path.
4. Reboot.
5. Repeat the same Fortnite benchmark.
6. Re-enable if the result is not meaningful enough to justify the security tradeoff.

### 3. Render Mode A/B Test

Reason: modern Fortnite is not guaranteed to have best frame pacing on Performance Mode, but Johnny is right that DX12 is unlikely to increase raw average FPS on a CPU-limited Ryzen 9 3900X setup. DX11 or a legacy DX11 Performance path, if still selectable, may have lower graphics-feature overhead but is not expected to beat current Performance Mode's stripped-down path for raw CPU frame time. Keep render-mode testing as a sanity check for 1% lows, stutter, and OBS/capture interaction, not as a likely path to 200 FPS. Shader compilation can make first-run DX12 results misleading.

Test:

1. Current Performance Mode baseline.
2. Identify the currently exposed rendering options in Fortnite settings and/or GameUserSettings.ini.
3. If DX11 is still selectable, benchmark it separately with the same route/mode and markers.
4. Benchmark DX12 all-low/competitive with Nanite/Lumen/ray tracing off only after multiple shader warm-up matches.
5. Compare average FPS, 1% lows, 0.1% lows, CPU Busy, GPU Busy, stutter markers, and subjective input feel.

### 4. HAGS A/B Test

Reason: Epic's current FPS troubleshooting page recommends enabling Hardware-accelerated GPU scheduling when available, but our current managed state disables it.

Cost:

- Registry change
- Reboot required
- Needs A/B benchmark before and after

Test:

1. Baseline benchmark with current `HwSchMode=1`.
2. Set `HwSchMode=2` while keeping MPO disabled.
3. Reboot.
4. Repeat the same Fortnite benchmark.
5. Compare average FPS, 1% lows, 0.1% lows, PresentMon CPU busy/wait/GPU busy, and stutter markers.

### 5. NVIDIA Driver/Profile Sanity

Reason: Fortnite can regress on specific driver branches, and the current driver version is not yet recorded in this document.

Test:

1. Record current NVIDIA driver version before further A/B testing.
2. If results regress after a driver update, consider a clean install or known-stable branch as a measured test.
3. Do not treat this as a magic optimization; it is hygiene and rollback context.

### 6. Priority A/B Test

Reason: the captures show a hot Fortnite frame thread while OBS and background audio processes are modest. Raising Fortnite's process priority is low-risk and reversible, but it is now lower priority than the OBS capture-pipeline, VBS, render-mode, and HAGS tests.

Test:

```bash
bin/windows-gaming-benchmark start --label fortnite-obs-priority-high --priority High
```

Use the same Fortnite + OBS recording or streaming workload as the 2026-05-23 OBS captures. Do not change affinity in the same test.

Success criteria:

- Average FPS improves meaningfully against the OBS recording captures.
- p99/p99.9 frame time and frames over 16.67/25/33.33 ms do not regress.
- OBS remains stable and audio/capture remain clean.

### 7. Affinity A/B Test

Reason: Ryzen 9 3900X is a multi-CCD Zen 2 CPU. Fortnite may behave better when its heavy threads stay within one CCD/CCX instead of bouncing across CCDs, but this remains low-confidence without telemetry showing migration cost.

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
- Do not re-suggest affinity as the next obvious move unless the user explicitly wants a controlled affinity A/B or telemetry points to cross-CCD thread migration cost.

### 8. BIOS-Side Ryzen / RAM Tuning

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

Do not prioritize the following without a specific benchmark hypothesis:

- `-USEALLAVAILABLECORES`, `-threads`, or similar launch arguments. Fortnite already uses multiple threads where it can; the measured problem is frame-critical CPU work, not that Windows is hiding cores.
- `msconfig` processor-count tweaks. Leaving this unset is the correct Windows default.
- HPET/platform-clock/dynamic-tick timer hacks. BCDEdit already shows no obvious timer pollution, and these tweaks are usually stale cargo cult.
- Manual Fortnite pak deletion. High-resolution textures were removed through Epic Games Launcher options and verified by disk state; do not hand-delete pak files.
- ReBAR as a major fix. It may be a small free tweak, but the current bottleneck is CPU-frame-time, not GPU memory transfer.

MMCSS `Games` task currently shows:

- `Scheduling Category=Medium`
- `Priority=2`
- `GPU Priority=8`
- `SFIO Priority=Normal`

Microsoft documents `GPU Priority` and `SFIO Priority` as not used, and `High` scheduling category treats `Priority` as `2`. Do not prioritize this over the current documented test queue.

## Sources

- Epic Fortnite FPS troubleshooting recommends HAGS, high-performance GPU preference, Delivery Optimization off, High Performance power, Game Mode on, and Xbox Game Bar off: https://www.epicgames.com/help/en-US/fortnite-battle-royale-c-202300000001636/technical-support-c-202300000001719/improve-low-fps-in-fortnite-on-pc-a202300000014026
- Epic Performance Mode article documents removing high-resolution textures through Epic Launcher options: https://www.epicgames.com/help/en-US/c-Category_Fortnite/c-Fortnite_TechnicalSupport/how-do-i-change-graphic-performance-to-increase-frame-rate-fps-a000089646
- Epic DX12 stutter support documents DirectX 12 shader-cache stutter and below-expected performance troubleshooting: https://www.epicgames.com/help/c-202300000001636/c-202300000001719/fortnite-stutters-heavily-and-has-below-expected-performance-on-directx-12-a202300000018050
- NVIDIA's OBS broadcasting guide documents NVENC as the preferred NVIDIA GPU encoding path for OBS: https://www.nvidia.com/en-us/geforce/guides/broadcasting-guide/
- OBS forum guidance and release notes discuss NVENC performance behavior and preview/capture overhead: https://obsproject.com/forum/threads/nvenc-performance-improvements-release-candidate.98950/
- Tom's Hardware measured Windows 11 VBS/HVCI gaming overhead, including Ryzen 3000-class results: https://www.tomshardware.com/news/windows-11-gaming-benchmarks-performance-vbs-hvci-security
- AMD Ryzen Master docs describe PBO, PBO Advanced, and Curve Optimizer behavior and limits: https://docs.amd.com/r/en-US/68886-ryzen-master-user-guide/CPU
- AMD Ryzen Master product page notes overclocking/PBO warranty caveats: https://www.amd.com/en/products/software/ryzen-master.html
- Microsoft MMCSS docs: https://learn.microsoft.com/en-us/windows/win32/procthread/multimedia-class-scheduler-service
- TechPowerUp reports the rumored Ryzen 7 5800X3D AM4 10th Anniversary Edition; treat as rumor until AMD/retail confirmation: https://www.techpowerup.com/348272/amd-to-re-launch-ryzen-7-5800x3d-as-am4-10th-anniversary-edition
- Tom's Hardware reports early retailer sightings of the rumored Ryzen 7 5800X3D AM4 10th Anniversary Edition around $310: https://www.tomshardware.com/pc-components/cpus/ryzen-7-5800x3d-am4-10th-anniversary-edition-surfaces-online-for-usd310-return-of-iconic-gaming-cpu-for-budget-builders-seems-imminent
