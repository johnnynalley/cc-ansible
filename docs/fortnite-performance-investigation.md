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
- Xbox Game Bar / Game DVR settings are no longer managed by Ansible. Windows
  Settings and the Xbox UI own this now; the 2026-06-13 loaded baseline had
  Game Bar, GameBarPresenceWriter, Xbox app, NVIDIA Overlay, NVIDIA Instant
  Replay, NVIDIA Highlights, Epic, Steam, Rockstar, Discord, Nextcloud, and
  SignalRGB present.
- Hardware-accelerated GPU scheduling is currently disabled (`HwSchMode=1`).
- Multiplane overlay disable was removed from managed state and live registry on 2026-06-13.
  Rollback export: `C:\ProgramData\Johnny\LiveRollbacks\dwm-before-mpo-restore-20260613-172721.reg`.
  Effective compositor behavior still needs a Windows reboot, then a PresentMon/RTSS validation capture.
- NIC power-saving features and interrupt moderation are disabled by the gaming tuning playbook.
- Automatic Performance Mode is retired. It no longer auto-watches Fortnite/OBS
  or closes/stops background clients and services.
- BCDEdit does not show obvious HPET/platform-clock/dynamic-tick tweak pollution.
- High-resolution textures were turned off in Epic Games Launcher on 2026-05-22 and verified by disk state.

## 2026-06-13 Optimization Rollback Audit

Context: after the 5800X3D install and A-XMP restore, the best real-round capture averaged roughly 194 FPS by RTSS with a 199.8 FPS p50 in round 2. That changes the cleanup priority. The old broad background-app shutdown was useful while diagnosing the 3900X-era ceiling, but it is no longer proven necessary and now has real workflow costs: launcher relaunch friction and Xbox/Game Bar chat breakage. The separate custom SignalRGB lock/unlock automation was retired on 2026-08-23 after the workstation moved to sleep for idle periods.

Treat these as the current one-by-one decisions:

| Optimization | Current classification | Reasoning / next action |
| --- | --- | --- |
| A-XMP / DDR4-3200 / FCLK1600 | Keep | This is the highest-confidence win found so far. Do not compare new tweaks against the accidental DDR4-2133 state. |
| 5800X3D cooling profile | Keep / monitor | CPU-sourced CAM fan behavior immediately lowered Fortnite temperatures. No Ansible change; keep watching real-match CPU temp, clocks, and cHTC headroom. |
| AMD Ryzen High Performance power plan | Keep for now | Static, low-friction, and the current strong baseline used it. Ryzen Balanced can be A/B tested later, but do not change it while cleaning up app-killing behavior. |
| NIC latency tuning | Keep | Disabling NIC power-saving and interrupt moderation is independent of the app-closing Performance Mode stack. It is a reasonable wired-gaming latency/stutter tweak with low downside on this desktop. |
| Defender Fortnite path exclusion | Keep | Scope is limited to the Fortnite install path, not a blanket Defender disable. It can reduce scan interference during game asset reads/updates. |
| RTSS/MAHM monitoring and SignalRGB RTSS exclusions | Keep | RTSS/MAHM is now the visible-FPS/sensor cross-check path. Excluding SignalRGB from RTSS hooking also supports the lighting API stability hypothesis. |
| MPO restored to Windows default | Keep pending reboot/capture validation | Managed state now removes `OverlayTestMode`. Do not re-disable MPO unless a measured capture proves it helps. |
| HAGS disabled | A/B test later | Current managed value is `HwSchMode=1`, but Epic recommends enabling HAGS. Test only after the cleanup baseline is stable and do not combine it with other graphics changes. |
| VBS/HVCI disable path | Leave disabled in inventory | The test entries are currently `enabled: false`. Do not apply unless Johnny accepts the security tradeoff for a controlled A/B. |
| High-resolution textures off | Keep user-managed | This is controlled through Epic Games Launcher options, not Ansible. Keep the disk-state evidence, but do not manually delete paks. |
| Performance Mode auto watcher | Rolled back 2026-06-13 | Live watcher task is removed, no watcher process was present after verification, and manual shortcuts/scripts remain available for future experiments. |
| OBS Performance Mode trigger | Rolled back 2026-06-13 | OBS no longer references the trigger in the active scene collection, and the old trigger file was replaced with a disabled stub so future OBS launches cannot silently enter Performance Mode. |
| Launcher/app close rules | Rolled back 2026-06-13 | The active process close list is now empty. Epic, Steam, Rockstar, Xbox, Nextcloud, SignalRGB, and other normal clients should no longer be killed by Performance Mode. |
| SignalRGB session-state automation | Retired 2026-08-23 | The custom logon-on, lock-off, and unlock-on tasks were removed. SignalRGB remains resident for colors through its ordinary user startup entry. |
| SysMain / Delivery Optimization / Windows Search / BITS stop rules | Rolled back 2026-06-13 | The active service stop list is now empty. Re-add only if a benchmark identifies a specific service as a stutter source. |
| Xbox Game Bar / Game DVR settings | Unmanaged by Ansible 2026-06-13 | `inventory/host_vars/lj-gaming-pc/gamebar.yml` was removed so Windows Settings/Xbox UI owns Game Bar. The old Ansible-managed disabling values were removed live as a one-time cleanup rather than replaced with new managed values. |
| Fortnite process priority | A/B test later | Low-risk, but do not bake it in without a capture showing better RTSS/MAHM FPS or lows. |
| Affinity presets | Deprioritized | The old multi-CCD 3900X concern does not carry cleanly to the single-CCD 5800X3D. Only revisit with a controlled benchmark. |
| Launch arguments such as `-USEALLAVAILABLECORES` | Deprioritized / rejected | Existing evidence points to frame-critical thread pressure, not missing cores. Do not add cargo-cult launch flags without a specific measured hypothesis. |

Live cleanup applied 2026-06-13:

- Rollback backup: `C:\ProgramData\Johnny\LiveRollbacks\gaming-cleanup-20260613-202322`.
- Performance Mode watcher task verified absent after final convergence.
- Watcher process count verified `0`.
- Performance Mode state verified inactive with zero closed apps and zero stopped services.
- OBS scene collection verified not to contain the Performance Mode trigger script path.
- Game Bar values `AppCaptureEnabled`, `HistoricalCaptureEnabled`, `GameDVR_Enabled`, and policy `AllowGameDVR` were removed, not replaced with new managed values.
- Keep NIC tuning, Defender exclusion, power plan, RTSS/MAHM monitoring, benchmark tooling, and other static low-friction optimizations intact.

## 2026-08-29 Fortnite Crash RCA

Read-only crash evidence was collected with `scripts/gaming/collect-fortnite-crash-evidence.ps1`.

Latest Fortnite crash directory:

```text
C:\Users\jn\AppData\Local\FortniteGame\Saved\Crashes\UECC-Windows-D28480164716B34EBFF5F284F892BB7E_0000
```

Last write time: `2026-08-29T13:43:00-05:00`.

Fortnite's own logs point to a virtual-memory allocation failure, not a normal
GPU-driver reset:

- `FortniteGame.log` reported a critical error at line 8319.
- The same log reported: `Ran out of memory allocating 31059968 (29.6 MiB) bytes with alignment 0. Last error msg: The paging file is too small for this operation to complete.`
- The backup log `FortniteGame-backup-2026.08.29-18.40.54.log` reported `Runnable thread Foreground Worker #1 crashed.`
- That backup log also reported: `Ran out of memory allocating 143892480 (137.2 MiB) bytes with alignment 0. Last error msg: The paging file is too small for this operation to complete.`

Windows Resource Exhaustion Detector events line up with the crash window:

- `2026-08-29T13:39:53.2810801-05:00`: Windows diagnosed low virtual memory and named `firefox.exe` PID 18204 at 98,577,752,064 bytes of virtual memory, `SignalRgb.exe` at about 4.1 GB, and `XboxPcApp.exe` at about 2.9 GB.
- `2026-08-29T13:44:58.0618394-05:00`: Windows again diagnosed low virtual memory and named the same `firefox.exe` PID 18204 at 100,273,147,904 bytes, with `SignalRgb.exe` and `XboxPcApp.exe` again the next largest named consumers.

Current post-crash state from the same collector:

- The runaway Firefox PID was no longer live by the time of the collector run.
- Commit was back to about 29.5 GB used out of an 81.3 GB commit limit.
- The system-managed pagefile on `C:` was allocated at about 48.6 GB, with about 12.6 GB peak usage recorded.
- `C:` had about 422.6 GB free, so the crash was not explained by the disk being full.
- Current high private-memory processes included SignalRGB around 4 GB, Xbox app around 2.9 GB, Discord/Steam/Medal/Tracker in lower ranges, and MedalEncoder with a high recorded paged-memory peak around 9.7 GB.

Interpretation:

The strongest root cause is a runaway Firefox process exhausting virtual-memory
commit around the Fortnite crash. Fortnite then failed a comparatively small
allocation because Windows could not satisfy it at that moment. SignalRGB, Xbox,
and MedalEncoder are worth watching because they were or had recently been
large memory consumers, but Firefox was the dominant named offender in the
Resource Exhaustion events.

Nearby app crashes around the same window included Nextcloud, Medal
`get-graphics-offsets64.exe`, and MSI Center `CC_Engine_x64.exe` with
`0xc0000409`. Treat those as possible fallout from the same memory-pressure
event or separate background-app instability until another capture proves a
direct cause.

Next actions:

1. Before Fortnite or streaming sessions, fully restart Firefox or avoid using
   Firefox for Twitch/TikTok/stream pages while playing until the leaking tab,
   site, extension, or browser session is identified.
2. Done: the benchmark preflight now records top memory consumers, flags large
   private/commit-memory processes, and captures recent Windows Resource
   Exhaustion Detector events so an absurd commit consumer is visible before
   Fortnite starts.
3. Keep the system-managed pagefile for now, but consider a fixed `C:` pagefile
   floor/ceiling such as 48-64 GB only with explicit approval. This is a crash
   safety net, not the root fix for a runaway browser process.
4. If SignalRGB or MedalEncoder keep showing multi-GB growth, investigate those
   separately rather than treating this Fortnite crash as proof that they are
   the primary cause.

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

> Updated 2026-08-29 after the 5800X3D verification, A-XMP restore, cooling-profile checks, Performance Mode rollback, Firefox memory-crash RCA, clean Rezon isolation capture, and clean BR follow-up. Treat this as a benchmark queue, not applied wins.

1. Streaming/OBS capture-path baseline:
   - the old OBS delta was measured on the previous 3900X baseline, where non-OBS gameplay was around 151 FPS and OBS recording was around 99-102 FPS
   - post-5800X3D clean gameplay now looks strong in Rezon 1v1s and BR, so the next meaningful tests are app-attribution and the real streaming stack, not more stripped-offline proof that the CPU upgrade works
   - first tests: normal streaming scene with stream relay, OBS preview enabled vs disabled, Game Capture stability/admin state, and whether the relay/offload path adds any measurable encode/capture pressure on the gaming PC
2. App-attribution follow-up:
   - clean BR with Firefox/Medal/Tracker closed averaged 198.7 FPS in the gameplay-ish band
   - BR with Firefox + Tracker open and Medal absent averaged 195.1 FPS in the gameplay-ish band, with higher GPU usage, RAM use, context switches, network traffic, and transition stalls
   - Johnny's real workflow includes watching streams in Firefox while keeping Tracker.gg open, so treat Firefox + Tracker / no-Medal as the desired-workflow baseline
   - BR with Firefox + Tracker + Medal averaged 196.7 FPS in the gameplay-ish band, with a 13.7 minute stable run averaging 197.3 FPS and zero sampled rows over 16.67 ms
   - this does not implicate Medal as the large active-gameplay regression source, but Medal did add measurable background footprint and the browser/network workload was not identical between runs
   - keep Firefox restart/closure as the safest pre-session habit because of the separate virtual-memory crash RCA
3. HAGS A/B if the user approves another reboot-level graphics test:
   - current managed state disables HAGS with `HwSchMode=1`
   - Epic's FPS guide recommends enabling HAGS when available
   - test HAGS only after the current loaded baseline is preserved, and do not combine it with render-mode changes in the same run
4. VBS/HVCI diagnostic A/B remains available only if Johnny accepts the reversible security tradeoff:
   - the post-5800X3D baseline does not justify disabling it blindly
   - document current `msinfo32` / Core Isolation state before changing anything
   - if disabled for a test, reboot, run the same capture, and re-enable if there is no meaningful win
5. Render-mode sanity checks, not a likely FPS unlock:
   - do not expect DX12 to beat Performance Mode for raw average FPS on this CPU-limited setup
   - DX11 or any legacy DX11 Performance path may be worth identifying only if it is still exposed/supported, but it is not expected to beat current Performance Mode for CPU frame time
   - keep render-mode tests as frame-pacing/stutter/OBS-interaction sanity checks, not likely 200 FPS paths
   - compare current Performance Mode against DX12 all-low/competitive only after multiple shader warm-up matches; if DX11 is still selectable, benchmark it separately
   - compare average FPS, 1%/0.1% lows, CPU Busy, GPU Busy, stutter markers, and input feel
6. MPO / PresentMon validity follow-up:
   - live state before this change showed `OverlayTestMode=5`, which disables MPO
   - managed target state now removes `HKLM:\SOFTWARE\Microsoft\Windows\Dwm\OverlayTestMode`
   - applied live on 2026-06-13; verified registry value absent while HAGS remained `HwSchMode=1`
   - rollback export saved at `C:\ProgramData\Johnny\LiveRollbacks\dwm-before-mpo-restore-20260613-172721.reg`
   - reason: Microsoft documents that Independent Flip can stay active when other desktop contents are present by using reverse composition or MPO; disabling MPO may force Fortnite back to `Composed: Flip` when overlays/capture are active
   - the post-cleanup capture still showed `Composed: Flip` almost the whole time, so RTSS/MAHM remain authoritative for visible FPS while PresentMon frame-pipeline metrics remain suspect in that state
7. NVIDIA driver/profile sanity:
   - record the current NVIDIA driver version in this document before more A/B tests
   - current snapshot reports NVIDIA driver `596.49`
   - if captures regress after a driver update, consider a clean install or known-stable driver branch as a measured test
   - this is a sanity check, not a magic tweak
8. Fortnite priority A/B remains low-risk but is now behind OBS/VBS/render-mode/MPO/HAGS tests:
   - run the same Fortnite + OBS recording/streaming workload with `--priority High`
   - compare against the 2026-05-23 OBS recording captures below
   - do not bake priority into Performance Mode unless it wins clearly
9. BIOS-side Ryzen/RAM tuning:
   - PBO/scalar/AutoOC and memory/FCLK/timing work are more likely to move the single-thread ceiling than more background-app cleanup
   - DDR4-3200 CL16 and FCLK1600 are restored after the CPU swap
   - any BIOS/memory change needs stability testing before calling it a Fortnite win
10. Affinity/CCD/CCX tests are not the immediate recommendation. The current saved benchmark state files all show `AffinityPreset: none`; if affinity was tried earlier, there is no durable capture artifact in the harness. Only revisit with a controlled, documented A/B if Johnny explicitly wants that path or telemetry shows cross-CCD/thread-migration cost.

## 2026-08-26 Fortnite FPS Regression Capture

Capture:

```text
C:\Users\jn\AppData\Local\WindowsGamingBenchmark\Captures\20260826-194926-fortnite-fps-regression-20260826
```

Local archive/analyzed copy:

```text
/tmp/LJ-GAMING-PC-20260826-194926-fortnite-fps-regression-20260826.zip
/tmp/LJ-GAMING-PC-20260826-194926-fortnite-fps-regression-20260826
```

Context:

- Johnny reported newly poor Fortnite FPS while in game.
- The benchmark harness was not already active. The prior status pointed at the
  June 17 pre-4000D real-workload capture, so there was no continuous always-on
  FPS log for the current regression.
- Capture ran from `2026-08-26T19:49:26-05:00` to
  `2026-08-26T19:57:05-05:00`.
- No affinity, priority, or power-plan override was applied by the harness.
- Active power plan remained AMD Ryzen High Performance, memory stayed at
  DDR4-3200 configured speed, display refresh stayed 200 Hz, Fortnite cap
  stayed 200 FPS, dynamic resolution was false, and quality settings remained
  low/competitive.
- Fortnite high-resolution texture install tags remained empty; the main
  Fortnite manifest install size was about 42 GB.
- Fortnite itself had recent file churn before the bad-FPS session: many
  install files under `Z:\Epic Games\Fortnite` were written around
  2026-08-26 10:08 local, including large UEFN pak/ucas files and
  `ShaderCompileWorker.exe`. Epic manifests for Unreal Editor for Fortnite,
  LEGO Fortnite Content, and Save the World content were also written at
  10:08. The main Fortnite manifest was touched at launch time
  2026-08-26 18:55, which may be normal launcher bookkeeping.

Current-state changes versus the recorded June good baseline:

- NVIDIA driver now reports `610.62` / Windows driver `32.0.16.1062`; the
  investigation's previous recorded driver was `596.49`.
- Windows update `KB5121003` and update `KB5120708` installed on 2026-08-23.
  `KB5121003` is the Microsoft-documented build `26200.9168` update with a
  known issue for some games becoming unresponsive on systems with certain
  RGB-related drivers/components. The named filename pattern is similar to
  `inpoutx64`; this machine did not have `inpoutx64.sys`, but it did have
  running Corsair low-level/HID drivers and `SignalRgbDriver.sys`.
- Medal `2634.403.1` was installed/updated on 2026-08-23 and `MedalEncoder`
  was present during the capture.
- SignalRGB is now `2.5.74` and was one of the hotter background processes in
  the capture. The custom SignalRGB lock/unlock automation was retired on
  2026-08-23; normal SignalRGB startup remains.

Visible FPS and frame pacing:

- RTSS all rows: average 165.4 FPS, p50 178.2 FPS, p95 194.9 FPS, p99
  197.8 FPS.
- RTSS gameplay-ish `fps >= 140`: average 179.9 FPS, p50 182.1 FPS, p95
  195.1 FPS, p99 197.8 FPS.
- This is materially worse than the 2026-06-13/14 loaded good baseline, where
  gameplay-ish `fps >= 140` averaged 196.5 FPS with p50 198.8 FPS.
- Full RTSS frame-time p95 was about 9.8 ms with 9 sampled frames over
  16.67 ms and 6 over 25 ms. The analyzer also saw large transition/stall
  frames early in the capture; do not compare those directly to a clean
  marked match segment.

PresentMon validity:

- PresentMon was valid in this capture: all 65,408 rows were
  `Hardware: Independent Flip`.
- Trimmed PresentMon gameplay window averaged about 150.6 FPS from frame time.
  CPU busy averaged 6.34 ms with p95 11.30 ms; GPU busy averaged 4.67 ms with
  p95 5.83 ms.
- This points to CPU/frame pacing dominance with occasional GPU participation,
  not a pure GPU downclock. CPU wait stayed low.

Thermals and clocks:

- CPU temperature averaged 79.7 C and maxed at 81.6 C in the summarized RTSS
  window; this is warm but below the prior June max and does not show thermal
  throttling.
- CPU clocks remained around 4.39-4.44 GHz in system/MAHM rows.
- GPU clocks, PCIe link, and temperatures looked normal: RTX 3070 around
  2040-2055 MHz, PCIe Gen4 x16, GPU temp about 56-57 C in the active tail,
  NVIDIA GPU utilization up to 94%.

Runtime pressure:

- Preflight warning: Memory Compression working set about 2.1 GB, with
  available memory still healthy at about 6.8 GB. Treat this as capture
  pollution to watch, not proof of RAM exhaustion.
- Highest non-Fortnite one-thread CPU pressure in the capture included
  Nextcloud max 105%, System max 100.5%, Firefox max 92.1%, DWM max 91.4%,
  SteelSeries Sonar max 75.5%, Explorer max 75.4%, SteelSeries GG Client max
  58.9%, SignalRGB max 56.3%, audiodg max 45.2%, SearchIndexer max 30%,
  MedalEncoder max 29.5%, Discord max 29.5%, and Defender `MsMpEng` max 28.1%.
- Tracker.gg was present with multiple Electron/Overwolf-style helper
  processes, including a GPU process and renderer processes, but it did not
  appear as a meaningful CPU offender. The capture had only one top-process
  row for `Tracker.gg`, at about 0.6% total CPU / 9.2% of one logical thread,
  and the follow-up live samples showed its processes at 0% CPU except for one
  10% one-thread blip.
- NVIDIA GPU utilization was high in this capture, averaging roughly 80.7%
  across RTSS rows and peaking at 94%. That is higher than the good-baseline
  average, but high GPU peaks are not new by themselves: the June good capture
  also reached about 93-97% GPU utilization at the high end. Treat the current
  GPU pressure as contributory, especially because GPU busy p95 exceeded the
  5 ms / 200 FPS budget, but not as the only bottleneck.
- Context switches remained high, and the analyzer classified a hot logical
  processor plus scheduler churn/driver-interrupt pressure. This is similar in
  shape to the old frame-critical-thread bottleneck, but with more active
  background pressure than the June good capture.

Live follow-up snapshot at `2026-08-26T20:21:00-05:00` while Fortnite was
running after Johnny intentionally uncapped gameplay FPS as a headroom test:

- Fortnite's saved config had changed since the capture: `FrameRateLimit=0.000000`
  and `FrontendFrameRateLimit=120`. Treat `FrameRateLimit=0` as uncapped
  gameplay FPS. This was a deliberate post-capture test condition, not an
  accidental cause of the original regression capture.
- The useful signal from the uncapped test is that Fortnite did not regain the
  old above-200 FPS headroom. It also explains why GPU utilization looked
  higher during the follow-up than it would with a strict 200 FPS cap.
- The config file had a last write time of `2026-08-26 20:19:41` local.
- Johnny restored the gameplay cap afterward. A read-only check showed
  `FrameRateLimit=200.000000`, `FrontendFrameRateLimit=120`, and config last
  write time `2026-08-26 20:29:52` local.
- HAGS remained disabled through `HwSchMode=1`; MPO stayed at Windows default
  because `OverlayTestMode` was absent.
- Game Mode-related registry values read `AutoGameModeEnabled=0` and
  `AllowAutoGameMode=0`. Because Game Bar/Game Mode are intentionally no
  longer Ansible-owned, verify this through the Windows Settings GUI before
  changing it with registry writes.
- Follow-up evidence points to Medal as the app that has the disable-Game-Mode
  capability, not Tracker.gg. Official Medal support documents a Medal UI
  toggle under Settings > Windows OS Settings > Advanced Settings that
  automatically disables Windows Game Mode for clip performance:
  <https://support.medal.tv/support/solutions/articles/48000922112>.
  The installed Medal app code contains `WindowsGameModeDisabled`, defaults it
  to `true`, and one Medal profile database has a `WindowsGameModeDisabled`
  key. Johnny later checked the Medal UI and reported that the setting was
  currently off, so do not claim Medal's current UI state was proven enabled.
  The verified live state before remediation was still
  `AutoGameModeEnabled=0` and `AllowAutoGameMode=0`.
- At Johnny's instruction, Game Mode was re-enabled directly in the user
  registry on 2026-08-26. Rollback exports were saved at
  `C:\ProgramData\Johnny\LiveRollbacks\game-mode-before-enable-20260826-204458`.
  Post-change verification, with Medal still running, showed
  `AutoGameModeEnabled=1` and `AllowAutoGameMode=1`; Medal did not immediately
  revert them.
- Microsoft's older Game Mode API documentation says foreground games can
  receive priority/exclusive resource treatment and increased GPU
  prioritization, with the benefit depending on competing background activity:
  <https://learn.microsoft.com/en-us/previous-versions/windows/desktop/gamemode/game-mode-portal>.
  That makes Game Mode a valid Fortnite A/B test on this system, especially
  with normal creator apps left running, but not a guaranteed win.
- Active GPU engine users included Fortnite graphics/compute, DWM 3D, Firefox
  3D/video decode, MedalEncoder video encode, Discord Clips video encode, Epic
  Launcher 3D, SteelSeries GG 3D, Rockstar SocialClub helper 3D, and a small
  Tracker.gg 3D entry.

Interpretation:

- The regression is real in telemetry. The original capture was not explained
  by a reset RAM clock, wrong power plan, display refresh cap, high-res
  textures, Fortnite's original 200 FPS cap, or thermal throttling.
- The uncapped follow-up is still useful: if the same system used to exceed
  200 FPS uncapped and now cannot, that supports a real headroom regression
  rather than merely a bad cap setting.
- Remaining suspects are recent Windows/RGB-driver interaction from
  `KB5121003`, the same-day Fortnite content/update churn, currently hot
  RGB/audio/sync/overlay processes, HAGS-disabled behavior under heavier GPU
  load, and the NVIDIA 610.62 driver difference from the last documented good
  baseline.
- Before changing settings, prefer a clean A/B sequence:
  1. Use the restored 200 FPS gameplay cap for competitive frame-pacing tests;
     leave uncapped only when intentionally measuring raw headroom.
  2. Capture with Game Mode enabled, Tracker.gg and Medal otherwise running,
     and compare against the 2026-08-26 disabled-Game-Mode regression capture.
  3. If still bad, run the already-planned HAGS A/B because current GPU load is
     high and HAGS is still disabled.
  4. Reboot once, start Fortnite with the same normal workload, and capture a
     clean match segment after startup/transition stalls settle.
  5. If still bad, test with Medal fully closed/disabled first because it
     changed on 2026-08-23 and had an encoder process present.
  6. Test with Tracker.gg/Overwolf closed as an overlay-hook A/B even though it
     was not a CPU-heavy process in this capture.
  7. Test with SignalRGB and Corsair/iCUE background components disabled only
     for the session, because `KB5121003` has an official RGB-driver/game
     known issue and this machine has Corsair/SignalRGB kernel drivers loaded.
  8. If that still fails, compare a known-stable NVIDIA driver rollback against
     the current 610.62 branch.
  9. Only after those checks should broader Windows update rollback be
     considered, because `KB5121003` is a security cumulative update.

Active follow-up capture started at `2026-08-26T20:53:16-05:00`:

```text
C:\Users\jn\AppData\Local\WindowsGamingBenchmark\Captures\20260826-205316-fortnite-game-mode-enabled-normal-workflow-20260826
```

Conditions:

- Game Mode re-enabled and verified while Medal remained running:
  `AutoGameModeEnabled=1`, `AllowAutoGameMode=1`.
- Fortnite gameplay cap restored to `FrameRateLimit=200.000000`.
- Tracker.gg, Medal, Firefox, SteelSeries, SignalRGB, Epic Launcher, Nextcloud,
  Discord, and other normal workflow apps remained present.
- Preflight warning: Memory Compression already large at about 2.49 GB.

Stopped/fetched analysis:

- PresentMon was usable in this capture: all 320,151 PresentMon rows reported
  `Hardware: Independent Flip`. Unlike the older composed-flip captures, this
  run can use PresentMon frame-pipeline data as supporting evidence alongside
  RTSS/MAHM visible FPS.
- Game Mode alone did not restore the old locked-200 behavior. RTSS visible
  FPS over the full mixed capture averaged 157.8 FPS with p50 168.3, p95
  197.0, p99 199.8, and max 200.8. The full average is dragged down by
  severe stalls and the later 120 FPS lobby/sleep tail.
- Before the sustained 120 FPS tail, the gameplay-ish `fps >= 140` band
  averaged 174.2 FPS with p50 175.2, p95 198.0, p99 199.8, and max 200.8.
  The near-cap `fps >= 180` band averaged 189.7 FPS. Clean stretches still
  prove the machine can approach or hit the 200 cap: `21:15:29-21:16:59`
  averaged 195.0 FPS, and `21:26:53-21:28:17` averaged 194.8 FPS with no
  RTSS frames over 16.67 ms.
- The problem in this run is intermittent freeze/drop behavior, not simple
  steady-state throughput. Before the lobby tail, RTSS logged 75 samples over
  16.67 ms, 49 over 33.33 ms, and 42 over 50 ms. Worst RTSS samples included
  4,044 ms at `21:00:29`, repeated 2,230 ms samples around `21:08:09-21:08:13`,
  repeated 2,225 ms samples around `21:24:51-21:24:55`, and 2,092 ms samples
  around `21:01:37-21:01:42`.
- The run did briefly hold roughly 192-199 FPS, then suffered a severe collapse
  around `2026-08-26T21:07:10-05:00`; a marker was added:
  `observed-fps-collapse-gpu-high-20260826-210710`.
- A later managed `bin/windows-gaming-benchmark peek` over
  `21:14:35-21:22:15` found another collapse. RTSS FPS averaged 168.9 with
  p95 198.8 and p99 199.9, but lows were bad: 113 of 360 samples were below
  160 FPS, 44 were below 140, four were below 60, and the worst RTSS frame was
  258.5 ms at `21:17:03`. A marker was added:
  `observed-repeat-fps-collapse-20260826-211703`. This supports treating the
  current regression primarily as intermittent stalls/lows rather than a
  simple inability to render near 200 FPS.
- A follow-up full Ansible `peek` over `21:17:29-21:25:10` observed a worse
  freeze around `21:24:51-21:24:55`, with repeated RTSS samples at 11.75 FPS
  and 2,225 ms frame time. Because that freeze overlapped with the remote
  full-playbook peek itself, treat it as possibly probe-induced until a final
  stopped/fetched capture proves otherwise. The harness now documents
  `peek --no-deploy` as the lower-overhead active-game check.
- A read-only event-log query for the capture window found no System/Application
  warning/error events for display driver resets, WHEA, disk, or OBS/app
  crashes. The only warning/error entries found were five
  `Microsoft-Windows-Search` event `10024` warnings at `21:07:36-21:07:42`
  reported unresponsive Search filter hosts being forcibly terminated.
  Resolved SearchFilterHost persistent handlers included Open Document Format,
  plain text, and generic pixel/image filters. This makes Windows Search
  indexing a strong candidate for at least that stall, especially because the
  indexed roots include broad `C:\Users\` scope and the machine has large cloud
  sync folders under the user profile.
- Search CPU was quiet shortly after the event cluster, so the evidence points
  to a burst/stall, not constant Search CPU load.
- The later `21:17` collapse did not have new Search event 10024 warnings, so
  Windows Search is a proven candidate for at least one stall, not yet a full
  explanation for every severe drop in the active run.
- The same live peek showed normal-workflow background CPU is still visible in
  the sampled process tail: Fortnite dominated, but Firefox, SteelSeries GG,
  Nextcloud, Desktop Window Manager, System, SocialClubHelper, SignalRGB,
  explorer, audiodg, SteelSeries Sonar, and Discord all appeared in the top
  recent CPU sample set. This does not prove any one app should be disabled,
  but it does explain why the 5800X3D can still show frame-critical contention
  even when total CPU usage looks low.
- CPU temperature does not look like the root cause in this capture. MAHM CPU
  temp averaged 80.4 C, p99 was 82.1 C, max was 82.5 C, and CPU clocks stayed
  around 4.42-4.45 GHz.
- System counters still show contention signals: p95 max CPU utility was
  126.1%, p95 context switches were about 298k/sec, p95 DPC was 3.32%, and
  p95 interrupts were 3.99%. Available memory stayed healthy with a 5.8 GB
  minimum, so this was not RAM exhaustion despite high committed memory.
- NVIDIA telemetry showed GPU usage high but not thermally or PCIe limited:
  SMI GPU util averaged 81.6%, p95 96%, GPU temp max 61 C, VRAM used about
  3.2 GB, and PCIe stayed Gen4 x16. PresentMon's worst-spike shape had huge
  frame/GPU-wait time while GPU busy itself stayed low, which points away from
  pure GPU rendering saturation as the explanation for multi-second stalls.
- Fortnite's current log shows the active render path is D3D12
  (`Using Default RHI: D3D12`) with NVIDIA driver `610.62`; Microsoft
  "Optimizations for windowed games" mainly targets DX10/DX11 windowed or
  borderless games, so that setting is not currently ranked as a likely D3D12
  Performance Mode fix.
- Fortnite logs repeatedly reported shader/material problems in this session:
  hundreds of `Invalid shader map ID`, `invalid ShaderMap`, `uncooked shader
  map ID`, and `Loading a material resource None` entries. Recent backup logs
  had smaller counts, so the current log is materially noisier.
- Epic's Fortnite support article for "stutters heavily and has below expected
  performance on DirectX 12" says the client can repeatedly recompile DirectX
  shaders and recommends clearing the shader cache after closing Epic Games
  Launcher and Fortnite:
  <https://www.epicgames.com/help/c-202300000001636/c-202300000001719/fortnite-stutters-heavily-and-has-below-expected-performance-on-directx-12-a202300000018050>.
- Local cache inventory supported that path before maintenance:
  `C:\Users\jn\AppData\Local\NVIDIA\DXCache` was about 10.2 GB, included a
  4 GB file touched on 2026-08-26, and `C:\Users\jn\AppData\Local\D3DSCache`
  was about 816 MB. Fortnite's `PersistentDownloadDir` was about 5.3 GB and was
  intentionally left alone.
- A disabled-by-default `shader-cache` maintenance task is now staged in the
  Windows gaming tuning playbook. It refuses to run while Fortnite or Epic
  Launcher processes are active unless forced, writes a JSON manifest under
  `C:\ProgramData\Johnny\LiveRollbacks`, and only targets disposable NVIDIA
  DX/D3DS cache paths.
- The shader-cache task was run on 2026-08-26 after Fortnite was closed. The
  first attempt correctly refused because `EpicGamesLauncher` and two
  `EpicWebHelper` processes were still running. After closing only those Epic
  processes, the guarded task ran with `ForceClear=false` and wrote manifest
  `C:\ProgramData\Johnny\LiveRollbacks\shader-cache-before-clear-20260826-214953`.
  Results: NVIDIA `DXCache` went from 571 files / 10,205.8 MB to 16 locked
  files / 3.5 MB; `D3DSCache` went from 101 files / 817.7 MB to 0 files; the
  per-driver NVIDIA DX cache path did not exist. The remaining 16 DXCache files
  were tiny locked `.nvph` entries and were not forced.
- Follow-up Rezon 1v1s testing after the shader-cache clear did not restore
  the expected near-locked 200 FPS behavior. Do not treat shader-cache cleanup
  as the root fix. It remains a reasonable maintenance action for DX12 shader
  churn, but the active regression is still open.
- The next non-app-disabling remediations are now ranked:
  1. Improve attribution in the benchmark harness before the next capture:
     system-wide network upload was high in the Rezon run, and the next harness
     revision records process I/O deltas in `watched-processes.csv` and
     `top-processes.csv`. These counters are not network-specific, but they
     can identify upload, cache, file, or socket churn candidates.
  2. Exclude heavy sync/media folders such as `C:\Users\jn\Nextcloud` from
     Windows Search indexing, or otherwise constrain Search indexing, instead
     of disabling Tracker.gg or Medal.
  3. Run HAGS enabled/disabled A/B with reboot and capture after the cache,
     Search-stall, and high-upload candidates are handled or ruled out.
  4. Test the RGB/monitoring driver stack for one session if the above fail:
     Microsoft documents a `KB5121003` known issue for some games on systems
     with certain RGB-related drivers/components, and this machine currently
     has Corsair/iCUE, SignalRGB, MSI Center, and Afterburner low-level drivers
     in the broader hardware-monitoring path. This is a controlled A/B
     candidate, not a proved Fortnite cause.

## 2026-08-26 Rezon 1v1s After Shader-Cache Clear

Capture:

```text
C:\Users\jn\AppData\Local\WindowsGamingBenchmark\Captures\20260826-222037-fortnite-rezon-1v1s-after-shader-cache-20260826
```

Local archive/analyzed copy:

```text
/tmp/LJ-GAMING-PC-20260826-222037-fortnite-rezon-1v1s-after-shader-cache-20260826.zip
/tmp/LJ-GAMING-PC-20260826-222037-fortnite-rezon-1v1s-after-shader-cache-20260826
/tmp/LJ-GAMING-PC-20260826-222037-analysis.json
```

Context:

- This was a Rezon 1v1s Creative capture immediately after the shader-cache
  clear, so do not compare it as identical workload to BR, Go Goated, Cup Zone
  Wars, or Duo baselines.
- Capture ran from `2026-08-26T22:20:37-05:00` to
  `2026-08-26T22:43:21-05:00`.
- No affinity, priority, or power-plan override was applied.
- Preflight allowed and recorded one warning: Memory Compression working set
  was 1,786.1 MB before start, while available memory was still about 10.7 GB.
- A live read-only System/Application warning/error query across the capture
  window returned no events. The capture archive has no `event-log.csv` rows.

Visible FPS and frame pacing:

- RTSS all rows: average 183.1 FPS, p50 188.0 FPS, p95 198.0 FPS, p99
  199.8 FPS, max 201.0 FPS.
- RTSS gameplay-ish `fps >= 140`: average 186.0 FPS, p50 188.2 FPS, p95
  198.0 FPS, p99 199.8 FPS. Frame-time p95 was 8.11 ms, p99 11.72 ms, max
  22.16 ms, with only two samples over 16.67 ms and none over 25 ms.
- RTSS near-cap `fps >= 180`: average 190.8 FPS, p50 191.9 FPS, p95 198.0
  FPS, p99 199.8 FPS. Frame-time p95 was 7.47 ms, p99 9.94 ms, max 22.16 ms.
- Full-window frame-time p99 was 13.16 ms. The ugly tail was p999 406 ms and
  max 458 ms by RTSS, with three RTSS samples over 50 ms.
- PresentMon was valid in this capture: all 218,384 rows were
  `Hardware: Independent Flip`. PresentMon all-window average frame time was
  6.20 ms, CPU busy averaged 5.92 ms, and GPU busy averaged 4.34 ms. Trimmed
  first-60/last-30 values were similar: 6.14 ms frame, 5.86 ms CPU busy, and
  4.35 ms GPU busy.

Thermals and system pressure:

- MAHM CPU temperature averaged 78.9 C, p95 80.1 C, p99 82.3 C, max 83.3 C.
  CPU clock averaged 4,438 MHz and maxed 4,450 MHz. This does not show thermal
  throttling.
- NVIDIA SMI GPU utilization averaged 84.8%, p95 94%, max 95%; GPU temperature
  maxed 58 C, VRAM used maxed about 2.68 GB, and PCIe stayed Gen4 x16.
- System p95 max CPU utility was 123.7%, p95 context switches were about
  327,733/sec, p95 DPC was 2.78%, and p95 interrupts were 4.85%.
- System-wide outbound network was unusually high for a Fortnite-only
  competitive test: average sent throughput was about 5.1 MB/s, p95 was about
  17.6 MB/s, and max was about 37.5 MB/s. The capture did not yet have
  per-process network attribution, so this is a strong lead for the next
  benchmark rather than a named culprit.
- Offline correlation after the first analysis found that weak active minutes
  often overlapped with high outbound traffic and scheduler/interrupt churn:
  `22:25` averaged about 173.7 FPS with about 11.6 MiB/s sent, and `22:28`
  averaged about 179.5 FPS with about 18.3 MiB/s average / 35.7 MiB/s max
  sent. Nearby top non-Fortnite CPU bursts repeatedly included `firefox`,
  `dwm`, `SignalRgb`, `nextcloud`, `System`, and later `MedalEncoder`. This is
  not process-level network proof; use the next process-I/O-enabled capture to
  attribute it.
- Target thread sampling did not show one Fortnite thread permanently pinned at
  100%; the hottest sampled thread reached about 92% of one logical processor.
  The CPU-side issue is still real because PresentMon CPU busy stayed above the
  5 ms / 200 FPS budget, but the shape is frame-critical work plus
  scheduler/driver/background contention rather than a single always-maxed
  thread.
- Highest sampled non-Fortnite process pressure included `MedalEncoder`
  max 13.0% total CPU / 208% of one logical thread, `System` max 8.9% total,
  `nextcloud` max 7.1% total, `firefox` max 5.9% total, `dwm` max 4.6% total,
  and `SignalRgb` max 4.1% total. `Tracker.gg` remained low in sampled CPU.

Comparison and interpretation:

- This was substantially better than the earlier 2026-08-26 Game Mode run:
  gameplay-ish RTSS average improved from 174.2 FPS to 186.0 FPS, and full
  RTSS p99 frame time improved from about 602 ms to 13.16 ms.
- Johnny reported that this Rezon 1v1s result still felt wrong and should be
  much closer to locked 200 FPS. Treat that correction as authoritative for the
  workload expectation: shader-cache cleanup did not fix the active issue.
- It is still weaker than the June good baselines in raw near-cap behavior:
  June Go Goated gameplay-ish averaged 195.5 FPS, and the June Duo loaded
  gameplay-ish band averaged 196.5 FPS. Because Rezon 1v1s is a different map,
  treat that as a regression signal, not a direct map-for-map loss.
- The remaining issue is not thermals, RAM exhaustion, display mode capture
  validity, or a simple inability to approach 200 FPS. The data still points to
  frame-critical CPU work plus scheduler/driver/background churn, high
  outbound network activity during the run, and GPU load higher than the June
  baselines but not thermally limited.
- The requested follow-up was run on 2026-08-29 after closing Tracker.gg,
  Firefox, and Medal. See `2026-08-29 Rezon 1v1s Clean App-Isolation Capture`.

## 2026-08-29 Rezon 1v1s Clean App-Isolation Capture

Capture:

```text
C:\Users\jn\AppData\Local\WindowsGamingBenchmark\Captures\20260829-140742-fortnite-rezon-1v1s-clean-no-tracker-firefox-medal-20260829
```

Local archive/analyzed copy:

```text
/tmp/LJ-GAMING-PC-20260829-140742-fortnite-rezon-1v1s-clean-no-tracker-firefox-medal-20260829.zip
/tmp/LJ-GAMING-PC-20260829-140742-fortnite-rezon-1v1s-clean-no-tracker-firefox-medal-20260829
/tmp/LJ-GAMING-PC-20260829-140742-analysis.json
```

Context:

- Johnny closed Tracker.gg, Firefox, and Medal before this capture.
- Process inventory for the capture did not find `firefox`, `medal`, or
  `tracker` processes.
- Capture ran from `2026-08-29T14:07:42-05:00` to
  `2026-08-29T14:15:40-05:00`.
- No affinity, priority, or power-plan override was applied.
- Preflight recorded no warnings.
- Markers:
  - `loading-lobby-120fps-cap` at `2026-08-29T14:09:19-05:00`
  - `heavy-loading-fps-drops` at `2026-08-29T14:11:01-05:00`
  - `match-end-clean-rezon-1v1s` at `2026-08-29T14:14:46-05:00`
- The capture archive had no System/Application warning/error event rows.

Visible FPS and frame pacing:

- RTSS all rows: average 158.6 FPS, p50 197.8 FPS, p95 200.0 FPS, p99
  201.0 FPS. This all-window average is depressed by loading stalls and the
  120 FPS lobby/tail state; it is not the stable gameplay result.
- RTSS gameplay-ish `fps >= 140`: average 198.6 FPS, p50 199.8 FPS, p95
  200.2 FPS, p99 201.0 FPS. Frame-time p95 was 5.95 ms, p99 6.85 ms, max
  8.96 ms, with zero sampled rows over 16.67 ms.
- RTSS near-cap `fps >= 180`: average 199.0 FPS, p50 199.8 FPS, p95
  200.3 FPS, p99 201.0 FPS. Frame-time p99 was 6.85 ms and max was 8.96 ms.
- The best stable run from `14:10:48` through `14:14:02` averaged 198.7 FPS
  by RTSS, with p50 199.8 FPS and max sampled frame time 8.96 ms.
- PresentMon was in `Hardware: Independent Flip`. For the clean stable window
  from `14:10:48` through `14:13:59`, PresentMon frame time averaged 5.03 ms,
  CPU busy averaged 4.84 ms, and GPU busy averaged 2.04 ms. PresentMon still
  recorded a small number of >16.67 ms frames inside that stable window, but
  no >50 ms frames before the end-transition boundary.

Loading and transition stalls:

- The heavy loading issue is real and separate from the stable gameplay
  result. RTSS recorded 34 rows under 100 FPS or with >25 ms frame time.
- Early loading/launch from `14:07:48` through `14:09:05` averaged 109.7 FPS
  by RTSS with max sampled frame time 1,276.8 ms. A nearby system sample
  showed page-fault activity up to 493,802/sec and pages/sec around 49.8, but
  disk read/write latency counters stayed at 0.
- The pre-heavy-loading cluster from `14:10:20` through `14:10:48` averaged
  86.1 FPS by RTSS with max sampled frame time 1,319.3 ms. PresentMon for the
  same cluster averaged 12.91 ms frame time and 12.73 ms CPU busy, with GPU
  busy only 2.78 ms. That points to CPU/game-transition work with the GPU
  mostly waiting, not GPU saturation.
- The end transition around `14:14:03` through `14:14:08` also had severe
  sampled stalls before the capture settled into the 120 FPS lobby/tail.
- No Windows event-log warning/error rows, disk-latency spikes, or high
  outbound upload signal accompanied this clean capture. Network sent was
  negligible compared with the 2026-08-26 Rezon run.

Thermals and system pressure:

- MAHM CPU temperature averaged 65.3 C, p95 71.9 C, max 73.0 C. In the stable
  gameplay window, CPU temperature averaged about 64.3 C and maxed 68.9 C.
- CPU clocks stayed at 4,450 MHz in MAHM, and system CPU max utility p95 was
  92.6%.
- NVIDIA SMI GPU utilization averaged 36.9%, p95 41.6%, max 43%. GPU
  temperature maxed 47 C and VRAM used maxed about 1.75 GB.
- Context-switch and interrupt pressure were much lower than the 2026-08-26
  Rezon run: context switches p95 about 117k/sec versus 328k/sec, DPC p95
  1.84% versus 2.78%, interrupt p95 1.52% versus 4.85%.
- Memory state was healthy: available memory averaged 17.2 GB, commit averaged
  26.9 GB, and no preflight memory warnings were present.

Comparison and interpretation:

- Closing Tracker.gg, Firefox, and Medal produced a strong clean-condition win
  versus the 2026-08-26 Rezon capture. Gameplay-ish RTSS average improved from
  186.0 FPS to 198.6 FPS, and p50 improved from 188.2 FPS to 199.8 FPS.
- Near-cap RTSS average improved from 190.8 FPS to 199.0 FPS, and near-cap p99
  frame time improved from 9.94 ms to 6.85 ms.
- The old capture had high GPU utilization, high outbound upload, high
  scheduler/interrupt pressure, a Memory Compression preflight warning, and
  active Tracker/Firefox/Medal process presence. The clean run removed those
  app processes and the system-pressure profile improved substantially.
- This does not prove which one of Tracker.gg, Firefox, or Medal was the
  primary drag, because all three changed together. It does prove the clean
  condition can restore Rezon 1v1s stable gameplay to near the 200 FPS cap.
- Remaining issue: loading/transition stalls are still ugly. They look like
  CPU-side game/asset/session-transition stalls with GPU waiting, not a steady
  gameplay FPS ceiling, not thermals, not disk latency from the sampled
  counters, and not Windows event-log errors.
- Next controlled attribution path was revised by Johnny's workflow
  requirement: Firefox/stream viewing and Tracker.gg are expected to remain
  open. The Firefox + Tracker / no-Medal BR run is the desired-workflow
  baseline, and the follow-up added Medal on top of that state.

## 2026-08-29 BR Clean Follow-Up Capture

Capture:

```text
C:\Users\jn\AppData\Local\WindowsGamingBenchmark\Captures\20260829-145243-fortnite-br-clean-followup-queued-20260829
```

Local archive/analyzed copy:

```text
/tmp/LJ-GAMING-PC-20260829-145243-fortnite-br-clean-followup-queued-20260829.zip
/tmp/LJ-GAMING-PC-20260829-145243-fortnite-br-clean-followup-queued-20260829
/tmp/LJ-GAMING-PC-20260829-145243-analysis.json
```

Context:

- Johnny queued a BR match after the clean Rezon isolation test.
- Process inventory for the capture did not find `firefox`, `medal`, or
  `tracker` processes.
- Capture ran from `2026-08-29T14:52:43-05:00` to
  `2026-08-29T15:13:27-05:00`.
- No affinity, priority, or power-plan override was applied.
- Preflight had one warning: Memory Compression working set was about
  1606.8 MB while available memory was still about 16.6 GB.
- Markers:
  - `br-queue-lobby-120fps-cap` at `2026-08-29T14:53:14-05:00`
  - `br-match-finished` at `2026-08-29T15:13:14-05:00`
- The capture archive had no System/Application warning/error event rows.

Visible FPS and frame pacing:

- RTSS all rows averaged 194.8 FPS with p50 199.8 FPS, p95 200.8 FPS, and
  p99 201.0 FPS. The all-window average is pulled down by lobby/transition
  state rather than by sustained gameplay.
- RTSS gameplay-ish `fps >= 140`: average 198.7 FPS, p50 199.8 FPS, p95
  200.8 FPS, p99 201.0 FPS. Frame-time p95 was 6.74 ms, p99 was 8.11 ms,
  max sampled frame time was 23.68 ms, and only one sampled row exceeded
  16.67 ms.
- RTSS near-cap `fps >= 180`: average 199.1 FPS, p50 199.8 FPS, p95
  200.8 FPS, p99 201.0 FPS. Frame-time p99 was 7.79 ms and max was
  23.68 ms.
- The best stable run from `15:01:39` through `15:12:41` averaged 199.1 FPS
  by RTSS, with p50 199.8 FPS and p99 frame time 7.69 ms.
- A 120 FPS tail was detected from `15:12:51` through the stop marker. Treat
  that as lobby/sleep/end state, not active BR gameplay.

PresentMon and frame-pipeline data:

- PresentMon was in `Hardware: Independent Flip` for 240,577 rows, so this
  capture's PresentMon frame-pipeline data is usable.
- PresentMon all-window frame time averaged 5.14 ms, p50 5.01 ms, p95
  6.89 ms, p99 8.66 ms, and p99.9 15.15 ms. The max 2692.95 ms frame lines up
  with the end-transition cluster rather than stable fighting.
- PresentMon CPU busy averaged 4.94 ms, p95 6.66 ms, and p99 8.48 ms.
  GPU busy averaged 2.57 ms, p95 3.60 ms, and p99 4.26 ms.
- Interpretation: Fortnite is still CPU-frame-path dominant for 200 FPS, but
  in this clean BR run the CPU path was usually inside the 5 ms budget.

Transition stalls:

- RTSS recorded 7 low/stall rows under 100 FPS. One was early around
  `14:53:45`; the rest clustered from `15:12:42` through `15:12:48`, before
  the 120 FPS tail.
- The worst RTSS/PresentMon frame was about 2693 ms at the end transition.
  PresentMon showed CPU busy about 2693 ms, GPU busy only about 13.7 ms, and
  GPU wait about 2679 ms for that frame.
- This points to game/session-transition or CPU-side stall behavior with the
  GPU waiting, not GPU saturation.

Thermals and system pressure:

- MAHM CPU temperature averaged 73.0 C, p95 75.9 C, p99 77.7 C, and maxed
  79.6 C. CPU clock averaged 4449.7 MHz and p95 was 4450 MHz.
- NVIDIA GPU utilization averaged 44.9%, p95 56.1%, and maxed 61%. GPU
  temperature maxed 59 C, VRAM used maxed about 2.0 GB, and PCIe stayed at
  Gen4 x16.
- System CPU total utility averaged 59.1%, while max logical CPU utility p95
  was 97.8%. Fortnite target-thread sampling repeatedly showed one hot thread
  around 96-104% of a logical processor.
- Disk read latency p95 was 0.41 ms and write latency was negligible.
  Network send averaged about 17 KB/sec and receive about 32 KB/sec, with no
  high-upload signature like the 2026-08-26 Rezon run.
- The only pollution/preflight signal was Memory Compression working set over
  1 GB. It did not coincide with low available memory or a Resource Exhaustion
  event in this capture.

Comparison and interpretation:

- This clean BR run supports the same conclusion as the clean Rezon run:
  without the earlier app/background pressure, stable Fortnite gameplay can
  ride the 200 FPS cap again.
- The remaining performance issue shown here is not a steady BR FPS ceiling,
  GPU saturation, disk latency, network upload, thermal throttling, or an
  obvious non-Fortnite process spike.
- The remaining measured pain is transition/loading/end-state stutter. Keep
  separating transition markers from fighting markers in future captures so
  load/return-to-lobby hitches do not pollute gameplay averages.
- Next controlled attribution path follows Johnny's workflow requirement:
  Firefox/stream viewing and Tracker.gg are expected to remain open. The
  Firefox + Tracker / no-Medal BR run is the desired-workflow baseline, and
  the follow-up added Medal on top of that state.

## 2026-08-29 BR Firefox + Tracker / No-Medal Attribution Capture

Capture:

```text
C:\Users\jn\AppData\Local\WindowsGamingBenchmark\Captures\20260829-153121-fortnite-br-firefox-tracker-no-medal-20260829
```

Local archive/analyzed copy:

```text
/tmp/LJ-GAMING-PC-20260829-153121-fortnite-br-firefox-tracker-no-medal-20260829.zip
/tmp/LJ-GAMING-PC-20260829-153121-fortnite-br-firefox-tracker-no-medal-20260829
/tmp/LJ-GAMING-PC-20260829-153121-analysis.json
```

Context:

- Johnny opened Firefox and Tracker.gg before loading the next BR match.
- Medal and MedalEncoder were absent in the structured process aggregate.
- Capture ran from `2026-08-29T15:31:21-05:00` to
  `2026-08-29T15:47:26-05:00`.
- No affinity, priority, or power-plan override was applied.
- Preflight had one warning: Memory Compression working set was about
  1447.1 MB while available memory was about 14.1 GB.
- Process-inventory pollution also flagged Memory Compression, maxing at about
  1509.7 MB working set.
- Markers:
  - `br-loading-firefox-tracker-no-medal-20260829` at
    `2026-08-29T15:31:39-05:00`
  - `br-match-1-death-loading-next-firefox-tracker-no-medal-20260829` at
    `2026-08-29T15:34:27-05:00`
  - `br-match-2-done-firefox-tracker-no-medal-20260829` at
    `2026-08-29T15:47:09-05:00`
- The capture archive had no System/Application warning/error event rows.

Visible FPS and frame pacing:

- RTSS all rows averaged 182.4 FPS, p50 197.8 FPS, p95 200.0 FPS, and
  p99 201.0 FPS. The all-window average is heavily pulled down by load,
  death/return, next-load, and end clusters.
- RTSS gameplay-ish `fps >= 140`: average 195.1 FPS, p50 198.0 FPS, p95
  200.0 FPS, p99 201.0 FPS. Frame-time p95 was 7.36 ms, p99 was 8.80 ms,
  max sampled frame time was 26.09 ms, and only one sampled row exceeded
  16.67 ms.
- RTSS near-cap `fps >= 180`: average 197.0 FPS, p50 198.0 FPS, p95
  200.0 FPS, p99 201.0 FPS. Frame-time p99 was 8.69 ms and max was
  26.09 ms.
- The best stable run from `15:39:50` through `15:44:49` averaged 197.8 FPS
  by RTSS, with p99 frame time 8.53 ms, max sampled frame time 12.94 ms, and
  zero sampled rows over 16.67 ms.

PresentMon and frame-pipeline data:

- PresentMon was in `Hardware: Independent Flip` for 164,372 rows, so this
  capture's PresentMon frame-pipeline data is usable.
- PresentMon all-window frame time averaged 5.83 ms, p50 5.16 ms, p95
  9.70 ms, p99 13.20 ms, and p99.9 30.13 ms. The max 3096.80 ms frame was
  transition/load behavior, not clean fighting.
- PresentMon CPU busy averaged 5.61 ms, p95 9.47 ms, and p99 12.91 ms.
  GPU busy averaged 3.72 ms, p95 5.14 ms, and p99 5.81 ms.
- Interpretation: this run had more CPU-frame-path pressure and more GPU work
  than clean BR, but it still had long stretches near the 200 FPS cap.

Transition stalls:

- RTSS recorded 28 low/stall rows under 100 FPS or over 25 ms, compared with
  7 in the clean BR run.
- Most low/stall rows clustered around:
  - initial load: `15:31:51` through `15:31:58`
  - match-1 death/return: `15:34:07` through `15:34:14`
  - next-load/start: `15:34:43` through `15:34:49`
  - end/return: `15:46:50` through `15:46:56`
- The only near-gameplay sampled hitch outside those clusters was around
  `15:35:36-15:35:37`, where RTSS recorded one 26.09 ms frame and the next
  sample's rolling FPS dipped.

Thermals, system pressure, and process attribution:

- MAHM CPU temperature averaged 76.4 C, p95 78.5 C, and maxed 80.1 C. CPU
  clock stayed effectively pegged near 4,450 MHz.
- NVIDIA GPU utilization averaged 65.0%, p95 79.0%, and maxed 80%, versus
  44.9% average and 61% max in clean BR. GPU temperature maxed 60 C and VRAM
  used maxed about 2.6 GB.
- RAM usage averaged about 19.4 GB and maxed about 19.9 GB, versus about
  16.8 GB average and 17.2 GB max in clean BR.
- Context switches averaged about 138k/sec and p95 was about 152k/sec, versus
  111k/sec average and 122k/sec p95 in clean BR.
- Network receive averaged about 3.5 MB/sec and maxed about 39.2 MB/sec.
  Network send averaged about 154 KB/sec and maxed about 2.55 MB/sec. This is
  far above clean BR and is consistent with active browser/app media traffic.
- Disk read/write latency stayed low and no event-log warnings/errors were
  captured.
- Firefox appeared repeatedly in top-process samples, maxing at about 5.5%
  total CPU and about 87.8% of one logical CPU in the sampler's normalized
  metric. Tracker.gg appeared only lightly in top-process samples, maxing at
  about 0.6% total CPU. Medal and MedalEncoder were absent from the structured
  aggregate.

Comparison and interpretation:

- Compared with clean BR, Firefox + Tracker without Medal is measurably worse:
  gameplay-ish RTSS average fell from 198.7 FPS to 195.1 FPS, near-cap average
  fell from 199.1 FPS to 197.0 FPS, and transition/stall rows rose from 7 to
  28.
- This capture does not prove Medal is the cause of the regression because a
  weaker result happened with Medal absent. It does, however, create the right
  no-Medal baseline for Johnny's desired workflow, where Firefox stream viewing
  and Tracker.gg remain open.
- The strongest signal in this run is active browser/app load: higher GPU
  utilization, higher RAM use, higher network traffic, higher context switches,
  and recurring Firefox CPU samples. Tracker.gg did not show enough CPU in
  top-process samples to be the obvious primary cause here, but it still needs
  its own split test because it was changed together with Firefox.
- Next controlled test was completed in
  `2026-08-29 BR Firefox + Tracker + Medal Attribution Capture`. Firefox-only
  or Tracker-only splits remain useful only if future evidence still points at
  app overhead after the Medal result below.

## 2026-08-29 BR Firefox + Tracker + Medal Attribution Capture

Capture:

```text
C:\Users\jn\AppData\Local\WindowsGamingBenchmark\Captures\20260829-155557-fortnite-br-firefox-tracker-medal-attribution-20260829
```

Local archive/analyzed copy:

```text
/tmp/LJ-GAMING-PC-20260829-155557-fortnite-br-firefox-tracker-medal-attribution-20260829.zip
/tmp/LJ-GAMING-PC-20260829-155557-fortnite-br-firefox-tracker-medal-attribution-20260829
/tmp/LJ-GAMING-PC-20260829-155557-analysis.json
```

Context:

- Johnny loaded another BR match after the Firefox + Tracker / no-Medal
  baseline.
- Firefox, Tracker.gg, Medal, and MedalEncoder were present in this capture.
- Capture ran from `2026-08-29T15:55:57-05:00` to
  `2026-08-29T16:11:17-05:00`.
- No affinity, priority, or power-plan override was applied.
- Preflight had one warning: Memory Compression working set was about
  1436.0 MB while available memory was about 12.6 GB.
- Process-inventory pollution also flagged Memory Compression, maxing at about
  1756.0 MB working set.
- Markers:
  - `br-loading-firefox-tracker-medal-attribution-20260829` at
    `2026-08-29T15:56:16-05:00`
  - `br-match-done-firefox-tracker-medal-attribution-20260829` at
    `2026-08-29T16:11:03-05:00`
- The capture archive had no System/Application warning/error event rows.

Visible FPS and frame pacing:

- RTSS all rows averaged 190.1 FPS, p50 198.8 FPS, p95 200.0 FPS, and
  p99 200.8 FPS. The all-window average is pulled down by initial load and
  end/return clusters.
- RTSS gameplay-ish `fps >= 140`: average 196.7 FPS, p50 198.8 FPS, p95
  200.0 FPS, p99 200.8 FPS. Frame-time p95 was 7.45 ms, p99 was 8.88 ms,
  max sampled frame time was 11.84 ms, and zero sampled rows exceeded
  16.67 ms.
- RTSS near-cap `fps >= 180`: average 197.5 FPS, p50 198.8 FPS, p95
  200.0 FPS, p99 200.8 FPS. Frame-time p99 was 8.83 ms and max was
  11.72 ms.
- The best stable run from `15:56:53` through `16:10:34` averaged 197.3 FPS
  by RTSS for about 13.7 minutes, with p99 frame time 8.68 ms, max sampled
  frame time 11.72 ms, and zero sampled rows over 16.67 ms.

PresentMon and frame-pipeline data:

- PresentMon was in `Hardware: Independent Flip` for 152,069 rows, so this
  capture's PresentMon frame-pipeline data is usable.
- PresentMon all-window frame time averaged 6.00 ms, p50 5.22 ms, p95
  10.69 ms, p99 12.63 ms, and p99.9 23.80 ms. The max 2990.43 ms frame was
  end/return behavior, not clean fighting.
- PresentMon CPU busy averaged 5.77 ms, p95 10.45 ms, and p99 12.37 ms.
  GPU busy averaged 3.72 ms, p95 5.21 ms, and p99 5.82 ms.

Transition stalls:

- RTSS recorded 17 low/stall rows under 100 FPS or over 25 ms, compared with
  28 in the Firefox + Tracker / no-Medal run and 7 in clean BR.
- Low/stall rows clustered around:
  - initial load: `15:56:04` through `15:56:09`
  - end/return: `16:10:35` through `16:10:47`
- No sampled gameplay-ish rows exceeded 16.67 ms in this run.

Thermals, system pressure, and process attribution:

- MAHM CPU temperature averaged 78.1 C, p95 80.4 C, and maxed 83.2 C. CPU
  clock stayed near 4,450 MHz.
- NVIDIA GPU utilization averaged 72.3%, p95 88.0%, and maxed 92%, versus
  65.0% average and 80% max in the Firefox + Tracker / no-Medal run. GPU
  temperature maxed 61 C and VRAM used maxed about 3.3 GB.
- RAM usage averaged about 20.9 GB and maxed about 22.5 GB, versus about
  19.4 GB average and 19.9 GB max in the no-Medal baseline.
- Context switches averaged about 151k/sec and p95 was about 161k/sec, versus
  138k/sec average and 152k/sec p95 in the no-Medal baseline.
- Network receive averaged about 0.93 MB/sec and maxed about 5.0 MB/sec,
  which is much lower than the no-Medal run's 3.5 MB/sec average and
  39.2 MB/sec max. Treat the browser/media workload as not perfectly matched.
- Firefox appeared repeatedly in top-process samples, maxing at about 7.3%
  total CPU and about 116% of one logical CPU in the sampler's normalized
  metric.
- Tracker.gg appeared lightly in top-process samples, maxing at about 0.6%
  total CPU.
- MedalEncoder appeared in top-process samples, maxing at about 3.0% total
  CPU and about 47% of one logical CPU. In process inventory, MedalEncoder
  maxed around 826 MB private memory and 413 MB working set.
- Medal itself appeared lightly in top-process samples, maxing at about 0.6%
  total CPU and about 367 MB working set.

Comparison and interpretation:

- Compared with the desired-workflow no-Medal baseline, adding Medal did not
  produce a clear active-gameplay FPS regression. Gameplay-ish RTSS average
  moved from 195.1 FPS to 196.7 FPS, near-cap average moved from 197.0 FPS to
  197.5 FPS, and sampled gameplay rows over 16.67 ms moved from 1 to 0.
- The Medal run still had higher RAM usage, GPU utilization, VRAM use, CPU
  temperature, and context switches. Medal/MedalEncoder therefore have
  measurable cost, but this capture does not support them being the major
  reason Fortnite fails to hold the 200 FPS cap during actual fighting.
- Because network receive was much lower in the Medal-added run, the browser
  stream/media workload was not identical. If this needs a stricter ruling,
  repeat A/B with the same Firefox stream quality/tab state and the same match
  type, alternating no-Medal and Medal.
- Current practical conclusion: for Johnny's preferred workflow, Medal is not
  proven to be the culprit from this capture. Keep watching for memory growth
  and encoder/overlay spikes, but shift the next investigation toward stream
  media load consistency, OBS/recording/streaming interaction, transition
  stutter separation, and preflight bad-state detection.

## 2026-08-29 Benchmark Preflight Hardening

The managed benchmark harness now records top memory consumers before capture
start and flags large private/commit-memory consumers separately from normal
Windows reserved virtual address space. It also captures recent
`Microsoft-Windows-Resource-Exhaustion-Detector` event ID 2004 rows so the
earlier Firefox low-virtual-memory failure is visible before a benchmark starts.

Validation notes:

- A first live preflight using raw `Win32_Process.VirtualSize` produced hundreds
  of false warnings because normal 64-bit, Electron, UWP, and system processes
  reserve very large address ranges.
- The implemented check was corrected to threshold private memory and
  pagefile-backed commit instead. Resource Exhaustion Detector event text
  remains the source of truth for Windows-reported low virtual memory.
- Corrected preflight at `2026-08-29T16:32:02-05:00` produced 16 rows and 3
  warnings: Memory Compression at 1268.8 MB working set plus the two earlier
  Resource Exhaustion Detector events from `13:39:53` and `13:44:58`.
- Current top process memory rows were not large enough to trip the private or
  commit thresholds: Fortnite was about 3.9 GB private/commit, Xbox app about
  2.6 GB, the largest current Firefox content process about 1.0 GB, and
  MedalEncoder about 805 MB current with a 9.4 GB peak.

## 2026-08-29 Reload Normal Workflow Capture

Capture:
`20260829-164037-fortnite-reload-normal-workflow-20260829`.

Local artifacts:

- Archive:
  `/tmp/LJ-GAMING-PC-20260829-164037-fortnite-reload-normal-workflow-20260829.zip`
- Analysis:
  `/tmp/LJ-GAMING-PC-20260829-164037-analysis.json`

Scope and reliability:

- Capture started at `2026-08-29T16:40:37-05:00` while Johnny was already in a
  Reload session.
- The sampler failed at `2026-08-29T17:18:17-05:00` before Johnny's
  Reload-to-BR update at about `17:19`, so this artifact should be treated as a
  Reload-only capture.
- Stop was requested later at `2026-08-29T18:15:43-05:00`, but no samples were
  collected between the sampler failure and stop. There is no valid long
  120-FPS lobby tail to trim in this artifact.
- The failure was a benchmark harness bug: process I/O deltas above Int32 range
  made PowerShell choose the wrong `[math]::Max()` overload. The harness was
  fixed to use double zeros for those comparisons.
- The sampler failure also left the capture-owned PresentMon process holding
  `presentmon-console.csv`. The harness stop path was fixed to clean up
  capture-owned PresentMon processes by recorded PID and matching output path.
- The local analyzer now surfaces `benchmark_sampler_failure` from
  `benchmark.log` so this kind of truncated capture is obvious in the JSON.
- Fix validation used smoke capture
  `20260829-182323-benchmark-sampler-overflow-smoke-20260829`. It collected
  44 combined rows and 6018 PresentMon rows, reported no
  `benchmark_sampler_failure`, observed normal sampler exit, and `stop --fetch`
  completed without the prior `presentmon-console.csv` lock failure.

Metrics before the sampler failure:

- Visible FPS source was RTSS.
- All sampled RTSS rows averaged 185.0 FPS, p50 194.9 FPS, p95 199.8 FPS.
  This all-window number includes Reload transitions/stalls.
- Gameplay-ish `fps >= 140` rows averaged 191.2 FPS, p50 195.1 FPS, p95
  200.0 FPS, p99 frame time 10.33 ms, max sampled gameplay-ish frame time
  30.24 ms, with one sampled row over 16.67 ms.
- Near-cap `fps >= 180` rows averaged 194.5 FPS, p50 196.1 FPS, p99 frame time
  9.85 ms, with one sampled row over 16.67 ms.
- Best stable windows included about 196.2 FPS for `16:48:08-16:53:46`,
  195.4 FPS for `16:58:41-17:03:32`, and 194.4 FPS for `17:12:34-17:18:08`.
- PresentMon used `Hardware: Independent Flip` throughout the captured window.
- PresentMon/diagnosis still showed CPU-frame-time dominance: average CPU busy
  6.00 ms versus GPU busy 3.53 ms.
- Max logical CPU utility p95 was 114.9%, context-switch p95 was about
  179,943/sec, NVIDIA GPU utilization p95 was 78%, and no System/Application
  event-log warning/error rows were captured.
- CPU temperature from MAHM averaged 78.5 C, p95 80.4 C, p99 81.4 C, and max
  85.0 C during the captured window.
- Preflight warnings were Memory Compression at 1242.6 MB working set and one
  earlier Resource Exhaustion Detector event still inside the 180-minute
  lookback. Available memory stayed healthy, with minimum sampled available
  memory about 12.5 GB.
- Highest non-Fortnite sampled pressure included `MedalEncoder` max 7.6% total
  CPU and high I/O deltas, Firefox max 5.4% total CPU, and `OneDrive.Sync.Service`
  with a large read burst. The process I/O counters are not direct network
  attribution.

Interpretation:

- This capture is useful for Reload behavior before `17:18`, but it cannot
  answer the BR question because the sampler had already died before BR.
- The active gameplay rows were mostly playable and frequently near cap, but
  this was weaker than the clean BR and Medal-added BR captures. Treat that as
  mode/workload evidence, not proof that the normal app stack broke BR again.
- The persistent bottleneck signal remains CPU frame time / hot logical CPU /
  scheduler churn, with no GPU saturation and no event-log driver fault in this
  artifact.

## 2026-08-29 Ranked BR SignalRGB-App-Disabled Capture

Capture:
`20260829-200143-fortnite-ranked-br-signalrgb-disabled-20260829`.

Local artifacts:

- Archive:
  `/tmp/LJ-GAMING-PC-20260829-200143-fortnite-ranked-br-signalrgb-disabled-20260829.zip`
- Analysis:
  `/tmp/LJ-GAMING-PC-20260829-200143-analysis.json`

Scope and reliability:

- Capture started at `2026-08-29T20:01:43-05:00` and stopped at
  `2026-08-29T22:03:50-05:00`.
- The sampler did not crash; `benchmark.log` had no analyzer-detected failures.
- Johnny later said he forgot to mark the match end and had been sitting in the
  lobby for a while. The corrected final-tail detector found the last RTSS
  sample above 130 FPS at `2026-08-29T21:02:11-05:00`, then a final
  120-FPS tail from `21:02:12` through stop. The final tail lasted about
  61.6 minutes and had a 99.5% capped-sample ratio.
- Do not compare the untrimmed all-window FPS to gameplay captures. The
  all-window average was pulled down to 139.3 FPS by the long lobby tail and
  transition/stall rows.

Process-presence caveat:

- The capture was explicitly marked
  `workflow-caveat-signalrgb-disabled-user-confirmed`.
- `process_presence.notable` showed the SignalRGB app absent, but
  `SignalRgbService.exe` present.
- Other notable missing groups were OBS, Nextcloud, iCUE, Sonobus, and Kovaak's.
- Present groups included Fortnite, Firefox, Tracker.gg, Medal/MedalEncoder,
  Discord, Steam, Epic Games Launcher, Rockstar/SocialClub, Xbox/Game Bar,
  SteelSeries/Sonar, OneDrive, NVIDIA overlay, RTSS/Afterburner, and Memory
  Compression.
- Because process presence differs from earlier "normal workflow" captures,
  state this delta before making performance claims. The absence of SignalRGB
  is not the whole issue; the comparison guard is that all notable app-state
  differences must be considered first.
- Follow-up on `2026-08-30` found Nextcloud was genuinely not running, not an
  analyzer grouping miss. The raw capture CSVs had zero Nextcloud rows, the
  live Windows process list had no Nextcloud process, and the HKCU Run entry
  still pointed at `C:\Program Files\Nextcloud\nextcloud.exe`.
- Nextcloud's newest client log stopped at about `2026-08-29T13:40:02-05:00`
  with repeated CFAPI virtual-file errors against `Media/Medal/Imports/*.mp4`:
  "The cloud operation cannot be performed on a file with incompatible
  hardlinks." Windows Application event ID 1000 then recorded
  `nextcloud.exe` version `34.0.2.10195` faulting in `ucrtbase.dll` at
  `2026-08-29T13:40:08-05:00` with exception `0xc0000409`.
- Performance Mode was not the cause of the missing Nextcloud process. Its
  live state was inactive, with the last recorded exit on `2026-06-17`, and
  the log showed no August 29 close/enforce entries for Nextcloud.
- Interpretation: Nextcloud likely crashed during the earlier low-virtual-memory
  / Medal hardlink placeholder-error window, then stayed absent because the
  HKCU startup entry only starts it at login and does not respawn a crashed
  desktop client.
- Follow-up on `2026-08-30T14:52:17-05:00` confirmed the disabled Medal
  imports are not creating new import clips, but the stale import folder is
  still a live Nextcloud problem. `C:\Users\jn\Nextcloud\Media\Medal\Imports`
  had 120 files, about 5.6 GB, no files modified in the prior 24 hours, and
  newest file time `2026-08-23T18:24:07-05:00`; the five newest sampled import
  MP4s still had `LinkCount=2`, linking each file to both
  `C:\Users\jn\AppData\Local\Temp\Highlights\Fortnite` and the Nextcloud
  imports path.
- The same probe showed fresh Nextcloud client log pressure in the prior three
  hours: 376 `incompatible hardlinks` lines, 752 placeholder-conversion
  failures, 2449 `Media/Medal/Imports` lines, and the last hardlink/placeholder
  failure at `2026-08-30T14:46:52-05:00`. Treat the stale imports as still
  capable of breaking Nextcloud sync and adding background churn until the
  hardlinked import debris is cleaned or moved out of the sync root.
- Medal's normal completed clips are a separate path from the broken imports:
  the five newest sampled `Media\Medal\Clips\Fortnite` MP4s were ordinary
  single-link files (`LinkCount=1`), not hardlinks. However,
  `C:\Users\jn\Nextcloud\Media\Medal\Temp\RecordingBuffer` was actively
  changing under Nextcloud during the probe, with 329 files, about 3.3 GB, and
  newest write time `2026-08-30T14:52:12-05:00`. That makes Medal's live
  recording buffer inside Nextcloud a current performance/sync noise source
  even if the old import feature is disabled.
- Current recommendation before the next strict benchmark: move Medal's active
  recording buffer and working clip output outside `C:\Users\jn\Nextcloud`,
  then copy or move completed clips into Nextcloud after the game/session is
  idle. Separately clean the stale `Media\Medal\Imports` hardlinks after
  approval. Do not treat the disabled import setting alone as sufficient.

Tail-trimmed metrics:

- Visible FPS source was RTSS.
- Before the final lobby tail, all RTSS rows from `20:01:58` to `21:02:11`
  averaged 159.7 FPS with p50 185.0 FPS. This includes loading, transition,
  and stall samples, so it is not the clean gameplay number.
- Before the final lobby tail, gameplay-ish `fps >= 140` rows averaged
  192.3 FPS, p50 196.8 FPS, p95 200.0 FPS, p99 frame time 11.43 ms, max
  sampled gameplay-ish frame time 123.91 ms, with 6 rows over 16.67 ms.
- Before the final lobby tail, near-cap `fps >= 180` rows averaged 195.5 FPS,
  p50 197.0 FPS, p95 200.0 FPS, p99 frame time 10.05 ms, max frame time
  24.96 ms, with 3 rows over 16.67 ms.
- Longest gameplay-ish runs included:
  - `20:17:06-20:29:23`: 12.3 minutes, 194.0 FPS average, p99 frame 9.56 ms,
    one row over 16.67 ms.
  - `20:35:48-20:42:56`: 7.1 minutes, 197.0 FPS average, p99 frame 8.30 ms,
    zero rows over 16.67 ms.
  - `20:57:54-21:02:11`: 4.3 minutes, 191.1 FPS average, p99 frame 9.98 ms,
    zero rows over 16.67 ms.

System and process interpretation:

- PresentMon used `Hardware: Independent Flip` throughout the capture and did
  not show a visible-FPS mismatch in the analyzer.
- The diagnosis remained CPU-frame-time dominant: PresentMon average CPU busy
  was 6.97 ms versus GPU busy 3.32 ms.
- Max logical CPU utility p95 was 109.2% and context-switch p95 was about
  168,734/sec. This again points to a hot frame-critical CPU path plus
  scheduler churn even when total CPU usage is moderate.
- NVIDIA GPU utilization p95 was 74% and GPU temperature maxed 61 C. This was
  not a GPU-saturation capture.
- CPU temperature from MAHM averaged 70.7 C, p95 77.8 C, p99 79.1 C, and max
  81.4 C, which is materially cooler than the earlier low-80s captures.
- Preflight recorded Memory Compression at 2298.1 MB, and process inventory
  later saw Memory Compression up to 3641.4 MB. Available memory remained
  healthy in system counters, with minimum sampled available memory about
  9.6 GB, so this is a captured warning rather than proof of active RAM
  starvation.
- Highest non-Fortnite sampled process pressure included Discord max 9.5%
  total CPU, Firefox max 6.7%, MedalEncoder max 4.5%, OneDrive Sync max 3.4%,
  audiodg max 3.3%, and DWM max 2.6%. Process I/O deltas were largest for
  Fortnite, MedalEncoder, OneDrive Sync, and Firefox; these are not direct
  per-process network counters.

Conclusion:

- After trimming the final lobby tail, this ranked BR run is playable and often
  near the 200 FPS cap, but weaker than the clean BR and shorter desired-workflow
  Medal attribution capture. Because it is longer ranked BR and has different
  process presence, do not use it as proof that any single app helped or hurt.
- The durable performance signal is still CPU-frame-time pressure and a hot
  logical processor, not GPU saturation, disk latency, or an obvious single
  background process.

## CPU Upgrade Status

Johnny ordered a Ryzen 7 5700X3D, but the installed CPU is verified as a Ryzen 7 5800X3D. The BIOS, Windows WMI, and `HKLM:\HARDWARE\DESCRIPTION\System\CentralProcessor\0` all report `AMD Ryzen 7 5800X3D 8-Core Processor`. Treat the 5800X3D as the installed and benchmark-relevant CPU.

The upgrade is now benchmarked enough for the old raw-FPS investigation: after
BIOS A-XMP was restored and FCLK1600 was verified, Fortnite held near the 200 FPS
cap in multiple real/Creative captures. The remaining work is not proving the
5800X3D helped; it is validating stream/OBS interaction, thermal headroom, and
optional graphics/security A/B tests.

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

## 2026-06-13 Real-Round Thermal Check

Capture:

```text
C:\Users\jn\AppData\Local\WindowsGamingBenchmark\Captures\20260613-164633-fortnite-5800x3d-real-round-thermal-check
```

Local archive analyzed from:

```text
/tmp/LJ-GAMING-PC-20260613-164633-fortnite-5800x3d-real-round-thermal-check
/tmp/LJ-GAMING-PC-20260613-164633-fortnite-5800x3d-real-round-thermal-check.zip
```

Markers:

- `target-started-20264`: 2026-06-13 16:46:37 -05:00
- `round1-death-start-round2`: 2026-06-13 16:50:59 -05:00
- `stop-requested`: 2026-06-13 17:12:45 -05:00

Visible FPS:

- Full capture RTSS visible-FPS source: average 193.9 FPS, p50 199.8 FPS.
- Round 1 RTSS: average 180.5 FPS, p50 198.0 FPS, p5 110.5 FPS. Frame-time p99 was 28.0 ms, with four RTSS frame samples over 16.67 ms.
- Round 2 RTSS: average 196.6 FPS, p50 199.8 FPS, p5 193.9 FPS, p1 119.5 FPS. Frame-time p99 was 8.75 ms, with four RTSS frame samples over 16.67 ms.
- The largest round 2 RTSS spikes were near the end/stop window at 17:12:21-17:12:44, including one 410 ms sample and one 105 ms sample. Treat those as likely transition/stop-edge artifacts unless the user confirms they were in live combat.

Thermals and clocks:

- Round 1 MAHM CPU temperature: average 80.1 C, p95 82.1 C, p99 83.0 C, max 83.9 C.
- Round 2 MAHM CPU temperature: average 79.7 C, p95 82.4 C, p99 84.0 C, max 86.0 C.
- Round 2 hottest sample: 86.0 C at 16:54:07, CPU clock 4325 MHz, CPU power 92.45 W, RTSS/MAHM visible FPS still about 199 FPS.
- CPU clock stayed healthy: round 2 average 4406 MHz, p50 4400 MHz, p95/p99/max 4450 MHz, minimum 4300 MHz.
- CPU power stayed normal for load: round 2 average 82.4 W, p95 89.2 W, p99 92.5 W, max 96.4 W.
- GPU was not thermally constrained: round 2 NVIDIA GPU temperature average 59.7 C, max 62 C.

Other pressure signals:

- NVIDIA GPU utilization in round 2 averaged 64.1%, p95 76.9%, max 79.0%, so this capture does not show GPU saturation.
- Windows CPU max utility in round 2 p95 was 102.9%, and Fortnite target-thread samples repeatedly showed one hot thread around 80-89% of a logical processor. This still points to Fortnite CPU-thread pressure as the practical limiter even when total CPU usage looks moderate.
- Round 2 RAM usage from MAHM averaged 19.96 GB and peaked around 20.37 GB. Windows available memory stayed high, roughly 12.6 GB minimum, so this was not memory pressure.
- DPC/interrupt levels were not alarming in this run: round 2 p95 DPC 1.63%, p95 interrupt 2.24%.

PresentMon validity:

- PresentMon reported 42,410 rows of `Composed: Flip` and derived roughly 27 FPS while RTSS averaged roughly 194 FPS. For this capture, PresentMon visible FPS and per-frame CPU/GPU busy timing are not authoritative.
- The analyzer now flags this as `presentmon_composed_flip_visible_fps_mismatch` and suppresses PresentMon CPU/GPU busy bottleneck classification in this state.

Interpretation:

- No thermal throttling was observed. The 5800X3D did get warm, peaking at 86 C, but it stayed below the 90 C limit while clocks remained around 4.3-4.45 GHz and FPS stayed near the 200 FPS cap.
- The CPU fan-curve change appears adequate for now, but the chip is still running warm enough that cooler mount, radiator airflow, and fan behavior remain worth checking if future real-match captures approach 90 C or show clock drops.
- Performance in round 2 looked strong: mostly capped near 200 FPS, not GPU-saturated, and no sustained thermal throttle pattern.


## 2026-06-13 Go Goated Loaded Normal-Use Baseline

Capture:

```text
C:\Users\jn\AppData\Local\WindowsGamingBenchmark\Captures\20260613-205138-fortnite-5800x3d-go-goated-post-cleanup
```

Local archive analyzed from:

```text
/tmp/LJ-GAMING-PC-20260613-205138-fortnite-5800x3d-go-goated-post-cleanup
/tmp/LJ-GAMING-PC-20260613-205138-fortnite-5800x3d-go-goated-post-cleanup.zip
/tmp/LJ-GAMING-PC-20260613-205138-fortnite-5800x3d-go-goated-post-cleanup.analysis.v2.json
```

Conditions:

- CPU installed and verified as Ryzen 7 5800X3D.
- A-XMP restored; current baseline is DDR4-3200 / FCLK1600.
- Automatic Performance Mode had been retired before this capture. No watcher,
  OBS trigger, launcher close rules, or service stop rules were active.
- Johnny reported that normal gaming overlays/features were turned back on:
  NVIDIA Overlay, NVIDIA Instant Replay, NVIDIA Highlights, and Game Bar.
- Process inventory confirmed NVIDIA Overlay, Game Bar, GameBarPresenceWriter,
  Xbox app, Epic Games Launcher, Steam, Rockstar Launcher/Social Club, Discord,
  Nextcloud, and SignalRGB were present.
- OBS was not present in the watched process inventory; this is not a streaming
  or OBS-recording benchmark.
- No affinity, priority, or power-plan override was applied by the benchmark
  harness.

Markers:

- `start`: 2026-06-13 20:51:38 -05:00
- `target-started-28800`: 2026-06-13 20:51:47 -05:00
- `stop-requested`: 2026-06-13 22:01:50 -05:00

Important limitation: Johnny forgot to mark the end of Go Goated, and the run
continued into lobby/end-state time. Treat the all-window average as a mixed
session number, not a clean gameplay-only average. Use the RTSS visible-FPS
bands below to separate likely gameplay from 120 FPS capped lobby/menu periods
and transitions.

Visible FPS from RTSS/MAHM:

- Full mixed capture RTSS: average 184.3 FPS, p50 198.8 FPS, p95 200.0 FPS,
  p99 201.0 FPS.
- Full mixed capture RTSS frame time: p50 5.28 ms, p95 8.76 ms, p99 19.75 ms,
  max 2476 ms.
- The full mixed capture had 41 RTSS samples over 16.67 ms, 30 over 25 ms, 28
  over 33.33 ms, and 25 over 50 ms. Most of those were in transition/stall
  buckets, not the high-FPS gameplay buckets.
- Gameplay-ish RTSS band `fps >= 140`: average 195.5 FPS, p50 198.9 FPS, p95
  200.0 FPS, p99 201.0 FPS. Frame-time p95 was 7.09 ms, p99 9.02 ms, max
  22.54 ms, with 8 samples over 16.67 ms and none over 25 ms.
- Near-cap RTSS band `fps >= 180`: average 197.6 FPS, p50 199.0 FPS, p95
  200.0 FPS, p99 201.0 FPS. Frame-time p95 was 6.90 ms, p99 8.63 ms, max
  22.54 ms, with 8 samples over 16.67 ms and none over 25 ms.
- Longest contiguous `fps >= 140` run: 21:10:25-21:37:59, 1434 samples over
  about 27.6 minutes, average 199.3 FPS, p50 199.8 FPS, p99 201.0 FPS.
  Frame-time p95 was 6.30 ms, p99 7.35 ms, max 20.40 ms, with only 2 samples
  over 16.67 ms.
- The 100-130 FPS band averaged 117.8 FPS and lines up with the known lobby or
  capped context behavior.

Thermals and clocks:

- Full capture MAHM CPU temperature: average 78.3 C, p95 82.0 C, p99 86.2 C,
  max 90.25 C.
- Near-cap `fps >= 180` CPU temperature: average 78.2 C, p95 81.9 C, p99 84.1
  C, max 89.9 C.
- CPU clock stayed healthy: full capture average 4410 MHz, p50 4400 MHz,
  p95/p99/max 4450 MHz, minimum 4275 MHz.
- Near-cap `fps >= 180` CPU clock: average 4409 MHz, p95/p99/max 4450 MHz,
  minimum 4300 MHz.
- No sustained thermal-throttle pattern was observed, but the 5800X3D did touch
  the cHTC limit area. Keep monitoring fan curve, radiator airflow, and clocks
  if future sessions approach 90 C again.

Other pressure signals:

- NVIDIA GPU utilization averaged 59.1%, p95 82.0%, max 86.0%. GPU temperature
  averaged 58.3 C and maxed at 62 C.
- GPU VRAM use stayed modest: NVIDIA reported max 2767 MB used.
- RAM usage averaged 17.7 GB and peaked around 19.8 GB. Windows available
  memory stayed healthy with a 13.2 GB minimum.
- The analyzer flagged Memory Compression working set around 1.4-1.5 GB, but
  this did not coincide with system RAM pressure.
- No stale runaway PowerShell worker was detected in this capture.
- DPC/interrupt levels were not alarming: p95 DPC 1.85%, p95 interrupt 2.38%.
- Context switches were elevated enough to note, with p95 around 172,600/sec,
  but there was no single background app smoking gun.
- Steam, Nextcloud, NVIDIA Overlay, Game Bar/Xbox, Epic, Rockstar, Discord,
  SignalRGB, and Defender were present but not dominant CPU users. NVIDIA
  Overlay appeared in the process data with low sampled CPU, and disk latency
  was negligible.
- Windows GPU engine counters reported 0% video encode, which may be a counter
  visibility issue rather than proof that Instant Replay/Highlights were idle.
  Practically, this capture did not show encode/disk pressure hurting Fortnite.

PresentMon validity:

- PresentMon recorded 140,536 rows, but 140,517 were `Composed: Flip`; only 18
  were `Hardware: Independent Flip`.
- PresentMon-derived visible FPS averaged roughly 33.4 FPS while RTSS averaged
  184.3 FPS over the same mixed capture. Treat PresentMon visible FPS and
  CPU/GPU busy classification as suspect in this capture.
- Keep RTSS/MAHM as the authoritative visible-FPS and sensor source until
  PresentMon is captured in a mode that agrees with RTSS.

Interpretation:

- This is the strongest evidence so far that broad app-closing Performance Mode
  is no longer needed for normal Fortnite after the 5800X3D + XMP restore.
  Fortnite held near the 200 FPS cap in the high-FPS gameplay bands even with
  normal overlays, launchers, sync clients, Discord, Xbox/Game Bar, and
  SignalRGB present.
- The old 3900X-era raw-FPS problem should be considered solved for non-OBS
  Fortnite. Remaining performance work should focus on the real streaming/OBS
  path, thermal headroom, HAGS if the user wants a reboot-level A/B, and only
  then lower-priority security/render-mode tests.
- Do not reintroduce launcher/app/service killing without a new capture proving
  a specific process or service is causing stutter.

## 2026-06-13/14 Duo Loaded Normal-Use Capture

Capture:

```text
C:\Users\jn\AppData\Local\WindowsGamingBenchmark\Captures\20260613-230129-fortnite-duo-loaded-normal-20260613
```

Local archive analyzed from:

```text
/tmp/LJ-GAMING-PC-20260613-230129-fortnite-duo-loaded-normal-20260613
/tmp/LJ-GAMING-PC-20260613-230129-fortnite-duo-loaded-normal-20260613.zip
/tmp/LJ-GAMING-PC-20260613-230129-fortnite-duo-loaded-normal-20260613.analysis.v2.json
```

Conditions:

- CPU installed and verified as Ryzen 7 5800X3D.
- A-XMP restored; current baseline is DDR4-3200 / FCLK1600.
- Automatic Performance Mode remained retired. No watcher, OBS trigger,
  launcher close rules, or service stop rules were active.
- Johnny was playing with a duo/friend and forgot to mark the end of gameplay.
- Normal background apps/overlays were still present. Process inventory showed
  NVIDIA Overlay, Xbox app, Epic, Steam, Rockstar/Social Club, Discord,
  Nextcloud, SignalRGB, SteelSeries Sonar, and Defender.
- OBS was not present in the watched process inventory; this is not a streaming
  or OBS-recording benchmark.
- No affinity, priority, or power-plan override was applied by the benchmark
  harness.
- Preflight was allowed to start with a recorded warning because Memory
  Compression was already large while available RAM remained healthy.

Markers:

- `start`: 2026-06-13 23:01:29 -05:00
- `target-started-28800`: 2026-06-13 23:01:38 -05:00
- `target-exited-28800`: 2026-06-14 02:19:44 -05:00
- `stop-requested`: 2026-06-14 02:21:18 -05:00

Inferred session split:

- The analyzer detected a sustained 120 FPS cap tail beginning at
  2026-06-14 01:27:53 -05:00.
- Last active RTSS sample above 130 FPS before that tail:
  2026-06-14 01:27:44 -05:00 at 196.85 FPS.
- From 01:27:53 until Fortnite exited at 02:19:44, RTSS stayed in a
  115-125 FPS cap pattern. Treat that as lobby/sleep/end-state time, not
  gameplay.

Visible FPS from RTSS/MAHM:

- Full active RTSS window, including the 120 FPS tail: average 170.9 FPS,
  p50 196.9 FPS, p95 200.0 FPS, p99 201.0 FPS.
- Pre-tail window, 23:01:39-01:27:52: average 189.5 FPS, p50 198.8 FPS,
  p95 200.0 FPS, p99 201.0 FPS. This still includes some earlier lobby/load
  segments and transition stalls.
- Pre-tail gameplay-ish `fps >= 140`: average 196.5 FPS, p50 198.8 FPS,
  p95 200.4 FPS, p99 201.0 FPS. Frame-time p95 was 7.27 ms, p99 9.13 ms,
  max 22.17 ms, with 4 samples over 16.67 ms and none over 25 ms.
- Pre-tail near-cap `fps >= 180`: average 197.5 FPS, p50 198.8 FPS,
  p95 200.8 FPS, p99 201.0 FPS. Frame-time p95 was 7.16 ms, p99 8.83 ms,
  max 22.17 ms, with 2 samples over 16.67 ms and none over 25 ms.
- Longest contiguous `fps >= 140` run: 00:55:24-01:27:44, about 32.3 minutes,
  average 199.3 FPS, p50 199.8 FPS, p99 201.0 FPS. Frame-time p95 was 6.17 ms,
  p99 7.34 ms, max 15.00 ms, with zero samples over 16.67 ms.
- Inferred 120 FPS tail: average 119.9 FPS, p50 120.1 FPS, p95 120.2 FPS.

Thermals and clocks:

- Pre-tail window CPU temperature: average 78.3 C, p95 84.6 C, p99 85.4 C,
  max 89.5 C.
- Pre-tail `fps >= 140` CPU temperature: average 78.4 C, p95 84.6 C,
  p99 85.4 C, max 88.1 C.
- Pre-tail `fps >= 180` CPU temperature: average 78.3 C, p95 84.6 C,
  p99 85.3 C, max 88.0 C.
- Tail CPU temperature fell to average 69.5 C, p95 71.3 C, max 76.4 C.
- CPU clocks remained healthy: pre-tail `fps >= 180` averaged 4403 MHz with
  p95/p99/max 4450 MHz.
- No sustained thermal-throttle pattern was observed, but the chip still runs
  warm enough that fan curve/radiator airflow remain worth watching.

Other pressure signals:

- Pre-tail `fps >= 180` NVIDIA GPU utilization averaged 70.2%, p95 93.0%,
  p99 96.0%, max 97.0%. GPU temperature averaged 59.5 C and maxed at 65 C.
- RAM usage averaged about 18.7 GB in the pre-tail gameplay-ish windows.
  Windows available memory stayed healthy with a 13.2 GB minimum.
- Memory Compression was the only preflight/capture pollution warning:
  preflight working set 1566 MB, process-inventory max 1585 MB, watched-process
  max 3065 MB. Available RAM stayed healthy, so this was a warning to record,
  not proof of memory pressure.
- Context switches were elevated but similar to prior loaded captures:
  pre-tail `fps >= 180` p95 about 177,200/sec.
- DPC/interrupt levels were not alarming: pre-tail `fps >= 180` p95 DPC 2.04%,
  p95 interrupt 2.71%.
- Background apps were not dominant CPU users. Max sampled totals included
  Nextcloud 5.0%, Discord 3.7%, SignalRGB 2.5%, SteelSeries Sonar 1.8%,
  Epic Games Launcher 1.2%, and NVIDIA Overlay about 0.6%.

PresentMon validity:

- PresentMon recorded 539,797 rows, but 539,424 were `Composed: Flip`; only
  372 were `Hardware: Independent Flip`.
- PresentMon-derived visible FPS averaged roughly 45.5 FPS while RTSS averaged
  170.9 FPS over the full active capture. Treat PresentMon visible FPS and
  CPU/GPU busy classification as suspect for this capture.
- RTSS/MAHM remain the authoritative visible-FPS and sensor sources for this
  capture.

Interpretation:

- This reinforces the Go Goated result: normal Fortnite performance now holds
  near the 200 FPS cap with normal launchers, overlays, sync clients, Discord,
  Xbox/Game Bar, SignalRGB, and Sonar present.
- The old broad Performance Mode process/service shutdown remains unjustified
  for non-OBS Fortnite. Do not re-add it unless a future capture identifies a
  specific offender.
- Remaining work should focus on the real streaming/OBS path and optional HAGS
  testing, not more background-app cleanup.

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

Reason: Epic's current FPS troubleshooting page recommends enabling Hardware-accelerated GPU scheduling when available, but our current managed state disables it. Do not run this until the MPO re-enable test is complete; changing both at once would make the PresentMon/flip-mode result ambiguous.

Cost:

- Registry change
- Reboot required
- Needs A/B benchmark before and after

Test:

1. Baseline benchmark with current `HwSchMode=1`.
2. Confirm whether MPO is already restored to Windows default behavior and record the PresentMon mode result.
3. Set `HwSchMode=2`.
4. Reboot.
5. Repeat the same Fortnite benchmark.
6. Compare average FPS, 1% lows, 0.1% lows, PresentMon CPU busy/wait/GPU busy, and stutter markers.

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
