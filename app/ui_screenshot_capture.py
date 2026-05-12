"""Deterministic Playwright screenshot capture for local report UI pages."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Any, Callable
from urllib.parse import urljoin


DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_OUTPUT_DIR = Path("docs/screenshots")
DEFAULT_VIEWPORT = {"width": 1440, "height": 1000}


@dataclass(frozen=True)
class ScreenshotTarget:
    route: str
    filename: str


@dataclass(frozen=True)
class ScreenshotFailure:
    route: str
    path: Path
    error: str


class ScreenshotCaptureResult(list[Path]):
    def __init__(
        self,
        captured_paths: list[Path],
        failures: list[ScreenshotFailure] | None = None,
    ) -> None:
        super().__init__(captured_paths)
        self.failures = failures or []

    @property
    def captured_count(self) -> int:
        return len(self)

    @property
    def failed_count(self) -> int:
        return len(self.failures)


SCREENSHOT_TARGETS = (
    ScreenshotTarget("/", "01_dashboard.png"),
    ScreenshotTarget("/library", "02_library_browser.png"),
    ScreenshotTarget("/review", "03_review_hub.png"),
    ScreenshotTarget("/review/metadata", "04_metadata_review.png"),
    ScreenshotTarget("/player", "05_player.png"),
)


def screenshot_targets() -> tuple[ScreenshotTarget, ...]:
    return SCREENSHOT_TARGETS


def output_paths(
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    targets: tuple[ScreenshotTarget, ...] = SCREENSHOT_TARGETS,
) -> list[Path]:
    root = Path(output_dir)
    return [root / target.filename for target in targets]


def ensure_output_dir(output_dir: str | Path = DEFAULT_OUTPUT_DIR) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root


def target_url(base_url: str, route: str) -> str:
    return urljoin(base_url.rstrip("/") + "/", route.lstrip("/"))


def capture_ui_screenshots(
    *,
    base_url: str = DEFAULT_BASE_URL,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    viewport: dict[str, int] | None = None,
    wait_after_load_ms: int = 500,
    playwright_factory: Callable[[], Any] | None = None,
) -> ScreenshotCaptureResult:
    root = ensure_output_dir(output_dir)
    viewport_size = viewport or DEFAULT_VIEWPORT
    generated_paths: list[Path] = []
    failures: list[ScreenshotFailure] = []
    factory = playwright_factory or _load_playwright_factory()

    with factory() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport=viewport_size)
            for target in SCREENSHOT_TARGETS:
                destination = root / target.filename
                try:
                    page.goto(
                        target_url(base_url, target.route),
                        wait_until="domcontentloaded",
                    )
                    page.wait_for_selector("body", timeout=10000)
                    page.wait_for_timeout(wait_after_load_ms)
                    try:
                        page.screenshot(path=str(destination), full_page=False)
                    except Exception:
                        page.wait_for_timeout(1000)
                        page.screenshot(path=str(destination), full_page=False)
                    generated_paths.append(destination)
                except Exception as exc:
                    failures.append(
                        ScreenshotFailure(
                            route=target.route,
                            path=destination,
                            error=str(exc),
                        )
                    )
                    print(
                        f"failed_route={target.route} path={destination} error={exc}",
                        file=sys.stderr,
                    )
        finally:
            browser.close()

    return ScreenshotCaptureResult(generated_paths, failures)


def _load_playwright_factory() -> Callable[[], Any]:
    try:
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Playwright is required for screenshot capture. Install dependencies "
            "and run: playwright install chromium"
        ) from exc
    return sync_playwright
