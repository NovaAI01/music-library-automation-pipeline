"""Deterministic local demo artifact generation."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import textwrap
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Sequence

from PIL import Image, ImageDraw, ImageFont

from app.ui_screenshot_capture import capture_ui_screenshots, screenshot_targets


DEFAULT_DEMO_DIR = Path("demo")
FRAME_SIZE = (1280, 720)
FRAME_BACKGROUND = (14, 18, 24)
FRAME_FOREGROUND = (232, 237, 243)
FRAME_MUTED = (137, 148, 162)


@dataclass(frozen=True)
class EvidenceCommand:
    slug: str
    display: str
    argv: tuple[str, ...]


@dataclass(frozen=True)
class DemoCommandResult:
    command: str
    argv: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    started_at: str
    finished_at: str
    frame: Path


@dataclass(frozen=True)
class DemoGenerationResult:
    frames_dir: Path
    frames: list[Path]
    regenerated_screenshot_count: int
    commands: list[DemoCommandResult]
    script_path: Path
    manifest_path: Path
    video_path: Path | None
    ffmpeg_available: bool


CommandRunner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]
ScreenshotCapture = Callable[..., list[Path]]
Clock = Callable[[], datetime]


def evidence_commands() -> tuple[EvidenceCommand, ...]:
    home = Path.home()
    library_root = home / "Music" / "Organised_Library"
    quarantine_root = home / "Music" / "Quarantine_Duplicates"
    return (
        EvidenceCommand(
            slug="metadata_audit",
            display=(
                "python -m app.main metadata-audit "
                "--library-root ~/Music/Organised_Library --out reports"
            ),
            argv=(
                sys.executable,
                "-m",
                "app.main",
                "metadata-audit",
                "--library-root",
                str(library_root),
                "--out",
                "reports",
            ),
        ),
        EvidenceCommand(
            slug="metadata_plan",
            display=(
                "python -m app.main metadata-plan "
                "--library-root ~/Music/Organised_Library --out reports"
            ),
            argv=(
                sys.executable,
                "-m",
                "app.main",
                "metadata-plan",
                "--library-root",
                str(library_root),
                "--out",
                "reports",
            ),
        ),
        EvidenceCommand(
            slug="library_qa",
            display=(
                "python -m app.main library-qa "
                "--library-root ~/Music/Organised_Library "
                "--quarantine-root ~/Music/Quarantine_Duplicates --out reports"
            ),
            argv=(
                sys.executable,
                "-m",
                "app.main",
                "library-qa",
                "--library-root",
                str(library_root),
                "--quarantine-root",
                str(quarantine_root),
                "--out",
                "reports",
            ),
        ),
        EvidenceCommand(
            slug="pytest",
            display="python -m pytest -q",
            argv=(sys.executable, "-m", "pytest", "-q"),
        ),
    )


def generate_demo(
    *,
    demo_dir: str | Path = DEFAULT_DEMO_DIR,
    screenshot_capture: ScreenshotCapture = capture_ui_screenshots,
    command_runner: CommandRunner | None = None,
    clock: Clock | None = None,
    ffmpeg_path: str | None = None,
) -> DemoGenerationResult:
    root = Path(demo_dir)
    frames_dir = root / "frames"
    frames_txt_path = root / "frames.txt"
    root.mkdir(parents=True, exist_ok=True)
    if frames_dir.exists():
        shutil.rmtree(frames_dir)
    frames_dir.mkdir(parents=True, exist_ok=True)
    frames_txt_path.unlink(missing_ok=True)

    now = clock or _utc_now
    runner = command_runner or _run_command
    frames: list[Path] = []
    commands: list[DemoCommandResult] = []

    captured_screenshots = screenshot_capture(output_dir=frames_dir)
    screenshot_frames = _ordered_screenshot_frames(frames_dir, captured_screenshots)
    frames.extend(screenshot_frames)

    for index, command in enumerate(evidence_commands(), start=len(frames) + 1):
        started_at = _timestamp(now())
        completed = runner(command.argv)
        finished_at = _timestamp(now())
        frame = frames_dir / f"{index:02d}_{command.slug}.png"
        render_terminal_frame(
            command=command.display,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            destination=frame,
        )
        frames.append(frame)
        commands.append(
            DemoCommandResult(
                command=command.display,
                argv=tuple(command.argv),
                returncode=completed.returncode,
                stdout=completed.stdout,
                stderr=completed.stderr,
                started_at=started_at,
                finished_at=finished_at,
                frame=frame,
            )
        )

    script_path = root / "demo_script.md"
    write_demo_script(script_path)

    ffmpeg = ffmpeg_path if ffmpeg_path is not None else shutil.which("ffmpeg")
    video_path: Path | None = None
    frames_txt_path.write_text(_concat_file(frames), encoding="utf-8")
    if ffmpeg:
        video_path = root / "demo.mp4"
        stitch_frames(ffmpeg, frames, video_path, frames_txt_path)

    manifest_path = root / "demo_manifest.json"
    write_manifest(
        manifest_path=manifest_path,
        frames=frames,
        commands=commands,
        script_path=script_path,
        video_path=video_path,
        ffmpeg_available=bool(ffmpeg),
        generated_at=_timestamp(now()),
    )

    return DemoGenerationResult(
        frames_dir=frames_dir,
        frames=frames,
        regenerated_screenshot_count=len(captured_screenshots),
        commands=commands,
        script_path=script_path,
        manifest_path=manifest_path,
        video_path=video_path,
        ffmpeg_available=bool(ffmpeg),
    )


def _ordered_screenshot_frames(
    frames_dir: Path,
    captured_screenshots: Sequence[Path],
) -> list[Path]:
    captured_paths = [Path(path) for path in captured_screenshots]
    captured_set = {path.resolve() for path in captured_paths if path.exists()}
    ordered_paths = [frames_dir / target.filename for target in screenshot_targets()]
    frames = [path for path in ordered_paths if path.resolve() in captured_set]
    known_names = {path.name for path in ordered_paths}
    frames.extend(
        path
        for path in captured_paths
        if path.exists() and path.name not in known_names
    )
    return frames


def render_terminal_frame(
    *,
    command: str,
    returncode: int,
    stdout: str,
    stderr: str,
    destination: str | Path,
) -> Path:
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", FRAME_SIZE, FRAME_BACKGROUND)
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    x = 56
    y = 48
    line_height = 18

    draw.text((x, y), "$ " + command, fill=(121, 213, 164), font=font)
    y += line_height * 2
    draw.text(
        (x, y),
        f"exit_code={returncode}",
        fill=FRAME_MUTED if returncode == 0 else (248, 113, 113),
        font=font,
    )
    y += line_height * 2

    for line in _wrap_terminal_lines(_terminal_body(stdout=stdout, stderr=stderr)):
        if y > FRAME_SIZE[1] - 56:
            draw.text((x, y), "...", fill=FRAME_MUTED, font=font)
            break
        draw.text((x, y), line, fill=FRAME_FOREGROUND, font=font)
        y += line_height

    image.save(destination)
    return destination


def write_demo_script(destination: str | Path) -> Path:
    destination = Path(destination)
    destination.write_text(
        textwrap.dedent(
            """\
            # Demo Script

            This demo shows the Media Library Automation Pipeline as a local,
            reproducible workflow. First, the report UI opens on the generated
            evidence pages: the reports dashboard, duplicate analysis, library
            QA, metadata audit, and manual duplicate review. These screens are
            read-only views over files already produced by the pipeline.

            Next, the demo switches to terminal evidence. The metadata audit
            checks the organised library for readable FLAC files and tag
            quality. The metadata plan proposes deterministic tag corrections
            without editing the media files. The library QA report compares the
            organised library and duplicate quarantine state. Finally, the test
            suite runs with pytest to show that the pipeline behavior is still
            covered.

            The video is built from generated screenshots and command-output
            frames only. There is no live screen recording, voice synthesis, or
            AI narration in the artifact.
            """
        ),
        encoding="utf-8",
    )
    return destination


def write_manifest(
    *,
    manifest_path: str | Path,
    frames: Sequence[Path],
    commands: Sequence[DemoCommandResult],
    script_path: Path,
    video_path: Path | None,
    ffmpeg_available: bool,
    generated_at: str,
) -> Path:
    manifest_path = Path(manifest_path)
    payload = {
        "generated_at": generated_at,
        "frames": [str(path) for path in frames],
        "commands": [
            {
                "command": result.command,
                "argv": list(result.argv),
                "returncode": result.returncode,
                "started_at": result.started_at,
                "finished_at": result.finished_at,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "frame": str(result.frame),
            }
            for result in commands
        ],
        "script_path": str(script_path),
        "output_video_path": str(video_path) if video_path else None,
        "ffmpeg_available": ffmpeg_available,
    }
    manifest_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return manifest_path


def stitch_frames(
    ffmpeg: str,
    frames: Sequence[Path],
    video_path: str | Path,
    concat_path: str | Path,
) -> Path:
    video_path = Path(video_path)
    concat_path = Path(concat_path)
    concat_path.write_text(_concat_file(frames), encoding="utf-8")
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_path),
            "-vf",
            (
                "scale=1280:720:force_original_aspect_ratio=decrease,"
                "pad=1280:720:(ow-iw)/2:(oh-ih)/2,format=yuv420p"
            ),
            "-r",
            "30",
            str(video_path),
        ],
        check=True,
    )
    return video_path


def _concat_file(frames: Sequence[Path]) -> str:
    lines: list[str] = []
    for frame in frames:
        escaped = str(frame.resolve()).replace("'", "'\\''")
        lines.append(f"file '{escaped}'")
        lines.append("duration 7")
    if frames:
        escaped = str(frames[-1].resolve()).replace("'", "'\\''")
        lines.append(f"file '{escaped}'")
    return "\n".join(lines) + "\n"


def _run_command(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(argv),
        capture_output=True,
        text=True,
        check=False,
    )


def _terminal_body(*, stdout: str, stderr: str) -> str:
    chunks = []
    if stdout.strip():
        chunks.append(stdout.strip())
    if stderr.strip():
        chunks.append("[stderr]\n" + stderr.strip())
    return "\n\n".join(chunks) or "(no output)"


def _wrap_terminal_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw_line in text.splitlines():
        if not raw_line:
            lines.append("")
            continue
        lines.extend(textwrap.wrap(raw_line, width=132) or [""])
    return lines


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
