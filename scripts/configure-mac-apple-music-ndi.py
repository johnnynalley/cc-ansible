#!/usr/bin/env python3
"""Configure a Mac OBS Apple Music application-audio NDI output."""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
import uuid
from pathlib import Path


SOURCE_NAME = "Apple Music"
BLACK_SOURCE_NAME = "Apple Music NDI Black"
NDI_SCENE_NAME = "Apple Music NDI Scene"
NDI_NAME = "MacBook Apple Music"
SCENE_NAME = "TikTok Vertical"
APP_BUNDLE_ID = "com.apple.Music"


def base_source(name: str, source_id: str, settings: dict) -> dict:
    return {
        "balance": 0.5,
        "deinterlace_field_order": 0,
        "deinterlace_mode": 0,
        "enabled": True,
        "flags": 0,
        "hotkeys": {
            "libobs.mute": [],
            "libobs.push-to-mute": [],
            "libobs.push-to-talk": [],
            "libobs.unmute": [],
        },
        "id": source_id,
        "mixers": 255,
        "monitoring_type": 0,
        "muted": False,
        "name": name,
        "prev_ver": 536936450,
        "private_settings": {},
        "push-to-mute": False,
        "push-to-mute-delay": 0,
        "push-to-talk": False,
        "push-to-talk-delay": 0,
        "settings": settings,
        "sync": 0,
        "uuid": str(uuid.uuid4()),
        "versioned_id": source_id,
        "volume": 1,
    }


def ndi_filter() -> dict:
    return base_source(
        NDI_NAME,
        "ndi_audiofilter",
        {
            "ndi_filter_ndigroups": "",
            "ndi_filter_ndiname": NDI_NAME,
        },
    ) | {"hotkeys": {}, "mixers": 0}


def scene_item(
    source: dict,
    item_id: int,
    *,
    name: str | None = None,
    pos: dict | None = None,
    pos_rel: dict | None = None,
    scale: dict | None = None,
    scale_rel: dict | None = None,
    locked: bool = False,
) -> dict:
    return {
        "align": 5,
        "blend_method": "default",
        "blend_type": "normal",
        "bounds": {"x": 0, "y": 0},
        "bounds_align": 0,
        "bounds_crop": False,
        "bounds_rel": {"x": 0, "y": 0},
        "bounds_type": 0,
        "crop_bottom": 0,
        "crop_left": 0,
        "crop_right": 0,
        "crop_top": 0,
        "group_item_backup": False,
        "hide_transition": {"duration": 300},
        "id": item_id,
        "locked": locked,
        "name": name or source["name"],
        "pos": pos or {"x": 0, "y": 0},
        "pos_rel": pos_rel or {"x": -0.5625, "y": -1},
        "private_settings": {},
        "rot": 0,
        "scale": scale or {"x": 1, "y": 1},
        "scale_filter": "disable",
        "scale_ref": {"x": 1080, "y": 1920},
        "scale_rel": scale_rel or {"x": 1, "y": 1},
        "show_transition": {"duration": 300},
        "source_uuid": source["uuid"],
        "visible": True,
    }


def main() -> int:
    obs_scene_path = Path.home() / "Library/Application Support/obs-studio/basic/scenes/Untitled.json"
    if not obs_scene_path.exists():
        print(f"obs_scene=missing path={obs_scene_path}")
        return 1

    with obs_scene_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    backup_path = obs_scene_path.with_suffix(f".json.pre-apple-music-ndi-{int(time.time())}.bak")
    shutil.copy2(obs_scene_path, backup_path)

    sources = data.setdefault("sources", [])
    source = next((item for item in sources if item.get("name") == SOURCE_NAME), None)
    if source is None:
        source = base_source(
            SOURCE_NAME,
            "sck_audio_capture",
            {
                "application": APP_BUNDLE_ID,
                "type": 1,
            },
        )
        sources.append(source)
        print("apple_music_source=created")
    else:
        source["id"] = "sck_audio_capture"
        source["versioned_id"] = "sck_audio_capture"
        source.setdefault("settings", {})["application"] = APP_BUNDLE_ID
        source["settings"]["type"] = 1
        print("apple_music_source=updated")

    source["monitoring_type"] = 0
    source["muted"] = False

    source_filters = source.setdefault("filters", [])
    if source_filters is None:
        source_filters = []
        source["filters"] = source_filters
    source_filters = [
        item
        for item in source_filters
        if item.get("name") != NDI_NAME and item.get("id") not in ("ndi_filter", "ndi_audiofilter")
    ]
    audio_filter = ndi_filter()
    source_filters.append(audio_filter)
    source["filters"] = source_filters
    print("audio_ndi_filter=created")

    black_source = next((item for item in sources if item.get("name") == BLACK_SOURCE_NAME), None)
    if black_source is None:
        black_source = base_source(
            BLACK_SOURCE_NAME,
            "color_source",
            {
                "color": 4278190080,
                "height": 720,
                "width": 1280,
            },
        )
        black_source["mixers"] = 0
        sources.append(black_source)
        print("black_source=created")
    else:
        black_source["id"] = "color_source"
        black_source["versioned_id"] = "color_source"
        black_source.setdefault("settings", {})["color"] = 4278190080
        black_source["settings"]["height"] = 720
        black_source["settings"]["width"] = 1280
        black_source["mixers"] = 0
        print("black_source=updated")

    ndi_scene = next((item for item in sources if item.get("name") == NDI_SCENE_NAME and item.get("id") == "scene"), None)
    if ndi_scene is None:
        ndi_scene = base_source(
            NDI_SCENE_NAME,
            "scene",
            {
                "custom_size": False,
                "id_counter": 2,
                "items": [
                    scene_item(black_source, 1, name=BLACK_SOURCE_NAME),
                    scene_item(source, 2, name=SOURCE_NAME),
                ],
            },
        )
        ndi_scene["mixers"] = 0
        sources.append(ndi_scene)
        print("ndi_scene=created")
    else:
        ndi_scene["id"] = "scene"
        ndi_scene["versioned_id"] = "scene"
        ndi_scene["mixers"] = 0
        scene_settings = ndi_scene.setdefault("settings", {})
        items = scene_settings.setdefault("items", [])
        id_counter = int(scene_settings.get("id_counter", 0))
        for item_source, item_name in ((black_source, BLACK_SOURCE_NAME), (source, SOURCE_NAME)):
            if not any(item.get("source_uuid") == item_source["uuid"] for item in items):
                id_counter += 1
                items.append(scene_item(item_source, id_counter, name=item_name))
        scene_settings["id_counter"] = max(id_counter, int(scene_settings.get("id_counter", 0)))
        print("ndi_scene=updated")

    ndi_scene["filters"] = [
        item
        for item in (ndi_scene.get("filters") or [])
        if item.get("name") != NDI_NAME and item.get("id") not in ("ndi_filter", "ndi_audiofilter")
    ]
    print("scene_ndi_filter=removed")

    scene = next((item for item in sources if item.get("name") == SCENE_NAME and item.get("id") == "scene"), None)
    if scene is None:
        print(f"scene={SCENE_NAME!r} status=missing")
    else:
        settings = scene.setdefault("settings", {})
        items = settings.setdefault("items", [])
        if not any(item.get("source_uuid") == source["uuid"] for item in items):
            next_id = int(settings.get("id_counter", 0)) + 1
            items.append(scene_item(source, next_id))
            settings["id_counter"] = next_id
            print("audio_scene_item=created")
        else:
            print("audio_scene_item=present")

        if not any(item.get("source_uuid") == ndi_scene["uuid"] for item in items):
            next_id = int(settings.get("id_counter", 0)) + 1
            items.append(
                scene_item(
                    ndi_scene,
                    next_id,
                    name=NDI_SCENE_NAME,
                    locked=True,
                    pos={"x": 8469, "y": 6500},
                    pos_rel={"x": 8.259259223937988, "y": 5.0},
                    scale={"x": 0.01, "y": 0.01},
                    scale_rel={"x": 0.005625, "y": 0.005625},
                )
            )
            settings["id_counter"] = next_id
            print("ndi_scene_item=created")
        else:
            print("ndi_scene_item=present")

    order = data.setdefault("scene_order", [])
    if not any(item.get("name") == NDI_SCENE_NAME for item in order):
        order.append({"name": NDI_SCENE_NAME})
        print("scene_order=updated")

    tmp_path = obs_scene_path.with_suffix(".json.tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=4)
        handle.write("\n")
    os.replace(tmp_path, obs_scene_path)

    print(f"backup={backup_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
