"""Browser smoke test for the rendered, entirely static atlas site.

This deliberately tests the built ``site/`` directory rather than source
templates.  It is invoked directly by the Phase 4 and Phase 6 gates once the
production payloads have been built; in a source-only checkout it skips.
"""

from __future__ import annotations

import gzip
import json
import os
import threading
from contextlib import contextmanager
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import pytest
from playwright.sync_api import Browser, Page, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
SITE = ROOT / "site"
DEFAULT_FIPS = "31109"


class _QuietStaticHandler(SimpleHTTPRequestHandler):
    """Serve the rendered artifact without making test output noisy."""

    def log_message(self, _format: str, *_args: object) -> None:
        pass


@contextmanager
def _server(site: Path):
    def handler(*args: object, **kwargs: object) -> _QuietStaticHandler:
        return _QuietStaticHandler(*args, directory=str(site), **kwargs)

    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def _agent_browser_chromium() -> str | None:
    """Use the installed agent-browser Chromium when Playwright has no copy."""
    configured = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE")
    if configured and Path(configured).is_file():
        return configured
    candidates = sorted(
        (Path.home() / ".agent-browser" / "browsers").glob(
            "chrome-*/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"
        )
    )
    return str(candidates[-1]) if candidates else None


@contextmanager
def _browser() -> Browser:
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch()
        except Exception as default_error:  # pragma: no cover - host-dependent fallback
            executable = _agent_browser_chromium()
            if executable is None:
                pytest.skip(f"Playwright Chromium is unavailable: {default_error}")
            browser = playwright.chromium.launch(executable_path=executable)
        try:
            yield browser
        finally:
            browser.close()


@pytest.fixture
def site_url() -> str:
    if not (SITE / "index.html").is_file():
        pytest.skip("site/ has not been built; run `wba site build`")
    with _server(SITE) as url:
        yield url


def _expected_drawer_values() -> dict[str, str]:
    """Read the same public payload used by the browser, never results/."""
    with gzip.open(SITE / f"data/county/{DEFAULT_FIPS}.json.gz", "rt") as stream:
        payload = json.load(stream)
    pair = payload["pairs"]["HDD-01"]
    pit = pair.get("pit", {})
    selected = str(pit.get("best_station") or pit.get("station_pit") or "—")
    hedge = next((row for row in pair.get("hedge", []) if row.get("s") == selected), {})
    with open(SITE / "data/stations.json") as stream:
        station_codes = {row.get("ghcn_id"): row.get("code") for row in json.load(stream)}
    return {
        "name": f"{payload['meta']['name']}, {payload['meta']['state']}",
        "best_code": station_codes.get(selected, selected),
        "he_pit": pit.get("he_pit"),
        "he_nearest": pit.get("he_nearest"),
        "es90_lower": hedge.get("es90_lower"),
    }


def _number_text(page: Page, selector: str) -> str:
    return page.locator(selector).inner_text().strip()


def _capture_console_error(errors: list[str], message: object) -> None:
    if getattr(message, "type", None) == "error":
        errors.append(str(getattr(message, "text", "console error")))


def test_static_atlas_smoke(site_url: str) -> None:
    """Exercise the map, payload decompression, controls, and narrow mobile layout."""
    expected = _expected_drawer_values()
    console_errors: list[str] = []
    page_errors: list[str] = []
    requests: list[str] = []

    with _browser() as browser:
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.on("console", lambda message: _capture_console_error(console_errors, message))
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.on("request", lambda request: requests.append(request.url))
        page.goto(f"{site_url}/index.html", wait_until="networkidle")
        page.wait_for_function(
            """() => document.querySelector('#county-name')?.textContent?.includes('Lancaster')"""
        )

        # A successful clear alone is not evidence that the map renderer drew.
        colors = page.locator("#atlas-map").evaluate(
            """canvas => {
                const pixels = canvas.getContext('2d').getImageData(0, 0, canvas.width,
                    canvas.height).data;
                const seen = new Set();
                for (let i = 0; i < pixels.length; i += 400) {
                    seen.add([pixels[i], pixels[i + 1], pixels[i + 2], pixels[i + 3]].join(','));
                }
                return seen.size;
            }"""
        )
        assert colors > 1, "canvas contains only a blank clear colour"

        # Confirm the gzipped county response is decoded by browser-native APIs.
        decoded = page.evaluate(
            """async () => {
                const response = await fetch('data/county/31109.json.gz');
                const stream = response.body.pipeThrough(new DecompressionStream('gzip'));
                return JSON.parse(await new Response(stream).text()).meta.fips;
            }"""
        )
        assert decoded == DEFAULT_FIPS

        assert _number_text(page, "#county-name") == expected["name"]
        assert _number_text(page, "#best-station").startswith(f"{expected['best_code']} · h ")
        # Displayed percentage precision is intentionally checked from the shipped value,
        # rather than against a hard-coded metric.
        for selector, value in (
            ("#he-nearest", expected["he_nearest"]),
        ):
            assert value is not None
            shown = _number_text(page, selector)
            assert shown not in {"", "—"}
            assert abs(float(shown.rstrip("%").replace(",", "")) / 100 - float(value)) <= 0.0005
        assert _number_text(page, "#he-pit").startswith(f"{float(expected['he_pit']) * 100:.1f}%")
        assert _number_text(page, "#es90-tail") not in {"", "—"}

        page.locator("button[data-layer='station']").click()
        assert page.locator("button[data-layer='station']").get_attribute("aria-pressed") == "true"
        search = page.locator("#county-search")
        search.fill("Cook")
        search.press("Enter")
        page.wait_for_function(
            """() => document.querySelector('#county-name')?.textContent?.includes('Cook')"""
        )

        # A shared link restores every selection dimension, and the map's keyboard
        # selection updates that link without a server round-trip.
        page.goto(f"{site_url}/index.html#fips=17031&idx=CDD&m=07&layer=station")
        page.wait_for_function(
            """() => document.querySelector('#county-name')?.textContent?.includes('Cook')
              && document.querySelector('#pair').value === 'CDD-07'"""
        )
        assert page.locator("button[data-layer='station']").get_attribute("aria-pressed") == "true"
        canvas = page.locator("#atlas-map")
        canvas.focus()
        canvas.press("ArrowRight")
        canvas.press("Enter")
        page.wait_for_function("() => location.hash.includes('fips=17033')")

        # Station markers must be exposed to both visual users and assistive tech.
        assert page.locator("#station-key").inner_text().strip(), (
            "station legend/markers were not rendered"
        )

        assert all(urlparse(url).netloc == urlparse(site_url).netloc for url in requests), requests
        assert not page_errors, page_errors
        assert not console_errors, console_errors

        mobile = browser.new_page(viewport={"width": 375, "height": 812})
        mobile_errors: list[str] = []
        mobile.on("pageerror", lambda error: mobile_errors.append(str(error)))
        mobile.goto(f"{site_url}/index.html", wait_until="networkidle")
        mobile.wait_for_function(
            "() => document.querySelector('#county-name')?.textContent?.includes('Lancaster')"
        )
        assert mobile.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth")
        assert not mobile_errors, mobile_errors
