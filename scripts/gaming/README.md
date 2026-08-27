# Gaming Scripts

## Scripts

- `analyze-gaming-capture.py`: Parses local gaming benchmark CSV data and
  summarizes frame-time, sensor, process, and diagnosis metrics. When available,
  it treats RTSS/MAHM as the visible-FPS source and uses PresentMon for
  frame-pipeline details such as CPU/GPU busy time when the PresentMon cadence
  is valid for the capture. It also reports PresentMon presentation modes so
  composed-flip mismatch captures can be separated from independent-flip
  captures. The summary includes visible-FPS bands so lobby/menus, transition
  stalls, and near-cap gameplay can be separated without one-off analysis.
  It also detects a sustained 120 FPS cap tail, useful when a Fortnite capture
  continues into lobby/sleep mode after gameplay has ended. It reports process
  I/O deltas when the capture includes those columns and flags high system-wide
  outbound network traffic as a follow-up attribution lead. When `event-log.csv`
  is present, it summarizes warning/error event providers and flags likely
  Search, display-driver, WHEA, disk, and app-hang evidence.
  Run locally on fetched capture output, for example
  `python3 scripts/gaming/analyze-gaming-capture.py <path>`.
- `capture-wasapi-endpoint.ps1`: Records a short diagnostic WAV directly from
  one explicit Windows capture-endpoint ID by using shared-mode WASAPI. It does
  not change the default device or install an audio package. For privacy, use
  it only with the system owner's approval, write to a narrow temporary path,
  and remove the remote recording after the required analysis artifact has
  been fetched.

## Safety Notes

- `analyze-gaming-capture.py` is read-only; it analyzes supplied capture files
  and prints metrics.
- Prefer running locally on the controller instead of broad remote Windows
  analysis when the gaming PC is in use.
- Microphone capture records room audio and speech. Obtain explicit approval,
  bound the duration, keep the artifact private, and delete temporary remote
  copies after analysis.
