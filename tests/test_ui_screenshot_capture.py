from pathlib import Path

from app.main import build_parser, main
from app.ui_screenshot_capture import (
    DEFAULT_OUTPUT_DIR,
    capture_ui_screenshots,
    ensure_output_dir,
    output_paths,
    screenshot_targets,
    target_url,
)


def test_route_mapping_is_deterministic():
    targets = screenshot_targets()

    assert [(target.route, target.filename) for target in targets] == [
        ("/reports", "01_reports_dashboard.png"),
        ("/reports/duplicates/latest", "02_duplicate_report.png"),
        ("/reports/library-qa/latest", "03_library_qa.png"),
        ("/reports/metadata/latest", "04_metadata_audit.png"),
        ("/review/duplicates/latest", "05_manual_review.png"),
        ("/review/metadata-suggestions", "06_metadata_suggestions.png"),
    ]


def test_filename_generation_uses_output_directory(tmp_path):
    paths = output_paths(tmp_path)

    assert paths == [
        tmp_path / "01_reports_dashboard.png",
        tmp_path / "02_duplicate_report.png",
        tmp_path / "03_library_qa.png",
        tmp_path / "04_metadata_audit.png",
        tmp_path / "05_manual_review.png",
        tmp_path / "06_metadata_suggestions.png",
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
        "http://127.0.0.1:8000/reports",
        "http://127.0.0.1:8000/reports/duplicates/latest",
        "http://127.0.0.1:8000/reports/library-qa/latest",
        "http://127.0.0.1:8000/reports/metadata/latest",
        "http://127.0.0.1:8000/review/duplicates/latest",
        "http://127.0.0.1:8000/review/metadata-suggestions",
    ]
    assert fake.page.waits == [25, 25, 25, 25, 25, 25]
    assert fake.page.screenshot_paths == [str(path) for path in generated]


def test_target_url_handles_base_url_slashes():
    assert (
        target_url("http://127.0.0.1:8000/", "/reports")
        == "http://127.0.0.1:8000/reports"
    )


def test_command_registration_behavior(monkeypatch, capsys):
    parser = build_parser()
    args = parser.parse_args(["capture-ui-screenshots"])
    assert args.command == "capture-ui-screenshots"

    def fake_capture():
        return [
            DEFAULT_OUTPUT_DIR / "01_reports_dashboard.png",
            DEFAULT_OUTPUT_DIR / "02_duplicate_report.png",
        ]

    monkeypatch.setattr("app.main.capture_ui_screenshots", fake_capture)

    assert main(["capture-ui-screenshots"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "docs/screenshots/01_reports_dashboard.png",
        "docs/screenshots/02_duplicate_report.png",
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
        self.waits = []
        self.screenshot_paths = []

    def goto(self, url, *, wait_until):
        assert wait_until == "networkidle"
        self.urls.append(url)

    def wait_for_timeout(self, milliseconds):
        self.waits.append(milliseconds)

    def screenshot(self, *, path, full_page):
        assert full_page is True
        self.screenshot_paths.append(path)
        Path(path).write_bytes(b"png")
