#!/usr/bin/env python3
"""Focused regressions for the embedded-subtitle staging verifier."""

from __future__ import annotations

import importlib.util
import json
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "scripts/media-release/sonarr_embedded_subtitle_verifier.py"
SPEC = importlib.util.spec_from_file_location("subtitle_verifier", SOURCE)
assert SPEC and SPEC.loader
VERIFIER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFIER)


class EmbeddedSubtitleVerifierTests(unittest.TestCase):
    def test_candidate_reference_is_stable_and_compact_output_hides_download_data(self) -> None:
        release = {
            "guid": "private-guid",
            "downloadUrl": "https://tracker.invalid/download?token=private",
            "indexerId": 9,
            "indexer": "Private",
            "title": "House.S04.1080p-WADU",
            "size": 123,
            "protocol": "torrent",
            "quality": {"quality": {"name": "WEBDL-1080p"}},
            "rejections": ["Existing file has a higher score"],
        }
        first = VERIFIER.candidate_id(release)
        second = VERIFIER.candidate_id(dict(release))
        self.assertEqual(first, second)
        self.assertRegex(first, r"^[a-f0-9]{64}$")
        compact = VERIFIER.compact_candidate(release)
        self.assertNotIn("guid", compact)
        self.assertNotIn("downloadUrl", compact)
        self.assertNotIn("private-guid", json.dumps(compact))
        self.assertNotIn("token=private", json.dumps(compact))

    def test_episode_parser_handles_single_and_multi_episode_names(self) -> None:
        self.assertEqual(
            VERIFIER.episode_numbers("House.S07E01.Now.What.mkv", 7), {1}
        )
        self.assertEqual(
            VERIFIER.episode_numbers("Example.S07E02-E03-E04.mkv", 7),
            {2, 3, 4},
        )
        self.assertEqual(
            VERIFIER.episode_numbers("House.S07E01.Now.What.mkv", 4), set()
        )
        self.assertEqual(
            VERIFIER.title_seasons("House Season 1-8 S01-S08 1080p"),
            set(range(1, 9)),
        )

    def test_container_paths_are_bounded_to_media_roots(self) -> None:
        self.assertEqual(
            VERIFIER.map_container_path("/incomplete/tx/House/file.mkv"),
            Path("/srv/incomplete_downloads/incomplete/torrents/tx/House/file.mkv"),
        )
        self.assertEqual(
            VERIFIER.map_container_path("/data/downloads/torrents/tx/file.mkv"),
            Path("/srv/media/plex/downloads/torrents/tx/file.mkv"),
        )
        for value in ("/etc/shadow", "/data/../etc/shadow", "relative/file.mkv"):
            with self.subTest(value=value), self.assertRaisesRegex(
                VERIFIER.VerificationError, "payload-path-invalid"
            ):
                VERIFIER.map_container_path(value)

    def test_ffprobe_requires_real_video_audio_and_tagged_english_subtitle(self) -> None:
        streams = {
            "streams": [
                {"index": 0, "codec_type": "video", "codec_name": "h264"},
                {"index": 1, "codec_type": "audio", "codec_name": "eac3"},
                {
                    "index": 2,
                    "codec_type": "subtitle",
                    "codec_name": "subrip",
                    "tags": {"language": "eng", "title": "English"},
                },
            ]
        }
        with tempfile.TemporaryDirectory() as directory:
            payload = Path(directory) / "episode.mkv"
            ffprobe = Path(directory) / "ffprobe"
            payload.write_bytes(b"payload")
            ffprobe.write_text("stub", encoding="ascii")
            result = mock.Mock(returncode=0, stdout=json.dumps(streams))
            with mock.patch.object(VERIFIER, "FFPROBE", ffprobe), mock.patch.object(
                VERIFIER.subprocess, "run", return_value=result
            ) as run:
                value = VERIFIER.probe_file(payload)
        self.assertTrue(value["hasVideo"])
        self.assertTrue(value["hasAudio"])
        self.assertTrue(value["hasEmbeddedEnglishSubtitle"])
        self.assertEqual(run.call_args.args[0][0], str(ffprobe))
        self.assertNotIn("shell", run.call_args.kwargs)

    def test_untagged_or_non_english_subtitle_is_not_eligible(self) -> None:
        for language in (None, "spa"):
            streams = {
                "streams": [
                    {"index": 0, "codec_type": "video", "codec_name": "hevc"},
                    {"index": 1, "codec_type": "audio", "codec_name": "aac"},
                    {
                        "index": 2,
                        "codec_type": "subtitle",
                        "codec_name": "subrip",
                        "tags": ({"language": language} if language else {}),
                    },
                ]
            }
            with self.subTest(language=language), tempfile.TemporaryDirectory() as directory:
                payload = Path(directory) / "episode.mkv"
                ffprobe = Path(directory) / "ffprobe"
                payload.write_bytes(b"payload")
                ffprobe.write_text("stub", encoding="ascii")
                result = mock.Mock(returncode=0, stdout=json.dumps(streams))
                with mock.patch.object(VERIFIER, "FFPROBE", ffprobe), mock.patch.object(
                    VERIFIER.subprocess, "run", return_value=result
                ):
                    value = VERIFIER.probe_file(payload)
            self.assertFalse(value["hasEmbeddedEnglishSubtitle"])

    def test_request_shapes_are_exact_and_never_accept_a_url_or_path(self) -> None:
        with mock.patch.object(VERIFIER, "release_candidates", return_value=[]):
            value = VERIFIER.handle(
                {
                    "schemaVersion": 1,
                    "action": "search",
                    "seriesId": 43,
                    "seasonNumber": 4,
                }
            )
        self.assertEqual(value["seriesId"], 43)
        for extra in (
            {"downloadUrl": "https://tracker.invalid/private"},
            {"path": "/srv/media/plex/TV Shows/House"},
        ):
            with self.subTest(extra=extra), self.assertRaisesRegex(
                VERIFIER.VerificationError, "invalid-request"
            ):
                VERIFIER.handle(
                    {
                        "schemaVersion": 1,
                        "action": "search",
                        "seriesId": 43,
                        "seasonNumber": 4,
                        **extra,
                    }
                )

    def test_search_filters_usenet_before_truncating_torrent_candidates(self) -> None:
        usenet = [
            {
                "guid": f"nzb-{index}",
                "indexerId": 1,
                "protocol": "usenet",
                "title": f"House.S04E{index:02d}-REMUX",
                "size": index,
            }
            for index in range(1, 61)
        ]
        torrent = {
            "guid": "torrent-pack",
            "indexerId": 12,
            "protocol": "torrent",
            "title": "House.S04.1080p.WEB-DL-WADU",
            "size": 123,
            "fullSeason": True,
            "mappedSeasonNumber": 4,
            "episodeNumbers": list(range(1, 17)),
            "downloadUrl": "https://tracker.invalid/private",
        }
        with mock.patch.object(
            VERIFIER, "release_candidates", return_value=[*usenet, torrent]
        ):
            value = VERIFIER.search({"seriesId": 43, "seasonNumber": 4})
        self.assertEqual(value["sourceTotal"], 61)
        self.assertEqual(value["total"], 1)
        self.assertFalse(value["truncated"])
        self.assertEqual(value["candidates"][0]["title"], torrent["title"])
        self.assertTrue(value["candidates"][0]["fullSeason"])
        self.assertEqual(value["candidates"][0]["mappedSeasonNumber"], 4)
        self.assertEqual(value["candidates"][0]["episodeNumbers"], list(range(1, 17)))
        self.assertNotIn("downloadUrl", json.dumps(value))

    def test_search_rejects_wrong_series_noise_but_keeps_multiseason_fallback(self) -> None:
        exact = {
            "guid": "exact",
            "indexerId": 12,
            "protocol": "torrent",
            "title": "House.S07.1080p-WADU",
            "size": 1,
            "fullSeason": True,
            "mappedSeasonNumber": 7,
            "seeders": 2,
        }
        multi = {
            "guid": "multi",
            "indexerId": 12,
            "protocol": "torrent",
            "title": "House Season S01-S08 1080p-Panda",
            "size": 2,
            "fullSeason": True,
            "mappedSeasonNumber": 1,
            "seeders": 10,
            "rejections": ["Multi-season releases are not supported", "Wrong season"],
        }
        noise = {
            "guid": "noise",
            "indexerId": 5,
            "protocol": "torrent",
            "title": "Terrace.House.S07E01.1080p",
            "size": 3,
            "mappedSeasonNumber": None,
            "rejections": ["Unknown Series"],
        }
        with mock.patch.object(
            VERIFIER, "release_candidates", return_value=[noise, multi, exact]
        ):
            value = VERIFIER.search({"seriesId": 43, "seasonNumber": 7})
        self.assertEqual([item["title"] for item in value["candidates"]], [exact["title"], multi["title"]])

    def test_search_ranks_custom_format_score_before_seeders(self) -> None:
        higher_score = {
            "guid": "higher-score",
            "indexerId": 12,
            "protocol": "torrent",
            "title": "House.S04.1080p.WEB-DL-WADU",
            "size": 1,
            "fullSeason": True,
            "mappedSeasonNumber": 4,
            "customFormatScore": 45619,
            "seeders": 2,
        }
        more_seeders = {
            "guid": "more-seeders",
            "indexerId": 12,
            "protocol": "torrent",
            "title": "House.S04.1080p.BluRay-iVy",
            "size": 2,
            "fullSeason": True,
            "mappedSeasonNumber": 4,
            "customFormatScore": 46160,
            "seeders": 1,
        }
        with mock.patch.object(
            VERIFIER, "release_candidates", return_value=[higher_score, more_seeders]
        ):
            value = VERIFIER.search({"seriesId": 43, "seasonNumber": 4})
        self.assertEqual(
            [item["title"] for item in value["candidates"]],
            [more_seeders["title"], higher_score["title"]],
        )

    def test_state_rejects_symlinks_and_non_root_ownership(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_root = Path(directory)
            target = state_root / ("a" * 24 + ".json")
            target.write_text(
                json.dumps({"transactionId": "a" * 24}), encoding="utf-8"
            )
            target.chmod(0o600)
            real = target.stat()
            trusted = mock.Mock(
                st_mode=stat.S_IFREG | 0o600,
                st_uid=0,
                st_size=real.st_size,
            )
            with mock.patch.object(VERIFIER, "STATE_ROOT", state_root), mock.patch.object(
                VERIFIER, "ensure_state_root"
            ), mock.patch.object(VERIFIER.os, "lstat", return_value=trusted):
                value = VERIFIER.read_state("a" * 24)
                self.assertEqual(value["transactionId"], "a" * 24)
                trusted.st_uid = 1000
                with self.assertRaisesRegex(
                    VERIFIER.VerificationError, "state-invalid"
                ):
                    VERIFIER.read_state("a" * 24)


if __name__ == "__main__":
    unittest.main()
