# Gaming Scripts

## Scripts

- `analyze-gaming-capture.py`: Parses local PresentMon/capture CSV data and
  summarizes frame-time and performance metrics. Run locally on fetched capture
  output, for example `python3 scripts/gaming/analyze-gaming-capture.py <path>`.

## Safety Notes

- Read-only; it analyzes supplied capture files and prints metrics.
- Prefer running locally on the controller instead of broad remote Windows
  analysis when the gaming PC is in use.
