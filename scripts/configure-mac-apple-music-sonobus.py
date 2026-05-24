#!/usr/bin/env python3
"""Configure Mac OBS to send the Apple Music app-capture source through SonoBus."""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
import uuid
from pathlib import Path


SOURCE_NAME = "Apple Music"
FILTER_NAME = "SonoBus Apple Music"
VST_PATH = "/Library/Audio/Plug-Ins/VST/SonoBus.vst"


def vst_filter() -> dict:
    return {
        "balance": 0.5,
        "deinterlace_field_order": 0,
        "deinterlace_mode": 0,
        "enabled": True,
        "flags": 0,
        "hotkeys": {},
        "id": "vst_filter",
        "mixers": 0,
        "monitoring_type": 0,
        "muted": False,
        "name": FILTER_NAME,
        "prev_ver": 536936450,
        "private_settings": {},
        "push-to-mute": False,
        "push-to-mute-delay": 0,
        "push-to-talk": False,
        "push-to-talk-delay": 0,
        "settings": {
            "open_when_active_vst_settings": False,
            "plugin_path": VST_PATH,
        },
        "sync": 0,
        "uuid": str(uuid.uuid4()),
        "versioned_id": "vst_filter",
        "volume": 1.0,
    }


def main() -> int:
    scene_path = Path.home() / "Library/Application Support/obs-studio/basic/scenes/Untitled.json"
    if not scene_path.exists():
        print(f"obs_scene=missing path={scene_path}")
        return 1

    if not Path(VST_PATH).exists():
        print(f"sonobus_vst=missing path={VST_PATH}")
        return 1

    with scene_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    source = next((item for item in data.get("sources", []) if item.get("name") == SOURCE_NAME), None)
    if source is None:
        print(f"source=missing name={SOURCE_NAME!r}")
        return 1

    backup_path = scene_path.with_suffix(f".json.pre-sonobus-{int(time.time())}.bak")
    shutil.copy2(scene_path, backup_path)

    filters = source.setdefault("filters", [])
    if filters is None:
        filters = []
        source["filters"] = filters

    sonobus = next((item for item in filters if item.get("name") == FILTER_NAME), None)
    if sonobus is None:
        filters.append(vst_filter())
        print("sonobus_filter=created")
    else:
        sonobus["id"] = "vst_filter"
        sonobus["versioned_id"] = "vst_filter"
        sonobus["enabled"] = True
        sonobus.setdefault("settings", {})["plugin_path"] = VST_PATH
        sonobus["settings"]["open_when_active_vst_settings"] = False
        print("sonobus_filter=updated")

    original_count = len(filters)
    filters[:] = [
        item
        for item in filters
        if not (item.get("name") == "MacBook Apple Music" and item.get("id") in ("ndi_filter", "ndi_audiofilter"))
    ]
    if len(filters) != original_count:
        print("ndi_filter=removed")

    tmp_path = scene_path.with_suffix(".json.tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=4)
        handle.write("\n")
    os.replace(tmp_path, scene_path)

    print(f"backup={backup_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
