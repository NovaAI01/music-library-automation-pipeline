from pathlib import Path

from app.main import build_parser, main
from tools.portfolio_demo.ui_screenshot_capture import (
    DEFAULT_OUTPUT_DIR,
    ScreenshotCaptureResult,
    ScreenshotFailure,
    capture_ui_screenshots,
    ensure_output_dir,
    output_paths,
    screenshot_targets,
    target_url,
)


def test_route_mapping_is_deterministic():
    targets = screenshot_targets()

    assert [(target.route, target.filename) for target in targets] == [
        ("/", "01_dashboard.png"),
        ("/library", "02_library_browser.png"),
        ("/review", "03_review_hub.png"),
        ("/review/metadata", "04_metadata_review.png"),
        ("/player", "05_player.png"),
    ]


def test_filename_generation_uses_output_directory(tmp_path):
    paths = output_paths(tmp_path)

    assert paths == [
        tmp_path / "01_dashboard.png",
        tmp_path / "02_library_browser.png",
        tmp_path / "03_review_hub.png",
        tmp_path / "04_metadata_review.png",
        tmp_path / "05_player.png",
    ]


def test_output_directory_creation_logic(tmp_path):
    screenshots = tmp_path / "docs" / "screenshots"

    result = ensure_output_dir(screenshots)

    assert result == screenshots
    assert screenshots.is_dir()


def test_capture_uses_mocked_browser_and_stable_urls(tmp_path):
    fake = FakePlaywright()

    generated = capture_ui_screenshots(
        base_url="http://127.0.0.1:8000",
        output_dir=tmp_path,
        wait_after_load_ms=25,
        playwright_factory=lambda: fake,
    )

    assert generated == output_paths(tmp_path)
    assert fake.browser.closed is True
    assert fake.page.viewport == {"width": 1440, "height": 1000}
    assert fake.page.urls == [
        "http://127.0.0.1:8000/",
        "http://127.0.0.1:8000/library",
        "http://127.0.0.1:8000/review",
        "http://127.0.0.1:8000/review/metadata",
        "http://127.0.0.1:8000/player",
    ]
    assert fake.page.goto_waits == ["domcontentloaded"] * 5
    assert fake.page.selectors == [("body", 10000)] * 5
    assert fake.page.waits == [25, 25, 25, 25, 25]
    assert fake.page.screenshot_paths == [str(path) for path in generated]
    assert generated.failed_count == 0


def test_capture_retries_failed_viewport_screenshot(tmp_path):
    retry_path = tmp_path / "02_library_browser.png"
    fake = FakePlaywright()
    fake.page.fail_once_screenshot_paths.add(str(retry_path))

    generated = capture_ui_screenshots(
        output_dir=tmp_path,
        wait_after_load_ms=25,
        playwright_factory=lambda: fake,
    )

    assert generated == output_paths(tmp_path)
    assert fake.page.screenshot_attempts.count(str(retry_path)) == 2
    assert 1000 in fake.page.waits


def test_capture_records_route_failure_and_continues(tmp_path, capsys):
    fake = FakePlaywright()
    fake.page.fail_goto_routes.add("/library")

    generated = capture_ui_screenshots(
        output_dir=tmp_path,
        wait_after_load_ms=25,
        playwright_factory=lambda: fake,
    )

    assert generated == [
        tmp_path / "01_dashboard.png",
        tmp_path / "03_review_hub.png",
        tmp_path / "04_metadata_review.png",
        tmp_path / "05_player.png",
    ]
    assert generated.failed_count == 1
    assert generated.failures[0].route == "/library"
    assert "failed_route=/library" in capsys.readouterr().err


def test_target_url_handles_base_url_slashes():
    assert (
        target_url("http://127.0.0.1:8000/", "/library")
        == "http://127.0.0.1:8000/library"
    )


def test_command_registration_behavior(monkeypatch, capsys):
    parser = build_parser()
    args = parser.parse_args(["capture-ui-screenshots"])
    assert args.command == "capture-ui-screenshots"

    def fake_capture():
        return ScreenshotCaptureResult(
            [
                DEFAULT_OUTPUT_DIR / "01_dashboard.png",
                DEFAULT_OUTPUT_DIR / "02_library_browser.png",
            ],
            [
                ScreenshotFailure(
                    route="/player",
                    path=DEFAULT_OUTPUT_DIR / "05_player.png",
                    error="timeout",
                )
            ],
        )

    monkeypatch.setattr("app.main.capture_ui_screenshots", fake_capture)

    assert main(["capture-ui-screenshots"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "captured=2",
        "failed=1",
        "tools/portfolio_demo/docs/screenshots/01_dashboard.png",
        "tools/portfolio_demo/docs/screenshots/02_library_browser.png",
    ]


def test_command_returns_nonzero_when_no_screenshots_are_captured(monkeypatch, capsys):
    monkeypatch.setattr(
        "app.main.capture_ui_screenshots",
        lambda: ScreenshotCaptureResult([], []),
    )

    assert main(["capture-ui-screenshots"]) == 1
    assert capsys.readouterr().out.splitlines() == [
        "captured=0",
        "failed=0",
    ]


class FakePlaywright:
    def __init__(self):
        self.page = FakePage()
        self.browser = FakeBrowser(self.page)
        self.chromium = FakeChromium(self.browser)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


class FakeChromium:
    def __init__(self, browser):
        self.browser = browser

    def launch(self, *, headless):
        assert headless is True
        return self.browser


class FakeBrowser:
    def __init__(self, page):
        self.page = page
        self.closed = False

    def new_page(self, *, viewport):
        self.page.viewport = viewport
        return self.page

    def close(self):
        self.closed = True


class FakePage:
    def __init__(self):
        self.viewport = None
        self.urls = []
        self.goto_waits = []
        self.selectors = []
        self.waits = []
        self.screenshot_paths = []
        self.screenshot_attempts = []
        self.fail_goto_routes = set()
        self.fail_once_screenshot_paths = set()

    def goto(self, url, *, wait_until):
        assert wait_until == "domcontentloaded"
        self.urls.append(url)
        self.goto_waits.append(wait_until)
        if any(route in url for route in self.fail_goto_routes):
            raise RuntimeError("navigation failed")

    def wait_for_selector(self, selector, *, timeout):
        assert selector == "body"
        assert timeout == 10000
        self.selectors.append((selector, timeout))

    def wait_for_timeout(self, milliseconds):
        self.waits.append(milliseconds)

    def screenshot(self, *, path, full_page):
        assert full_page is False
        self.screenshot_attempts.append(path)
        if path in self.fail_once_screenshot_paths:
            self.fail_once_screenshot_paths.remove(path)
            raise RuntimeError("screenshot failed")
        self.screenshot_paths.append(path)
        Path(path).write_bytes(b"png")
