import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from app.demo_generator import (
    evidence_commands,
    generate_demo,
    render_terminal_frame,
)
from app.main import build_parser, main
from app.ui_screenshot_capture import screenshot_targets


PNG_BYTES = b"\x89PNG\r\n\x1a\n"


def test_evidence_command_mapping_is_stable():
    commands = evidence_commands()

    assert [command.display for command in commands] == [
        (
            "python -m app.main metadata-audit "
            "--library-root ~/Music/Organised_Library --out reports"
        ),
        (
            "python -m app.main metadata-plan "
            "--library-root ~/Music/Organised_Library --out reports"
        ),
        (
            "python -m app.main library-qa "
            "--library-root ~/Music/Organised_Library "
            "--quarantine-root ~/Music/Quarantine_Duplicates --out reports"
        ),
        "python -m pytest -q",
    ]


def test_render_terminal_frame_writes_png(tmp_path):
    destination = tmp_path / "frame.png"

    result = render_terminal_frame(
        command="python -m pytest -q",
        returncode=0,
        stdout="12 passed",
        stderr="",
        destination=destination,
    )

    assert result == destination
    assert destination.read_bytes().startswith(b"\x89PNG")


def test_generate_demo_creates_frames_manifest_and_script_without_ffmpeg(tmp_path):
    screenshot = tmp_path / "demo" / "frames" / "01_reports_dashboard.png"
    calls = []

    def fake_capture(*, output_dir):
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        screenshot.write_bytes(PNG_BYTES)
        return [screenshot]

    def fake_runner(argv):
        calls.append(tuple(argv))
        return subprocess.CompletedProcess(
            args=list(argv),
            returncode=0,
            stdout="ok",
            stderr="",
        )

    clock_values = iter(
        [
            datetime(2026, 1, 1, 12, minute, tzinfo=timezone.utc)
            for minute in range(9)
        ]
    )

    result = generate_demo(
        demo_dir=tmp_path / "demo",
        screenshot_capture=fake_capture,
        command_runner=fake_runner,
        clock=lambda: next(clock_values),
        ffmpeg_path="",
    )

    assert result.frames_dir == tmp_path / "demo" / "frames"
    assert result.frames_dir.is_dir()
    assert result.video_path is None
    assert result.regenerated_screenshot_count == 1
    assert len(result.frames) == 5
    assert len(calls) == 4
    assert result.script_path.read_text(encoding="utf-8").startswith("# Demo Script")

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["output_video_path"] is None
    assert manifest["ffmpeg_available"] is False
    assert manifest["frames"] == [str(path) for path in result.frames]
    assert [item["command"] for item in manifest["commands"]] == [
        command.display for command in evidence_commands()
    ]
    assert manifest["commands"][0]["started_at"] == "2026-01-01T12:00:00Z"
    assert manifest["commands"][0]["finished_at"] == "2026-01-01T12:01:00Z"


def test_generate_demo_clears_stale_frames_before_rebuild(tmp_path):
    demo_dir = tmp_path / "demo"
    frames_dir = demo_dir / "frames"
    frames_dir.mkdir(parents=True)
    stale_frame = frames_dir / "99_stale.png"
    stale_frame.write_bytes(PNG_BYTES)
    (demo_dir / "frames.txt").write_text("file '/old/frame.png'\n", encoding="utf-8")

    def fake_capture(*, output_dir):
        screenshot = Path(output_dir) / "01_reports_dashboard.png"
        screenshot.write_bytes(PNG_BYTES)
        return [screenshot]

    result = generate_demo(
        demo_dir=demo_dir,
        screenshot_capture=fake_capture,
        command_runner=_completed_command,
        clock=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc),
        ffmpeg_path="",
    )

    assert not stale_frame.exists()
    assert all(path.exists() for path in result.frames)
    assert "99_stale.png" not in (demo_dir / "frames.txt").read_text(encoding="utf-8")


def test_generate_demo_orders_frames_from_current_screenshot_targets(tmp_path):
    demo_dir = tmp_path / "demo"
    target_paths = [
        demo_dir / "frames" / target.filename for target in reversed(screenshot_targets())
    ]

    def fake_capture(*, output_dir):
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        for path in target_paths:
            path.write_bytes(PNG_BYTES)
        return target_paths

    result = generate_demo(
        demo_dir=demo_dir,
        screenshot_capture=fake_capture,
        command_runner=_completed_command,
        clock=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc),
        ffmpeg_path="",
    )

    assert [path.name for path in result.frames[:5]] == [
        "01_dashboard.png",
        "02_library_browser.png",
        "03_review_hub.png",
        "04_metadata_review.png",
        "05_player.png",
    ]


def test_generate_demo_includes_player_in_frames_and_manifest(tmp_path):
    demo_dir = tmp_path / "demo"

    def fake_capture(*, output_dir):
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        paths = []
        for target in screenshot_targets():
            path = Path(output_dir) / target.filename
            path.write_bytes(PNG_BYTES)
            paths.append(path)
        return paths

    result = generate_demo(
        demo_dir=demo_dir,
        screenshot_capture=fake_capture,
        command_runner=_completed_command,
        clock=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc),
        ffmpeg_path="",
    )

    frames_txt = (demo_dir / "frames.txt").read_text(encoding="utf-8")
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))

    player_frame = str((demo_dir / "frames" / "05_player.png"))
    assert player_frame in [str(path) for path in result.frames]
    assert "05_player.png" in frames_txt
    assert player_frame in manifest["frames"]


def test_generate_demo_synchronizes_manifest_with_frames_txt(tmp_path):
    demo_dir = tmp_path / "demo"

    def fake_capture(*, output_dir):
        screenshot = Path(output_dir) / "01_reports_dashboard.png"
        screenshot.write_bytes(PNG_BYTES)
        return [screenshot]

    result = generate_demo(
        demo_dir=demo_dir,
        screenshot_capture=fake_capture,
        command_runner=_completed_command,
        clock=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc),
        ffmpeg_path="",
    )

    frames_txt = (demo_dir / "frames.txt").read_text(encoding="utf-8")
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))

    assert manifest["frames"] == [str(path) for path in result.frames]
    for frame in result.frames:
        assert str(frame.resolve()) in frames_txt


def test_generate_demo_invokes_ffmpeg_when_available(tmp_path, monkeypatch):
    screenshot = tmp_path / "demo" / "frames" / "01_reports_dashboard.png"
    ffmpeg_calls = []

    def fake_capture(*, output_dir):
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        screenshot.write_bytes(PNG_BYTES)
        return [screenshot]

    def fake_runner(argv):
        return subprocess.CompletedProcess(
            args=list(argv),
            returncode=0,
            stdout="ok",
            stderr="",
        )

    def fake_subprocess_run(argv, *, check):
        ffmpeg_calls.append(argv)
        Path(argv[-1]).write_bytes(b"mp4")
        return subprocess.CompletedProcess(args=argv, returncode=0)

    monkeypatch.setattr("app.demo_generator.subprocess.run", fake_subprocess_run)

    result = generate_demo(
        demo_dir=tmp_path / "demo",
        screenshot_capture=fake_capture,
        command_runner=fake_runner,
        clock=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc),
        ffmpeg_path="/usr/bin/ffmpeg",
    )

    assert result.video_path == tmp_path / "demo" / "demo.mp4"
    assert result.video_path.read_bytes() == b"mp4"
    assert ffmpeg_calls[0][0] == "/usr/bin/ffmpeg"


def test_generate_demo_command_registration_behavior(monkeypatch, capsys, tmp_path):
    parser = build_parser()
    args = parser.parse_args(["generate-demo"])
    assert args.command == "generate-demo"

    class FakeResult:
        frames_dir = tmp_path / "demo" / "frames"
        frames = [frames_dir / "01_reports_dashboard.png"]
        regenerated_screenshot_count = 1
        manifest_path = tmp_path / "demo" / "demo_manifest.json"
        script_path = tmp_path / "demo" / "demo_script.md"
        video_path = None

    monkeypatch.setattr("app.main.generate_demo", lambda: FakeResult())

    assert main(["generate-demo"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "regenerated_screenshot_count=1",
        "frame_count=1",
        f"frames_dir={tmp_path / 'demo' / 'frames'}",
        f"manifest_path={tmp_path / 'demo' / 'demo_manifest.json'}",
        f"script_path={tmp_path / 'demo' / 'demo_script.md'}",
        "output_video_path=",
        "ffmpeg_available=false",
    ]


def _completed_command(argv):
    return subprocess.CompletedProcess(
        args=list(argv),
        returncode=0,
        stdout="ok",
        stderr="",
    )
