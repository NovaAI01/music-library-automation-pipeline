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
        screenshot.write_bytes(b"\x89PNG\r\n\x1a\n")
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


def test_generate_demo_invokes_ffmpeg_when_available(tmp_path, monkeypatch):
    screenshot = tmp_path / "demo" / "frames" / "01_reports_dashboard.png"
    ffmpeg_calls = []

    def fake_capture(*, output_dir):
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        screenshot.write_bytes(b"\x89PNG\r\n\x1a\n")
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
        manifest_path = tmp_path / "demo" / "demo_manifest.json"
        script_path = tmp_path / "demo" / "demo_script.md"
        video_path = None

    monkeypatch.setattr("app.main.generate_demo", lambda: FakeResult())

    assert main(["generate-demo"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        f"frames_dir={tmp_path / 'demo' / 'frames'}",
        f"manifest_path={tmp_path / 'demo' / 'demo_manifest.json'}",
        f"script_path={tmp_path / 'demo' / 'demo_script.md'}",
        "video_path=",
        "ffmpeg_available=false",
    ]
