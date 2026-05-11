"""Deterministic Playwright screenshot capture for local report UI pages."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin


DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_OUTPUT_DIR = Path("docs/screenshots")
DEFAULT_VIEWPORT = {"width": 1440, "height": 1000}


@dataclass(frozen=True)
class ScreenshotTarget:
    route: str
    filename: str


SCREENSHOT_TARGETS = (
    ScreenshotTarget("/reports", "01_reports_dashboard.png"),
    ScreenshotTarget("/reports/duplicates/latest", "02_duplicate_report.png"),
    ScreenshotTarget("/reports/library-qa/latest", "03_library_qa.png"),
    ScreenshotTarget("/reports/metadata/latest", "04_metadata_audit.png"),
    ScreenshotTarget("/review/duplicates/latest", "05_manual_review.png"),
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
) -> list[Path]:
    root = ensure_output_dir(output_dir)
    viewport_size = viewport or DEFAULT_VIEWPORT
    generated_paths: list[Path] = []
    factory = playwright_factory or _load_playwright_factory()

    with factory() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport=viewport_size)
            for target in SCREENSHOT_TARGETS:
                destination = root / target.filename
                page.goto(target_url(base_url, target.route), wait_until="networkidle")
                page.wait_for_timeout(wait_after_load_ms)
                page.screenshot(path=str(destination), full_page=True)
                generated_paths.append(destination)
        finally:
            browser.close()

    return generated_paths


def _load_playwright_factory() -> Callable[[], Any]:
    try:
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Playwright is required for screenshot capture. Install dependencies "
            "and run: playwright install chromium"
        ) from exc
    return sync_playwright
