#!/usr/bin/env python3
import csv
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path


def fnum(value):
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.upper() == "NA":
        return None
    try:
        return float(text.replace(",", ""))
    except ValueError:
        return None


def percentile(sorted_values, pct):
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (pct / 100.0) * (len(sorted_values) - 1)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return sorted_values[lower]
    weight = rank - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight


def stats(values):
    values = [v for v in values if v is not None and math.isfinite(v)]
    if not values:
        return None
    sorted_values = sorted(values)
    return {
        "count": len(values),
        "avg": statistics.fmean(values),
        "min": sorted_values[0],
        "p50": percentile(sorted_values, 50),
        "p95": percentile(sorted_values, 95),
        "p99": percentile(sorted_values, 99),
        "p999": percentile(sorted_values, 99.9),
        "max": sorted_values[-1],
    }


def fps_lows_from_frame_ms(values):
    values = [v for v in values if v and v > 0 and math.isfinite(v)]
    if not values:
        return None
    sorted_values = sorted(values)
    avg_frame = statistics.fmean(values)
    p99 = percentile(sorted_values, 99)
    p999 = percentile(sorted_values, 99.9)
    return {
        "avg_from_frame_ms": 1000.0 / avg_frame,
        "1pct_low_from_p99_frame_ms": 1000.0 / p99 if p99 else None,
        "0_1pct_low_from_p999_frame_ms": 1000.0 / p999 if p999 else None,
        "min_from_max_frame_ms": 1000.0 / sorted_values[-1] if sorted_values[-1] else None,
    }


def counts_over(values, thresholds):
    return {str(t): sum(1 for v in values if v is not None and v > t) for t in thresholds}


def truthy(value):
    return str(value).strip().lower() in ("true", "1", "yes")


def read_csv(path):
    if not path.exists():
        return
    with open(path, newline="", encoding="utf-8-sig") as fh:
        yield from csv.DictReader(fh)


def read_json(path):
    if not path.exists():
        return None
    with open(path, encoding="utf-8-sig") as fh:
        return json.load(fh)


def parse_presentmon_time(text):
    if not text:
        return None
    base = str(text).split(".")[0]
    try:
        return datetime.strptime(base, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def parse_iso_time(text):
    if not text:
        return None
    try:
        return datetime.fromisoformat(str(text))
    except ValueError:
        return None


def summarize_presentmon_rows(rows):
    frame = [row["frame_ms"] for row in rows]
    cpu_busy = [row["cpu_busy_ms"] for row in rows]
    cpu_wait = [row["cpu_wait_ms"] for row in rows]
    gpu_time = [row["gpu_time_ms"] for row in rows]
    gpu_busy = [row["gpu_busy_ms"] for row in rows]
    gpu_wait = [row["gpu_wait_ms"] for row in rows]
    display_latency = [row["display_latency_ms"] for row in rows]
    frame_minus_gpu_busy = [
        row["frame_ms"] - row["gpu_busy_ms"]
        for row in rows
        if row["frame_ms"] is not None and row["gpu_busy_ms"] is not None
    ]
    return {
        "rows": len(rows),
        "frame_ms": stats(frame),
        "fps_lows": fps_lows_from_frame_ms(frame),
        "frame_over_ms_counts": counts_over(frame, [5, 6.67, 8.33, 10, 16.67, 25, 33.33, 50]),
        "cpu_busy_ms": stats(cpu_busy),
        "cpu_wait_ms": stats(cpu_wait),
        "gpu_time_ms": stats(gpu_time),
        "gpu_busy_ms": stats(gpu_busy),
        "gpu_wait_ms": stats(gpu_wait),
        "display_latency_ms": stats(display_latency),
        "frame_minus_gpu_busy_ms": stats(frame_minus_gpu_busy),
    }


def summarize_visible_samples(samples):
    if not samples:
        return None
    fps = [sample.get("fps") for sample in samples]
    frame_ms = [sample.get("frame_ms") for sample in samples]
    times = [sample.get("time") for sample in samples if sample.get("time") is not None]
    first_time = min(times) if times else None
    last_time = max(times) if times else None
    return {
        "rows": len(samples),
        "first_timestamp": first_time.isoformat() if first_time else None,
        "last_timestamp": last_time.isoformat() if last_time else None,
        "duration_seconds": (last_time - first_time).total_seconds()
        if first_time and last_time
        else None,
        "fps": stats(fps),
        "frame_ms": stats(frame_ms),
        "fps_lows": fps_lows_from_frame_ms(frame_ms),
        "frame_over_ms_counts": counts_over(frame_ms, [5, 6.67, 8.33, 10, 16.67, 25, 33.33, 50]),
    }


def summarize_visible_bands(samples):
    samples = [
        sample for sample in samples
        if sample.get("fps") is not None and math.isfinite(sample["fps"])
    ]
    if not samples:
        return {}
    bands = {
        "all": lambda fps: True,
        "near_cap_fps_gte_180": lambda fps: fps >= 180,
        "gameplayish_fps_gte_140": lambda fps: fps >= 140,
        "lobbyish_fps_100_to_130": lambda fps: 100 <= fps <= 130,
        "stall_or_transition_fps_lt_100": lambda fps: fps < 100,
    }
    return {
        name: summarize_visible_samples([
            sample for sample in samples if predicate(sample["fps"])
        ])
        for name, predicate in bands.items()
    }


def summarize_visible_runs(samples, min_fps=140, min_rows=10):
    runs = []
    current = []
    for sample in samples:
        fps = sample.get("fps")
        if fps is not None and math.isfinite(fps) and fps >= min_fps:
            current.append(sample)
            continue
        if len(current) >= min_rows:
            runs.append(current)
        current = []
    if len(current) >= min_rows:
        runs.append(current)
    return [
        summarize_visible_samples(run)
        for run in sorted(runs, key=len, reverse=True)[:10]
    ]


def truncate(text, length=240):
    text = str(text or "")
    if len(text) <= length:
        return text
    return text[: length - 3] + "..."


def summarize_inventory_pollution(root):
    allowed_powershell = (
        "windows-gaming-benchmark.ps1",
        "windows-performance-watch.ps1",
        "windows-performance-mode.ps1",
    )
    process_rows = defaultdict(lambda: {
        "samples": 0,
        "max_working_set_mb": 0.0,
        "max_private_mb": 0.0,
        "max_cpu_seconds": 0.0,
        "command_line": "",
    })

    for row in read_csv(root / "process-inventory.csv"):
        name = (row.get("ProcessName") or "").lower()
        if name not in ("powershell.exe", "pwsh.exe", "memory compression"):
            continue
        key = row.get("Id") or row.get("ProcessName") or name
        rec = process_rows[key]
        rec["samples"] += 1
        rec["name"] = row.get("ProcessName") or name
        rec["pid"] = row.get("Id")
        rec["max_working_set_mb"] = max(rec["max_working_set_mb"], fnum(row.get("WorkingSetMB")) or 0.0)
        rec["max_private_mb"] = max(rec["max_private_mb"], fnum(row.get("PrivateMemoryMB")) or 0.0)
        rec["max_cpu_seconds"] = max(rec["max_cpu_seconds"], fnum(row.get("CpuSeconds")) or 0.0)
        if row.get("CommandLine"):
            rec["command_line"] = row["CommandLine"]

    warnings = []
    for rec in process_rows.values():
        name = (rec.get("name") or "").lower()
        command_line = rec.get("command_line") or ""
        allowed = any(pattern in command_line for pattern in allowed_powershell)
        if name in ("powershell.exe", "pwsh.exe") and not allowed and (
            rec["max_working_set_mb"] >= 512 or rec["max_private_mb"] >= 512
        ):
            warnings.append({
                "type": "stale_or_external_powershell",
                "pid": rec.get("pid"),
                "samples": rec["samples"],
                "max_working_set_mb": rec["max_working_set_mb"],
                "max_private_mb": rec["max_private_mb"],
                "max_cpu_seconds": rec["max_cpu_seconds"],
                "command_line": truncate(command_line),
            })
        if name == "memory compression" and rec["max_working_set_mb"] >= 1024:
            warnings.append({
                "type": "memory_compression_pressure",
                "pid": rec.get("pid"),
                "samples": rec["samples"],
                "max_working_set_mb": rec["max_working_set_mb"],
                "max_private_mb": rec["max_private_mb"],
            })
    return warnings


def summarize_obs_profile(root):
    rows = list(read_csv(root / "obs-profile.csv"))
    settings = {}
    for row in rows:
        if not truthy(row.get("Available")):
            continue
        section = row.get("Section") or ""
        key = row.get("Key") or ""
        if not key:
            continue
        settings[f"{section}.{key}"] = row.get("Value")
    return {
        "rows": len(rows),
        "settings": settings,
    }


def stat_count(value):
    if isinstance(value, dict):
        count = value.get("count")
        if isinstance(count, (int, float)):
            return count
    return 0


def top_counter_name(counter_items):
    if not counter_items:
        return None
    first = counter_items[0]
    if isinstance(first, (list, tuple)) and first:
        return first[0]
    return None


def choose_visible_fps_source(result):
    rtss = result.get("rtss") or {}
    rtss_fps = rtss.get("fps_window")
    if stat_count(rtss_fps) > 0:
        return {
            "source": "rtss",
            "fps": rtss_fps,
            "frame_ms": rtss.get("frame_ms"),
            "fps_lows": rtss.get("fps_lows"),
        }

    afterburner = result.get("afterburner") or {}
    afterburner_fps = afterburner.get("OsdFramerate")
    if stat_count(afterburner_fps) > 0:
        return {
            "source": "afterburner",
            "fps": afterburner_fps,
            "frame_ms": afterburner.get("OsdFrametimeMs"),
            "fps_lows": None,
        }

    presentmon_all = (result.get("presentmon") or {}).get("all") or {}
    presentmon_fps = presentmon_all.get("fps_lows") or {}
    if presentmon_fps.get("avg_from_frame_ms") is not None:
        return {
            "source": "presentmon",
            "fps": {
                "count": (presentmon_all.get("frame_ms") or {}).get("count"),
                "avg": presentmon_fps.get("avg_from_frame_ms"),
                "min": presentmon_fps.get("min_from_max_frame_ms"),
            },
            "frame_ms": presentmon_all.get("frame_ms"),
            "fps_lows": presentmon_fps,
        }

    return {
        "source": None,
        "fps": None,
        "frame_ms": None,
        "fps_lows": None,
    }


def add_diagnosis(result):
    diagnosis = []
    presentmon_all = result.get("presentmon", {}).get("all", {})
    frame = presentmon_all.get("frame_ms") or {}
    fps = presentmon_all.get("fps_lows") or {}
    cpu_busy = presentmon_all.get("cpu_busy_ms") or {}
    cpu_wait = presentmon_all.get("cpu_wait_ms") or {}
    gpu_busy = presentmon_all.get("gpu_busy_ms") or {}
    system = result.get("system", {})
    nvidia = result.get("nvidia_smi", {})
    obs_profile = result.get("obs_profile", {})
    obs_settings = obs_profile.get("settings") or {}
    visible_fps = result.get("visible_fps") or {}

    def metric(group, key, stat_name):
        value = (group.get(key) or {}).get(stat_name)
        return value if isinstance(value, (int, float)) else None

    visible_source = visible_fps.get("source")
    visible_stats = visible_fps.get("fps") or {}
    visible_frame = visible_fps.get("frame_ms") or {}
    visible_avg_fps = visible_stats.get("avg")
    presentmon_avg_fps = fps.get("avg_from_frame_ms")
    presentmon_top_mode = top_counter_name((result.get("presentmon") or {}).get("present_modes"))
    presentmon_visible_mismatch = (
        visible_source
        and visible_source != "presentmon"
        and visible_avg_fps is not None
        and presentmon_avg_fps is not None
        and abs(visible_avg_fps - presentmon_avg_fps) >= max(15.0, visible_avg_fps * 0.15)
    )
    presentmon_composed_mismatch = (
        presentmon_visible_mismatch
        and presentmon_top_mode
        and presentmon_top_mode.startswith("Composed:")
    )
    if presentmon_visible_mismatch:
        diagnosis.append({
            "type": "presentmon_visible_fps_mismatch",
            "severity": "medium",
            "detail": (
                f"Visible FPS source '{visible_source}' averaged {visible_avg_fps:.1f} FPS, "
                f"while PresentMon-derived FPS averaged {presentmon_avg_fps:.1f}. "
                f"Dominant PresentMon present mode was '{presentmon_top_mode or 'unknown'}'. "
                "Use RTSS/MAHM for visible FPS."
            ),
        })
        if presentmon_composed_mismatch:
            diagnosis.append({
                "type": "presentmon_composed_flip_visible_fps_mismatch",
                "severity": "medium",
                "detail": (
                    "PresentMon disagreed while the game was in a composed presentation "
                    "path. Treat PresentMon FPS and per-frame CPU/GPU busy timing as "
                    "suspect for this capture; compare against an independent-flip capture."
                ),
            })

    avg_cpu_busy = cpu_busy.get("avg")
    avg_gpu_busy = gpu_busy.get("avg")
    avg_cpu_wait = cpu_wait.get("avg")
    if presentmon_composed_mismatch and (avg_cpu_busy is not None or avg_gpu_busy is not None):
        diagnosis.append({
            "type": "presentmon_frame_pipeline_suspect",
            "severity": "medium",
            "detail": (
                "Skipping PresentMon CPU/GPU busy bottleneck classification because "
                "the composed-flip PresentMon frame cadence does not match the visible FPS source."
            ),
        })
    elif avg_cpu_busy is not None and avg_gpu_busy is not None:
        if avg_cpu_busy >= max(avg_gpu_busy * 1.5, avg_gpu_busy + 2.0):
            diagnosis.append({
                "type": "cpu_frame_time_dominant",
                "severity": "high",
                "detail": (
                    f"Average CPU busy {avg_cpu_busy:.2f} ms is much higher than "
                    f"GPU busy {avg_gpu_busy:.2f} ms."
                ),
            })
        elif avg_gpu_busy >= avg_cpu_busy * 1.2:
            diagnosis.append({
                "type": "gpu_frame_time_dominant",
                "severity": "medium",
                "detail": (
                    f"Average GPU busy {avg_gpu_busy:.2f} ms is higher than "
                    f"CPU busy {avg_cpu_busy:.2f} ms."
                ),
            })
    if not presentmon_composed_mismatch and avg_cpu_wait is not None and avg_cpu_wait >= 2.0:
        diagnosis.append({
            "type": "cpu_wait_pressure",
            "severity": "medium",
            "detail": f"Average CPU wait is {avg_cpu_wait:.2f} ms.",
        })

    cpu_max_utility_p95 = metric(system, "CpuMaxUtilityPct", "p95")
    if cpu_max_utility_p95 is not None and cpu_max_utility_p95 >= 90:
        diagnosis.append({
            "type": "hot_logical_processor",
            "severity": "high",
            "detail": f"p95 max CPU utility is {cpu_max_utility_p95:.1f}%. Total CPU usage can look low while one frame-critical thread is saturated.",
        })

    ctx_p95 = metric(system, "ContextSwitchesPerSec", "p95")
    if ctx_p95 is not None and ctx_p95 >= 150000:
        diagnosis.append({
            "type": "scheduler_churn",
            "severity": "medium",
            "detail": f"p95 context switches are {ctx_p95:,.0f}/sec.",
        })

    pages_p95 = metric(system, "PagesPerSec", "p95")
    avail_min = metric(system, "AvailableMBytes", "min")
    if avail_min is not None and avail_min < 4096:
        diagnosis.append({
            "type": "memory_pressure",
            "severity": "high",
            "detail": f"Minimum available memory was {avail_min:,.0f} MB.",
        })
    elif pages_p95 is not None and pages_p95 >= 10000:
        diagnosis.append({
            "type": "paging_or_file_cache_activity",
            "severity": "medium",
            "detail": f"p95 pages/sec is {pages_p95:,.0f}; check whether launchers, sync, recording, or cache rebuilds are active.",
        })

    dpc_p95 = metric(system, "CpuTotalDpcPct", "p95")
    interrupt_p95 = metric(system, "CpuTotalInterruptPct", "p95")
    if (dpc_p95 is not None and dpc_p95 >= 3) or (interrupt_p95 is not None and interrupt_p95 >= 3):
        diagnosis.append({
            "type": "driver_interrupt_pressure",
            "severity": "medium",
            "detail": f"p95 DPC={dpc_p95 or 0:.2f}% interrupt={interrupt_p95 or 0:.2f}%.",
        })

    encode_p95 = metric(system, "GpuEngineVideoEncodeUtilPct", "p95")
    if encode_p95 is not None and encode_p95 >= 70:
        diagnosis.append({
            "type": "video_encode_heavy",
            "severity": "medium",
            "detail": f"p95 GPU video encode engine utilization is {encode_p95:.1f}%. This does not prove GPU 3D saturation, but it can add stream-path pressure.",
        })
        stream_encoder = str(obs_settings.get("SimpleOutput.StreamEncoder") or "").lower()
        rec_encoder = str(obs_settings.get("SimpleOutput.RecEncoder") or "").lower()
        if "nvenc" in stream_encoder and "nvenc" in rec_encoder and rec_encoder != "none":
            diagnosis.append({
                "type": "obs_dual_nvenc_path",
                "severity": "medium",
                "detail": f"OBS is configured for stream encoder '{stream_encoder}' plus recording encoder '{rec_encoder}'. This can create a heavier encode path while streaming/recording.",
            })
        if truthy(obs_settings.get("SimpleOutput.RecRB")) or truthy(obs_settings.get("AdvOut.RecRB")):
            diagnosis.append({
                "type": "obs_replay_buffer_enabled",
                "severity": "medium",
                "detail": "OBS replay buffer is enabled, which keeps extra recording work active during gameplay.",
            })
        aggregate_bitrate = fnum(obs_settings.get("Stream1.MultitrackVideoMaximumAggregateBitrate"))
        if aggregate_bitrate is not None and aggregate_bitrate >= 20000:
            diagnosis.append({
                "type": "obs_multitrack_encode_budget",
                "severity": "info",
                "detail": f"OBS multitrack maximum aggregate bitrate is {aggregate_bitrate:,.0f} Kbps.",
            })

    gpu_util_p95 = metric(nvidia, "GpuUtilPct", "p95")
    gpu_3d_p95 = metric(system, "GpuEngine3DUtilPct", "p95")
    if gpu_util_p95 is not None and gpu_util_p95 < 80 and gpu_3d_p95 is not None and gpu_3d_p95 < 80:
        diagnosis.append({
            "type": "not_gpu_saturated",
            "severity": "info",
            "detail": f"p95 NVIDIA GPU util={gpu_util_p95:.1f}% and p95 GPU 3D engine={gpu_3d_p95:.1f}%.",
        })

    p99 = visible_frame.get("p99")
    p999 = visible_frame.get("p999")
    if visible_avg_fps is not None and p99 is not None and p999 is not None:
        diagnosis.append({
            "type": "frame_summary",
            "severity": "info",
            "detail": f"Visible FPS source={visible_source} avg={visible_avg_fps:.1f}, p99 frame={p99:.2f} ms, p999 frame={p999:.2f} ms.",
        })

    if result.get("preflight", {}).get("warnings"):
        diagnosis.append({
            "type": "preflight_warning",
            "severity": "high",
            "detail": f"{len(result['preflight']['warnings'])} preflight warning(s) were present before capture.",
        })
    if result.get("pollution", {}).get("process_inventory_warnings"):
        diagnosis.append({
            "type": "capture_pollution",
            "severity": "high",
            "detail": f"{len(result['pollution']['process_inventory_warnings'])} process inventory warning(s) were detected during capture.",
        })

    result["diagnosis"] = diagnosis


def main(root):
    root = Path(root)
    capture_state = read_json(root / "state.json") or {}
    rows = []
    worst_frames = []
    present_modes = Counter()
    runtimes = Counter()

    for row in read_csv(root / "presentmon-console.csv"):
        item = {
            "time": parse_presentmon_time(row.get("CPUStartDateTime")),
            "time_text": row.get("CPUStartDateTime"),
            "frame_ms": fnum(row.get("FrameTime")),
            "cpu_busy_ms": fnum(row.get("CPUBusy")),
            "cpu_wait_ms": fnum(row.get("CPUWait")),
            "gpu_time_ms": fnum(row.get("GPUTime")),
            "gpu_busy_ms": fnum(row.get("GPUBusy")),
            "gpu_wait_ms": fnum(row.get("GPUWait")),
            "display_latency_ms": fnum(row.get("DisplayLatency")),
        }
        rows.append(item)
        if item["frame_ms"] is not None:
            worst_frames.append(item)
        if row.get("PresentMode"):
            present_modes[row["PresentMode"]] += 1
        if row.get("PresentRuntime"):
            runtimes[row["PresentRuntime"]] += 1

    times = [row["time"] for row in rows if row["time"] is not None]
    first_time = min(times) if times else None
    last_time = max(times) if times else None
    early = []
    gameplay = []
    late = []
    if first_time and last_time:
        for row in rows:
            if row["time"] is None:
                continue
            from_start = (row["time"] - first_time).total_seconds()
            from_end = (last_time - row["time"]).total_seconds()
            if from_start < 60:
                early.append(row)
            elif from_end < 30:
                late.append(row)
            else:
                gameplay.append(row)

    worst_frames.sort(key=lambda row: row["frame_ms"], reverse=True)
    spike16 = [row for row in rows if row["frame_ms"] is not None and row["frame_ms"] > 16.67]
    spike33 = [row for row in rows if row["frame_ms"] is not None and row["frame_ms"] > 33.33]

    afterburner = {}
    ab_cols = [
        "GpuUsagePct", "GpuClockMHz", "GpuPowerW", "GpuMemoryUsageMB",
        "CpuUsagePct", "CpuMaxLogicalUsagePct", "CpuClockMHz", "CpuTempC",
        "RamUsageMB", "OsdFramerate", "OsdFrametimeMs",
    ]
    ab_values = defaultdict(list)
    afterburner_visible_samples = []
    for row in read_csv(root / "afterburner.csv"):
        for col in ab_cols:
            ab_values[col].append(fnum(row.get(col)))
        afterburner_fps = fnum(row.get("OsdFramerate"))
        afterburner_frame_ms = fnum(row.get("OsdFrametimeMs"))
        if afterburner_fps is not None:
            afterburner_visible_samples.append({
                "time": parse_iso_time(row.get("Timestamp")),
                "fps": afterburner_fps,
                "frame_ms": afterburner_frame_ms,
            })
    for col in ab_cols:
        afterburner[col] = stats(ab_values[col])

    system = {}
    sys_cols = [
        "AvailableMBytes", "CommittedMBytes", "PagesPerSec",
        "PageFaultsPerSec",
        "CpuTotalProcessorTimePct", "CpuTotalUtilityPct",
        "CpuMaxProcessorTimePct", "CpuMaxUtilityPct", "CpuTotalPrivilegedPct",
        "CpuTotalDpcPct", "CpuTotalInterruptPct", "CpuMaxFrequencyMHz",
        "ProcessorQueueLength", "ContextSwitchesPerSec", "Processes", "Threads",
        "DiskReadLatencyMs",
        "DiskWriteLatencyMs", "DiskReadBytesPerSec", "DiskWriteBytesPerSec",
        "DiskQueueLength",
        "NetworkBytesTotalPerSec", "NetworkBytesReceivedPerSec", "NetworkBytesSentPerSec",
        "GpuEngine3DUtilPct", "GpuEngineCopyUtilPct", "GpuEngineVideoEncodeUtilPct",
        "GpuEngineVideoDecodeUtilPct", "GpuEngineComputeUtilPct",
        "GpuDedicatedUsageMB", "GpuSharedUsageMB",
    ]
    sys_values = defaultdict(list)
    for row in read_csv(root / "system.csv"):
        for col in sys_cols:
            sys_values[col].append(fnum(row.get(col)))
    for col in sys_cols:
        system[col] = stats(sys_values[col])

    nvidia_smi = {}
    nvidia_cols = [
        "GpuUtilPct", "GpuMemoryUtilPct", "GpuGraphicsClockMHz",
        "GpuMemoryClockMHz", "GpuPowerW", "GpuTempC",
        "GpuMemoryUsedMB", "GpuMemoryTotalMB", "PcieLinkGen", "PcieLinkWidth",
    ]
    nvidia_values = defaultdict(list)
    for row in read_csv(root / "nvidia-smi.csv"):
        for col in nvidia_cols:
            nvidia_values[col].append(fnum(row.get(col)))
    for col in nvidia_cols:
        nvidia_smi[col] = stats(nvidia_values[col])

    rtss_frame = []
    rtss_fps = []
    rtss_visible_samples = []
    rtss_rows = 0
    rtss_active_rows = 0
    for row in read_csv(root / "rtss.csv"):
        rtss_rows += 1
        if str(row.get("Active", "")).lower() == "true" and row.get("ProcessId") not in ("0", "", None):
            rtss_active_rows += 1
            frame_ms = fnum(row.get("FrameTimeMs"))
            fps = fnum(row.get("FpsWindow"))
            rtss_frame.append(frame_ms)
            rtss_fps.append(fps)
            if fps is not None:
                rtss_visible_samples.append({
                    "time": parse_iso_time(row.get("Timestamp")),
                    "fps": fps,
                    "frame_ms": frame_ms,
                })

    thread_rows = []
    for row in read_csv((root / "target-threads.csv" if (root / "target-threads.csv").exists() else root / "fortnite-threads.csv")):
        pct = fnum(row.get("OneThreadPct"))
        if pct is not None:
            thread_rows.append((pct, row))
    thread_rows.sort(reverse=True, key=lambda item: item[0])

    proc = defaultdict(lambda: {"samples": 0, "max_total": 0.0, "max_one": 0.0, "max_ws": 0.0, "ids": set()})
    for file_name in ("top-processes.csv", "watched-processes.csv"):
        for row in read_csv(root / file_name):
            name = row.get("ProcessName") or ""
            rec = proc[name]
            rec["samples"] += 1
            rec["ids"].add(row.get("Id"))
            rec["max_total"] = max(rec["max_total"], fnum(row.get("CpuPctTotal")) or 0.0)
            rec["max_one"] = max(rec["max_one"], fnum(row.get("CpuPctOneThread")) or 0.0)
            rec["max_ws"] = max(rec["max_ws"], fnum(row.get("WorkingSetMB")) or 0.0)

    preflight_rows = list(read_csv(root / "preflight.csv"))
    preflight_warnings = [
        {
            "timestamp": row.get("Timestamp"),
            "category": row.get("Category"),
            "name": row.get("Name"),
            "process_id": row.get("ProcessId"),
            "detail": row.get("Detail"),
            "working_set_mb": fnum(row.get("WorkingSetMB")),
            "private_memory_mb": fnum(row.get("PrivateMemoryMB")),
            "available_mb": fnum(row.get("AvailableMBytes")),
        }
        for row in preflight_rows
        if truthy(row.get("Suspicious"))
    ]

    result = {
        "root": str(root),
        "capture_state": {
            "label": capture_state.get("Label"),
            "start_time": capture_state.get("StartTime"),
            "affinity_preset": capture_state.get("AffinityPreset"),
            "requested_affinity_mask": capture_state.get("RequestedAffinityMask"),
            "applied_affinity_mask": capture_state.get("AppliedAffinityMask"),
            "original_affinity_mask": capture_state.get("OriginalAffinityMask"),
            "requested_priority_class": capture_state.get("RequestedPriorityClass"),
            "applied_priority_class": capture_state.get("AppliedPriorityClass"),
            "original_priority_class": capture_state.get("OriginalPriorityClass"),
            "power_plan_preset": capture_state.get("PowerPlanPreset"),
            "requested_power_plan_guid": capture_state.get("RequestedPowerPlanGuid"),
            "applied_power_plan_guid": capture_state.get("AppliedPowerPlanGuid"),
            "original_power_plan_guid": capture_state.get("OriginalPowerPlanGuid"),
            "restored_power_plan_guid": capture_state.get("RestoredPowerPlanGuid"),
        },
        "preflight": {
            "rows": len(preflight_rows),
            "warnings": preflight_warnings,
        },
        "pollution": {
            "process_inventory_warnings": summarize_inventory_pollution(root),
        },
        "obs_profile": summarize_obs_profile(root),
        "presentmon": {
            "rows": len(rows),
            "first_cpu_start": rows[0]["time_text"] if rows else None,
            "last_cpu_start": rows[-1]["time_text"] if rows else None,
            "present_modes": present_modes.most_common(),
            "runtimes": runtimes.most_common(),
            "all": summarize_presentmon_rows(rows),
            "early_first_60s": summarize_presentmon_rows(early),
            "gameplay_trim_first60_last30": summarize_presentmon_rows(gameplay),
            "late_last_30s": summarize_presentmon_rows(late),
            "spike_gt_16_67": summarize_presentmon_rows(spike16),
            "spike_gt_33_33": summarize_presentmon_rows(spike33),
            "worst_frames": [
                {
                    key: (value.isoformat(sep=" ") if isinstance(value, datetime) else value)
                    for key, value in row.items()
                }
                for row in worst_frames[:20]
            ],
        },
        "afterburner": afterburner,
        "system": system,
        "nvidia_smi": nvidia_smi,
        "rtss": {
            "rows": rtss_rows,
            "active_rows": rtss_active_rows,
            "fps_window": stats(rtss_fps),
            "frame_ms": stats(rtss_frame),
            "fps_lows": fps_lows_from_frame_ms(rtss_frame),
            "frame_over_ms_counts": counts_over(rtss_frame, [5, 6.67, 8.33, 10, 16.67, 25, 33.33, 50]),
        },
        "target_threads": {
            "rows": len(thread_rows),
            "hottest_samples": [
                {
                    "timestamp": row.get("Timestamp"),
                    "thread_id": row.get("ThreadId"),
                    "one_thread_pct": pct,
                    "state": row.get("State"),
                    "wait": row.get("WaitReason"),
                }
                for pct, row in thread_rows[:20]
            ],
        },
        "processes": [
            {
                "name": name,
                "samples": rec["samples"],
                "max_cpu_pct_total": rec["max_total"],
                "max_cpu_pct_one_thread": rec["max_one"],
                "max_working_set_mb": rec["max_ws"],
                "ids": sorted(item for item in rec["ids"] if item),
            }
            for name, rec in sorted(proc.items(), key=lambda item: item[1]["max_total"], reverse=True)[:30]
        ],
        "markers": list(read_csv(root / "markers.csv")) if (root / "markers.csv").exists() else [],
    }

    result["visible_fps"] = choose_visible_fps_source(result)
    visible_samples = (
        rtss_visible_samples
        if result["visible_fps"].get("source") == "rtss"
        else afterburner_visible_samples
        if result["visible_fps"].get("source") == "afterburner"
        else []
    )
    result["visible_fps_bands"] = summarize_visible_bands(visible_samples)
    result["visible_fps_runs_fps_gte_140"] = summarize_visible_runs(visible_samples, min_fps=140)
    add_diagnosis(result)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: analyze-gaming-capture.py <capture-dir>")
    main(sys.argv[1])
