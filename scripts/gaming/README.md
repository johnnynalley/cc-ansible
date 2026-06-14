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
  Run locally on fetched capture output, for example
  `python3 scripts/gaming/analyze-gaming-capture.py <path>`.

## Safety Notes

- Read-only; it analyzes supplied capture files and prints metrics.
- Prefer running locally on the controller instead of broad remote Windows
  analysis when the gaming PC is in use.
