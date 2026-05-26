# Windows Templates

## Templates

- `windows-gaming-benchmark.ps1.j2`: Windows gaming benchmark runner.
- `windows-gaming-capture.ps1.j2`: Windows gaming capture helper.
- `windows-performance-mode.ps1.j2`: Performance mode controller.
- `windows-performance-watch.ps1.j2`: Performance watcher.
- `windows-performance-window-action.ps1.j2`: Foreground-window action helper.
- `windows-performance-run-hidden.vbs.j2`: Hidden runner wrapper.
- `obs-performance-mode.lua.j2`: OBS performance-mode trigger.
- `signalrgb-lock-state.ps1.j2`: SignalRGB lock-state helper.

## Consumers

- `playbooks/windows/windows-gaming-benchmark.yml`
- `playbooks/windows/windows-gaming-monitoring.yml`
- `playbooks/windows/windows-performance-mode.yml`
- `playbooks/windows/windows-signalrgb.yml`

## Safety Notes

- Do not launch visible Windows GUI apps through SSH/Ansible. Keep deployed
  local copies under `C:\ProgramData\Johnny\...` unless a playbook documents a
  different path.
