#!/usr/bin/env python3
"""Configure Mac OBS TikTok scene for video-only broker audio handling."""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path


SOURCE_NAME = "TikTok Vertical Broker"


def main() -> int:
    scene_path = Path.home() / "Library/Application Support/obs-studio/basic/scenes/Untitled.json"
    if not scene_path.exists():
        print(f"obs_scene=missing path={scene_path}")
        return 1

    with scene_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    source = next((item for item in data.get("sources", []) if item.get("name") == SOURCE_NAME), None)
    if source is None:
        print(f"source=missing name={SOURCE_NAME!r}")
        return 1

    backup_path = scene_path.with_suffix(f".json.pre-tiktok-vbcable-{int(time.time())}.bak")
    shutil.copy2(scene_path, backup_path)

    source["monitoring_type"] = 0
    source["muted"] = False
    source["volume"] = 1.0

    tmp_path = scene_path.with_suffix(".json.tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=4)
        handle.write("\n")
    os.replace(tmp_path, scene_path)

    print(f"source={SOURCE_NAME!r}")
    print("monitoring_type=0")
    print("volume=1.0")
    print(f"backup={backup_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
