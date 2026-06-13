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
- CPU currently verified by Windows snapshot 2026-06-12: AMD Ryzen 7 5800X3D, 8 cores / 16 threads
  - Johnny reported buying a 5700X3D, but Windows reports `AMD Ryzen 7 5800X3D 8-Core Processor` through both WMI and the CPU registry brand string.
  - Supporting identity data: `AuthenticAMD`, Family 25 Model 33 Stepping 2, 96 MB L3, WMI max clock 3401 MHz.
  - Treat the installed CPU as a 5800X3D.
- Previous CPU: AMD Ryzen 9 3900X, 12 cores / 24 threads
- Motherboard: MSI MPG B550 Gaming Plus
- BIOS: `1.L1`
- RAM: 32 GB, 4x8 GB Corsair `CMW16GX4M2C3200C16`
- Memory clock previously verified: 1600 MHz, DDR4-3200 effective
- Memory clock after CPU swap snapshot 2026-06-12: initially reset to DDR4-2133 effective.
- A-XMP restored 2026-06-12; Windows now reports all four DIMMs at 3200 MT/s configured speed.
- Fabric clock verified after A-XMP restore: 1600 MHz.
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

Current 5800X3D read-only SDK telemetry showed:

- Current OC mode: Default Mode
- Fused limits: PPT 142 W, EDC 140 A, TDC 95 A
- cHTC thermal-control limit: 90 C
- CPU overclocking from BIOS allowed: yes
- Memory/FCLK: DDR4-3200, MCLK 1600 MHz, FCLK 1600 MHz
- RAM timings observed: 3200 CL16-18-18-36, GearDown enabled
- In Fortnite, current clocks stayed roughly 4.2-4.45 GHz on boosted cores during thermal checks

Implication: Ryzen Master SDK is useful for current telemetry, but the old 3900X-specific PBO/Curve Optimizer interpretation is retired. Treat any X3D tuning as a new 5800X3D-specific BIOS/telemetry investigation, not a continuation of the 3900X tuning plan.

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

> Updated 2026-06-13 after the AM4 X3D CPU swap, A-XMP restore, and cooling-profile checks. Treat this as a benchmark queue, not applied wins. The short-term goal is to capture clean post-upgrade Fortnite data, then re-rank remaining tweaks based on the new CPU frame-time baseline.

1. Post-upgrade health baseline:
   - installed CPU is verified as a 5800X3D even though Johnny ordered a 5700X3D
   - record idle/load CPU temperature, effective clocks, power limits, cooling profile, and whether boost behavior is normal for the X3D CPU
   - then run a clean Fortnite Performance Mode capture without OBS before judging the upgrade
2. OBS capture-pipeline A/B, after the clean X3D baseline:
   - the biggest measured delta is non-OBS gameplay around 151 FPS vs OBS recording around 99-102 FPS
   - OBS process CPU was only about 4%, so the likely overhead is capture hook / compositor / preview / scene path rather than x264-style CPU encoding
   - first tests: Game Capture vs Display Capture vs Window Capture, then preview enabled vs disabled
   - then test stripped scene vs normal scene, overlays/browser sources disabled, OBS admin vs normal, OBS priority normal vs above-normal, and NVENC options
3. VBS/HVCI diagnostic A/B if Johnny approves the reversible security tradeoff:
   - VBS/HVCI can still tax CPU-bound Windows 11 gaming, but re-rank this after the 5800X3D baseline
   - after the X3D swap, do not test this until a clean post-upgrade baseline is recorded
   - document current `msinfo32` / Core Isolation state before changing anything
   - if disabled for a test, reboot, run the same capture, and re-enable if there is no meaningful win
4. Render-mode sanity checks, not a likely FPS unlock:
   - do not expect DX12 to beat Performance Mode for raw average FPS on this CPU-limited setup
   - DX11 or any legacy DX11 Performance path may be worth identifying only if it is still exposed/supported, but it is not expected to beat current Performance Mode for CPU frame time
   - keep render-mode tests as frame-pacing/stutter/OBS-interaction sanity checks, not likely 200 FPS paths
   - compare current Performance Mode against DX12 all-low/competitive only after multiple shader warm-up matches; if DX11 is still selectable, benchmark it separately
   - compare average FPS, 1%/0.1% lows, CPU Busy, GPU Busy, stutter markers, and input feel
5. HAGS A/B if the user approves another reboot-level graphics test:
   - current managed state disables HAGS with `HwSchMode=1`
   - Epic's FPS guide recommends enabling HAGS when available
   - test HAGS with MPO still disabled first, and do not combine with render-mode changes in the same run
6. NVIDIA driver/profile sanity:
   - record the current NVIDIA driver version in this document before more A/B tests
   - current snapshot reports NVIDIA driver `596.49`
   - if captures regress after a driver update, consider a clean install or known-stable driver branch as a measured test
   - this is a sanity check, not a magic tweak
7. Fortnite priority A/B remains low-risk but is now behind OBS/VBS/render-mode/HAGS tests:
   - run the same Fortnite + OBS recording/streaming workload with `--priority High`
   - compare against the 2026-05-23 OBS recording captures below
   - do not bake priority into Performance Mode unless it wins clearly
8. BIOS-side Ryzen/RAM tuning:
   - PBO/scalar/AutoOC and memory/FCLK/timing work are more likely to move the single-thread ceiling than more background-app cleanup
   - DDR4-3200 CL16 and FCLK1600 are restored after the CPU swap
   - any BIOS/memory change needs stability testing before calling it a Fortnite win
9. Affinity/CCD/CCX tests are not the immediate recommendation. The current saved benchmark state files all show `AffinityPreset: none`; if affinity was tried earlier, there is no durable capture artifact in the harness. Only revisit with a controlled, documented A/B if Johnny explicitly wants that path or telemetry shows cross-CCD/thread-migration cost.

## CPU Upgrade Status

Johnny ordered a Ryzen 7 5700X3D, but the installed CPU is verified as a Ryzen 7 5800X3D. The BIOS, Windows WMI, and `HKLM:\HARDWARE\DESCRIPTION\System\CentralProcessor\0` all report `AMD Ryzen 7 5800X3D 8-Core Processor`. Treat the 5800X3D as the installed and benchmark-relevant CPU.

Do not call the upgrade benchmarked yet. Before final performance conclusions:

- BIOS A-XMP was restored after the initial post-swap DDR4-2133 reading; Windows now reports the kit at DDR4-3200
- FCLK1600 and CPU thermal/clock spot checks are recorded below
- capture at least one clean post-install Fortnite baseline and archive it

## 2026-06-13 X3D Thermal Spot Check While Fortnite Was Running

Johnny saw roughly 83 C in his overlay while Fortnite was running. A read-only Ryzen Master SDK `GetPMTableData` check at 2026-06-13 15:14-15:20 -05:00 showed:

- CPU: Windows/Ryzen telemetry still reports `AMD Ryzen 7 5800X3D`
- AMD cHTC thermal-control limit: 90 C
- Current CPU temperature: 81.81 C
- PPT: 83.3 W current / 142 W limit
- EDC: 95.4 A current / 140 A limit
- TDC: 47.0 A current / 95 A limit
- Current core clocks: roughly 4.22-4.35 GHz
- Effective active-core clocks: roughly 1.97-4.01 GHz depending on core/load
- Memory clock: 1600 MHz, FCLK 1600 MHz, CL16-18-18-36, GearDown enabled

Interpretation: 82-83 C is warm but below the X3D thermal-control limit. It does not prove unsafe operation by itself, and clocks were still boosting over 4.2 GHz, but this should be improved or watched if Fortnite holds low-to-mid 80s for long sessions or approaches 88-90 C. Cooling mount/paste, fan curve, case airflow, dust, and a conservative X3D undervolt/curve-optimizer path are the next likely thermal levers; do not change them without a controlled before/after test.

Follow-up one-minute Ryzen telemetry sample while Fortnite was still active:

- Temperature samples: 84.30, 84.05, 80.50, 79.30, 80.09, 80.26 C
- PPT range: 65.5-88.0 W
- EDC range: 53.5-112.2 A
- Current clocks remained roughly 4.17-4.39 GHz on active boosted cores

Interpretation update: the CPU was not continuously climbing toward 90 C during this short sample. It spiked into the mid-80s, then settled around 79-80 C as load varied. That is still warm for a Kraken-cooled gaming load, but it looks more like 5800X3D heat density plus fan/pump behavior than an immediate cooling failure.

Later CAM check:

- Johnny reported NZXT CAM pump set to Performance and liquid temperature around 46 C while sitting in the Fortnite lobby.
- CAM was running when checked remotely.
- Ryzen telemetry at that moment: CPU temperature 78.95 C, PPT 85.1 W, EDC 102.5 A, TDC 48.4 A, CPU package power 61.0 W.
- NVIDIA telemetry at that moment: GPU temperature 45 C, GPU utilization 44%, GPU power 45.8 W, GPU fan 38%.

Interpretation update: the 46 C liquid temperature is the main cooling signal. With the GPU also around 45 C and not heavily loaded, this does not look like the radiator is simply being blasted by a hot GPU. If the liquid is already 46 C in the lobby, the next non-undervolt checks are radiator fan profile/RPM, whether the radiator fans are actually tied to the Kraken/CAM fan channel, radiator airflow direction, and whether the case/radiator path is recirculating warm air. Pump Performance alone is not enough if fan behavior is quiet or disconnected from the liquid curve.

Johnny then changed CAM's radiator fan temperature source from liquid to CPU, with the Performance fan curve effectively running all fans at 100%. Follow-up Ryzen telemetry while Fortnite was still active:

- Temperature samples: 68.37, 71.41, 67.75, 67.58, 77.82, 67.20 C
- PPT range: 62.3-76.7 W
- GPU stayed around 43-45 C

Interpretation update: using CPU temperature as the fan-curve source immediately helped. The earlier liquid-based curve was likely too slow or too quiet for the 5800X3D's fast CPU hotspot swings. Liquid temperature is usually the smoother AIO control source, but for this specific gaming workload and current CAM profile, CPU-sourced radiator fans are the better practical setting if noise is acceptable. A refined liquid-source curve could still work if it ramps aggressively by roughly 40-42 C liquid and reaches 100% by the mid-40s.

For Fortnite and other cache-sensitive games, the installed 5800X3D is the correct AM4 upgrade path from the previous 3900X. A 5900X adds cores but does not solve the cache/game-thread limitation that the captures pointed at. Re-run the benchmark harness on the verified 5800X3D before chasing lower-confidence tweaks.

## 2026-06-13 5800X3D Cup Zone Wars Stress Capture

Capture:

```text
C:\Users\jn\AppData\Local\WindowsGamingBenchmark\Captures\20260613-153814-fortnite-5800x3d-cup-zone-wars
```

Local archive analyzed from:

```text
/tmp/LJ-GAMING-PC-20260613-153814-fortnite-5800x3d-cup-zone-wars
/tmp/LJ-GAMING-PC-20260613-153814-fortnite-5800x3d-cup-zone-wars.zip
```

Conditions:

- CPU installed and verified as Ryzen 7 5800X3D.
- A-XMP restored; RAM/FCLK verified at DDR4-3200 / FCLK1600 before this capture.
- CAM radiator fan curve had been changed from liquid-source behavior to CPU-source behavior, which lowered observed Fortnite CPU temperatures earlier in the session.
- Fortnite was running in a Cup Zone Wars map used as a worst-case Creative stress test.
- OBS was not present in the watched process inventory during this capture; the `obs-profile.csv` file is a config snapshot, not proof that OBS was recording.
- No affinity, priority, or power-plan override was applied by the benchmark harness.

Markers:

- `start`: 2026-06-13 15:38:14 -05:00
- `target-started-20264`: 2026-06-13 15:38:19 -05:00
- `stop-requested`: 2026-06-13 15:41:15 -05:00

Important limitation: this capture has no explicit `map-loaded`, `round-start`, `fight-start`, `round-end`, or `leave-map` markers. Load and exit transitions are mixed into the aggregate stats, so treat the all-window numbers as stress-capture diagnostics rather than clean gameplay FPS.

Analyzer summary:

- PresentMon rows: 6602
- Present mode: almost entirely `Composed: Flip`; this is important because the raw PresentMon FPS did not line up with the in-game FPS Johnny saw
- Runtime: DXGI
- All-window average FPS from raw PresentMon frame time: 37.8
- Trimmed first-60/last-30 average FPS from raw PresentMon frame time: 35.3
- All-window p99 frame time: 201.23 ms
- All-window p99.9 frame time: 661.21 ms
- Worst captured frame: 4047.52 ms
- Average CPU busy: 26.32 ms
- Average GPU busy: 2.56 ms
- p95 max CPU utility: 95.2%
- NVIDIA GPU utilization averaged 48.0%, p95 55.8%, max 56.0%
- GPU temperature stayed low: average 56.6 C, max 59 C
- Available memory averaged 14.1 GB; disk queue and disk latency were not a concern
- Fortnite reached 6472.9 MB working set
- Fortnite hot target-thread samples hit roughly 97-98% of one full logical processor

The raw PresentMon time buckets show why this capture cannot be treated as a clean visible-FPS result:

- 0-40 seconds had severe map load / transition spikes, including many frames over 33 ms.
- 40-80 seconds was much steadier: roughly 52-55 FPS by PresentMon frame time, p50 around 15.8-16.1 ms, and p95 around 35-37 ms.
- 80-150 seconds had another bad region, including a 4047 ms frame and a 3193 ms frame near 15:40:39-15:40:46.
- 160-175 seconds was the cleanest tail: roughly 65-67 FPS by PresentMon frame time, p50 around 16.1 ms, p95 around 25.4-25.5 ms, and only three frames over 33 ms.

Interpretation:

- Johnny's subjective result is important: this map was previously so laggy that mechanics did not work, and after the X3D swap/XMP restore/cooling-profile change it was playable enough to use for practice. That is a real practical win over the old state.
- Johnny reported averaging roughly 150 FPS in-game during this Cup Zone Wars run. Treat that user-visible in-game FPS as the gameplay observation for this run.
- The raw PresentMon FPS numbers in this capture are suspect and should not be used as the authoritative visible FPS result. They conflict with Johnny's in-game observation and look like a composed-presentation measurement path that the current harness/analyzer is not interpreting correctly for this session.
- The non-FPS telemetry still points away from GPU saturation: GPU utilization was modest, GPU temperature was low, and Fortnite had hot target-thread samples near a full logical processor. Keep the working theory as Fortnite hot-thread / CPU-frame pressure, but do not cite this capture's raw PresentMon FPS as the proof.
- Background-process pollution was not the smoking gun here. DWM, Defender, SteelSeries Sonar, Discord, CAM, and PowerShell stayed low relative to Fortnite's own frame-critical work.

Next action:

- For another Cup Zone Wars test, mark `map-loaded`, `round-start`, `heavy-fight`, `round-end`, and `leave-map` so the analyzer can isolate real fighting from load/exit spikes.
- Improve or cross-check the benchmark harness before relying on PresentMon-derived FPS for Creative stress maps. The next capture should include a second visible-FPS source such as RTSS/Afterburner logging, an in-game FPS note, or another reliable frame counter alongside PresentMon.
- Keep Cup Zone Wars labeled as a stress map. Do not compare it directly against BR or Realistics captures.

## 2026-06-13 RTSS/MAHM Benchmark Smoke Capture

Capture:

```text
C:\Users\jn\AppData\Local\WindowsGamingBenchmark\Captures\20260613-155840-fortnite-rtss-mahm-smoke
```

Local archive analyzed from:

```text
/tmp/LJ-GAMING-PC-20260613-155840-fortnite-rtss-mahm-smoke
/tmp/LJ-GAMING-PC-20260613-155840-fortnite-rtss-mahm-smoke.zip
```

Purpose: verify that the benchmark harness can read the same RTSS/Afterburner
data Johnny is watching in the OSD.

Conditions:

- Fortnite was already running.
- RTSS OSD was active and tracking `FortniteClient-Win64-Shipping.exe`.
- MAHM/Afterburner shared memory was available.
- No affinity, priority, or power-plan override was applied by the harness.
- The run was a short smoke check, not a gameplay benchmark.

Results:

- RTSS rows: 37
- RTSS active rows: 37
- RTSS tracked process: `Z:\Epic Games\Fortnite\FortniteGame\Binaries\Win64\FortniteClient-Win64-Shipping.exe`
- RTSS FPS window average: 120.0 FPS
- RTSS frame time average: 8.31 ms, p99 9.59 ms
- MAHM rows: 37
- MAHM OSD framerate average: 119.9 FPS
- PresentMon-derived average FPS over the same smoke capture: 69.2 FPS
- PresentMon average frame time: 14.44 ms
- MAHM CPU temperature: average 81.6 C, min 80.75 C, p95 82.5 C, max 83.0 C
- MAHM CPU clock: average 4399 MHz, max 4450 MHz
- MAHM CPU power: average 76.5 W, max 85.1 W
- MAHM GPU usage: average 38.9%
- MAHM GPU temperature: average 45.6 C, max 48 C
- NVIDIA SMI also reported GPU around 46 C / 41% utilization during its system sample.

Follow-up PresentMon isolation check while Fortnite was still open:

```text
C:\Users\jn\AppData\Local\WindowsGamingBenchmark\Captures\presentmon-debug-20260613-160927
```

- Full PresentMon v2 tracking: 956 rows, `Hardware: Independent Flip`, 8.3484 ms average frame time, 119.78 FPS from average frame time.
- PresentMon `--no_track_display --no_track_gpu --no_track_input`: 1915 rows, 4.2434 ms average frame time, 235.66 FPS from average frame time.
- No stale `PresentMon-2.4.1-x64.exe` capture process remained afterward; only `PresentMonService` was running.

Interpretation:

- The RTSS and MAHM shared-memory capture path works. Future captures can use RTSS/MAHM as the visible-FPS and sensor source instead of trusting PresentMon-derived FPS alone.
- PresentMon is not globally broken. In the smoke capture, PresentMon was wrong for visible FPS because the game was in `Composed: Flip`: RTSS and MAHM agreed around 120 FPS, while PresentMon-derived FPS said roughly 69 FPS. In the immediate follow-up check, full PresentMon tracking matched RTSS when the game was in `Hardware: Independent Flip`, reporting 119.78 FPS.
- `--no_track_display` is not a visible-FPS replacement. It reported about 235.66 FPS, which is closer to an app/present submission cadence than what the player sees on screen.
- Keep PresentMon for `CPUBusy`/`GPUBusy` frame-pipeline diagnostics, but record `PresentMode` and cross-check visible FPS against RTSS/MAHM. Treat PresentMon visible FPS as suspect when the dominant mode is `Composed: Flip` and it disagrees with RTSS/MAHM.
- This run appears to have been in a 120 FPS capped state, likely lobby or another capped context. Treat the 120 FPS result as a harness validation signal, not a full performance benchmark.
- The thermal concern is still real. Seeing roughly 81-83 C at only about 120 FPS, with GPU temperature in the mid-to-high 40s, points back to CPU heat density and cooler/fan behavior rather than GPU heat soak. It is still below the 90 C cHTC limit, but it is warmer than expected for a 5800X3D on a Kraken under this kind of load.
- The next thermal/performance capture should be a marked real match or Creative test with RTSS/MAHM enabled, so we can correlate visible FPS, CPU temp, CPU power, CPU busy, and hot-thread samples over a real workload.


## 2026-05-24 Creative 32-Player Cup Zone Wars FPS Observation

Johnny reported unusually severe FPS lag in a 32-player cup zone wars map, specifically noting that it was FPS lag and that the map had a lot going on. Treat large Creative endgame maps as worst-case CPU-frame-time stress tests, not representative BR baselines. For practice quality, prefer smaller or better-optimized endgame/zone wars maps if the 32-player map breaks frame pacing; bad FPS produces bad fighting reps.

Implication for benchmark planning: if Creative 32-player maps are used for testing, label them explicitly as stress tests and do not compare them directly against normal BR / Realistics captures. Capture map code, player count, OBS state, and whether the lag is map-specific.

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

Reason: modern Fortnite is not guaranteed to have best frame pacing on Performance Mode, but the verified 5800X3D already appears to have solved the old raw-FPS ceiling in Performance Mode. DX11 or a legacy DX11 Performance path, if still selectable, may have lower graphics-feature overhead, but keep render-mode testing as a sanity check for 1% lows, stutter, and OBS/capture interaction rather than a likely raw-FPS unlock. Shader compilation can make first-run DX12 results misleading.

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

Reason: Fortnite can regress on specific driver branches. The current recorded NVIDIA driver is `596.49`.

Test:

1. Keep the recorded NVIDIA driver version attached to each benchmark.
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

Reason: the old 3900X was a multi-CCD Zen 2 CPU, but the installed 5800X3D is a single-CCD gaming part, so the previous CCD/CCX migration concern is mostly retired. Keep affinity testing low priority unless new telemetry shows scheduler or thread-placement problems.

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

- verify stock 5800X3D boost/thermal behavior under clean benchmark load
- fan/pump/radiator airflow tuning before any voltage work
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
