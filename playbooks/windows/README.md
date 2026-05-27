# windows Playbooks

Owner area: Windows gaming workstation automation.

## Operating Notes

- Key vars: windows_gaming_*, windows_performance_mode_*, windows_signalrgb_*, gaming_benchmark_*, windows_streaming_*.
- Template owners: templates/windows.
- Script owners: scripts/gaming, scripts/streaming.
- Keep playbook metadata headers and `playbooks/README.md` in sync when behavior changes.

## Playbooks

| Playbook | Hosts | Purpose | Validation |
| --- | --- | --- | --- |
| `windows-gaming-benchmark.yml` | `localhost, windows_gaming_benchmark_targets` | Configure Windows gaming benchmark capture. | `ansible-playbook playbooks/windows/windows-gaming-benchmark.yml --syntax-check` |
| `windows-gaming-monitoring.yml` | `localhost, windows_gaming_monitoring_targets` | Configure Windows gaming monitoring. | `ansible-playbook playbooks/windows/windows-gaming-monitoring.yml --syntax-check` |
| `windows-gaming-tuning.yml` | `localhost, windows_gaming_tuning_targets` | Configure Windows gaming tuning and deploy streaming helpers. | `ansible-playbook playbooks/windows/windows-gaming-tuning.yml --syntax-check` |
| `windows-performance-mode.yml` | `localhost, windows_performance_mode_targets` | Configure Windows Performance Mode automation. | `ansible-playbook playbooks/windows/windows-performance-mode.yml --syntax-check` |
| `windows-signalrgb.yml` | `localhost, windows_signalrgb_targets` | Configure Windows SignalRGB lock and unlock automation. | `ansible-playbook playbooks/windows/windows-signalrgb.yml --syntax-check` |
