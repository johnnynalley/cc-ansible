#!/usr/bin/env python3
"""Regression tests for Plex appliance queue identity reconciliation."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import os
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

import requests


ROOT = Path(__file__).parents[2]
PLAYER = ROOT / "templates/plex-appliance/plex-appliance-player.py.j2"


def load_player_module():
    environment = {
        "PLEX_APPLIANCE_SERVER_URL": "http://plex.invalid:32400",
        "PLEX_APPLIANCE_TOKEN": "test-token",
        "PLEX_APPLIANCE_LIBRARY": "Shows",
        "PLEX_APPLIANCE_COLLECTION": "Adult Swim Collection",
        "PLEX_APPLIANCE_STATUS_SCREEN": "false",
    }
    os.environ.update(environment)
    loader = importlib.machinery.SourceFileLoader("plex_appliance_player", str(PLAYER))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    if spec is None:
        raise RuntimeError(f"Could not load {PLAYER}")
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


PLAYER_MODULE = load_player_module()


def episode(key: str, *, title: str = "Interdimensional Cable 2: Tempting Fate", guid: str = ""):
    attributes = {
        "ratingKey": key,
        "type": "episode",
        "title": title,
        "grandparentTitle": "Rick and Morty",
        "parentTitle": "Season 2",
        "parentIndex": "2",
        "index": "8",
    }
    if guid:
        attributes["guid"] = guid
    return ET.Element("Video", attributes)


class PlexAppliancePlayerTests(unittest.TestCase):
    def test_http_404_is_missing_metadata(self):
        response = requests.Response()
        response.status_code = 404
        not_found = requests.HTTPError(response=response)
        self.assertTrue(PLAYER_MODULE.plex_metadata_not_found(not_found))

        response.status_code = 503
        unavailable = requests.HTTPError(response=response)
        self.assertFalse(PLAYER_MODULE.plex_metadata_not_found(unavailable))
        self.assertFalse(PLAYER_MODULE.plex_metadata_not_found(TimeoutError()))

    def test_legacy_active_title_rebinds_to_unique_replacement(self):
        replacement = episode("44368")
        active = {
            "key": "19219",
            "title": PLAYER_MODULE.item_title(replacement),
            "position": 47.5,
            "failure_count": 3,
            "failure_position": 47.5,
            "failure_reason": "playback_failure",
        }

        rebound = PLAYER_MODULE.reconcile_active_metadata(
            active,
            {"44368": replacement},
            set(),
        )

        self.assertIsNotNone(rebound)
        self.assertEqual(rebound["key"], "44368")
        self.assertEqual(rebound["position"], 47.5)
        self.assertEqual(rebound["identity"], 'episode:["rick and morty","2","8"]')
        self.assertNotIn("failure_count", rebound)
        self.assertNotIn("failure_position", rebound)
        self.assertNotIn("failure_reason", rebound)

    def test_saved_guid_rebinds_even_if_title_changes(self):
        replacement = episode("44368", title="Updated title", guid="plex://episode/stable")
        active = {
            "key": "19219",
            "title": "Old title",
            "identity": "guid:plex://episode/stable",
            "position": 12.0,
        }

        rebound = PLAYER_MODULE.reconcile_active_metadata(
            active,
            {"44368": replacement},
            set(),
        )

        self.assertEqual(rebound["key"], "44368")
        self.assertEqual(rebound["title"], "Rick and Morty - Season 2 - Updated title")

    def test_ambiguous_legacy_title_is_not_guessed_or_marked_played(self):
        first = episode("44368")
        second = episode("44369")
        active = {
            "key": "19219",
            "title": PLAYER_MODULE.item_title(first),
            "position": 0.0,
        }

        rebound = PLAYER_MODULE.reconcile_active_metadata(
            active,
            {"44368": first, "44369": second},
            set(),
        )
        queue, played, unplayable = PLAYER_MODULE.reconcile_shuffle_state(
            ["19219", "90000"],
            [],
            [],
            {"44368", "44369", "90000"},
            PLAYER_MODULE.active_item_key(rebound),
        )

        self.assertIsNone(rebound)
        self.assertNotIn("19219", queue)
        self.assertEqual(set(queue), {"44368", "44369", "90000"})
        self.assertEqual(played, [])
        self.assertEqual(unplayable, [])

    def test_active_checkpoint_persists_stable_identity(self):
        item = episode("44368", guid="plex://episode/stable")
        checkpoint = PLAYER_MODULE.active_checkpoint("44368", item, 15.0, 120.0)
        self.assertEqual(checkpoint["identity"], "guid:plex://episode/stable")


if __name__ == "__main__":
    unittest.main()
