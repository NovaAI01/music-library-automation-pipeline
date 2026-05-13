import csv
import json

from app.album_discovery import (
    SUGGESTION_HEADERS,
    ExternalAlbumMatch,
    generate_album_discovery,
)
from app.main import build_parser, main


def test_unknown_album_detection_and_local_suggestion(tmp_path):
    library_root = _make_library(tmp_path)

    result = generate_album_discovery(
        library_root=library_root,
        out_dir=tmp_path / "reports",
    )
    suggestions = _read_suggestions(tmp_path)

    assert result.total_tracks_checked == 3
    assert result.unknown_album_tracks == 2
    assert result.total_suggestions == 1
    assert suggestions[0] == {
        "file_path": "Metal/Static-X/Unknown Album/Wisconsin Death Trip - 01 - Push It.mp3",
        "artist": "Static-X",
        "title": "Push It",
        "current_album": "Unknown Album",
        "suggested_album": "Wisconsin Death Trip",
        "release_year": "",
        "confidence": "low",
        "confidence_reason": "Local filename evidence contains an album-like token; no external metadata was used.",
        "source": "local_filename",
        "source_url": "",
        "requires_human_review": True,
    }


def test_writes_csv_json_and_summary(tmp_path):
    library_root = _make_library(tmp_path)

    generate_album_discovery(library_root=library_root, out_dir=tmp_path / "reports")
    report_dir = tmp_path / "reports" / "album_discovery"

    assert (report_dir / "album_discovery_summary.json").exists()
    assert (report_dir / "album_discovery_suggestions.json").exists()
    assert _csv_headers(report_dir / "album_discovery_suggestions.csv") == list(
        SUGGESTION_HEADERS
    )
    csv_rows = _read_csv(report_dir / "album_discovery_suggestions.csv")
    assert csv_rows[0]["requires_human_review"] == "true"
    summary = json.loads(
        (report_dir / "album_discovery_summary.json").read_text(encoding="utf-8")
    )
    assert summary["low_confidence_count"] == 1
    assert summary["network_lookup_used"] is False


def test_network_lookup_is_opt_in(tmp_path):
    library_root = _make_library(tmp_path)
    lookup = FailingLookup()

    generate_album_discovery(
        library_root=library_root,
        out_dir=tmp_path / "reports",
        use_network=False,
        lookup_client=lookup,
    )

    assert lookup.calls == []


def test_mocked_external_lookup_sets_high_confidence(tmp_path):
    library_root = _make_library(tmp_path)
    lookup = StaticLookup(
        ExternalAlbumMatch(
            album="Wisconsin Death Trip",
            release_year="1999",
            confidence="high",
            confidence_reason="Exact artist/title match from MusicBrainz with one release candidate.",
            source="musicbrainz",
            source_url="https://musicbrainz.org/release/test-release",
        )
    )

    result = generate_album_discovery(
        library_root=library_root,
        out_dir=tmp_path / "reports",
        use_network=True,
        lookup_client=lookup,
    )
    suggestions = _read_suggestions(tmp_path)

    assert result.high_confidence_count == 2
    assert lookup.calls == [
        ("Deftones", "Change"),
        ("Static-X", "Push It"),
    ]
    assert suggestions[0]["confidence"] == "high"
    assert suggestions[0]["release_year"] == "1999"
    assert suggestions[0]["source"] == "musicbrainz"
    assert suggestions[0]["requires_human_review"] is True


def test_cache_behavior_for_musicbrainz_payload(tmp_path):
    library_root = _make_library(tmp_path)
    payload = {
        "recordings": [
            {
                "title": "Push It",
                "artist-credit": [{"name": "Static-X"}],
                "releases": [
                    {
                        "id": "release-1",
                        "title": "Wisconsin Death Trip",
                        "date": "1999-03-23",
                    }
                ],
            }
        ]
    }
    lookup = CachedPayloadLookup(payload)

    generate_album_discovery(
        library_root=library_root,
        out_dir=tmp_path / "reports",
        use_network=True,
        lookup_client=lookup,
    )
    cache_dir = tmp_path / "reports" / "album_discovery" / "cache"
    cache_files = sorted(cache_dir.glob("*.json"))

    assert len(cache_files) == 2
    assert lookup.fetch_count == 2

    generate_album_discovery(
        library_root=library_root,
        out_dir=tmp_path / "reports",
        use_network=True,
        lookup_client=lookup,
    )

    assert lookup.fetch_count == 2


def test_confidence_scoring_for_multiple_external_releases(tmp_path):
    library_root = _make_library(tmp_path)
    lookup = StaticLookup(
        ExternalAlbumMatch(
            album="Around the Fur",
            release_year="1997",
            confidence="medium",
            confidence_reason="Exact artist/title match from MusicBrainz, but 2 release candidates exist.",
            source="musicbrainz",
            source_url="https://musicbrainz.org/release/release-2",
        )
    )

    result = generate_album_discovery(
        library_root=library_root,
        out_dir=tmp_path / "reports",
        use_network=True,
        lookup_client=lookup,
    )

    assert result.medium_confidence_count == 2
    assert result.low_confidence_count == 0


def test_command_registration(tmp_path, capsys):
    library_root = _make_library(tmp_path)

    exit_code = main(
        [
            "discover-albums",
            "--library-root",
            str(library_root),
            "--out",
            str(tmp_path / "reports"),
        ]
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert f"report_path={tmp_path / 'reports' / 'album_discovery'}" in output
    assert "network_lookup_used=false" in output
    command_names = build_parser()._subparsers._group_actions[0].choices
    assert "discover-albums" in command_names


class FailingLookup:
    def __init__(self):
        self.calls = []

    def lookup(self, *, artist, title, cache_dir):
        self.calls.append((artist, title))
        raise AssertionError("network lookup should not run")


class StaticLookup:
    def __init__(self, match):
        self.match = match
        self.calls = []

    def lookup(self, *, artist, title, cache_dir):
        self.calls.append((artist, title))
        return self.match


class CachedPayloadLookup:
    def __init__(self, payload):
        self.payload = payload
        self.fetch_count = 0

    def lookup(self, *, artist, title, cache_dir):
        from app.album_discovery import (
            _cache_key,
            _match_from_musicbrainz_payload,
            _read_json,
            _write_json,
        )

        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path = cache_dir / f"{_cache_key(artist, title)}.json"
        if cache_path.exists():
            payload = _read_json(cache_path)
        else:
            self.fetch_count += 1
            payload = self.payload
            _write_json(cache_path, payload)
        return _match_from_musicbrainz_payload(payload, artist=artist, title=title)


def _make_library(tmp_path):
    library_root = tmp_path / "library"
    _touch(
        library_root
        / "Metal"
        / "Static-X"
        / "Unknown Album"
        / "Wisconsin Death Trip - 01 - Push It.mp3"
    )
    _touch(library_root / "Metal" / "Deftones" / "Unknown Album" / "Deftones - Change.mp3")
    _touch(library_root / "Metal" / "Chevelle" / "Wonder What's Next" / "Chevelle - Send.mp3")
    return library_root


def _touch(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")


def _read_suggestions(tmp_path):
    return json.loads(
        (
            tmp_path
            / "reports"
            / "album_discovery"
            / "album_discovery_suggestions.json"
        ).read_text(encoding="utf-8")
    )["suggestions"]


def _csv_headers(path):
    with path.open(newline="", encoding="utf-8") as file_handle:
        return next(csv.reader(file_handle))


def _read_csv(path):
    with path.open(newline="", encoding="utf-8") as file_handle:
        return list(csv.DictReader(file_handle))
