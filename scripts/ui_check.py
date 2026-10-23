"""Headless UI check: starts the server in-process, loads the page, visits all three tabs, reports
console errors, and saves screenshots to results/screens/. Needs `pip install playwright==1.64.0`.

    python scripts/ui_check.py            # uses APP_MODE from .env
    APP_MODE=mock python scripts/ui_check.py --lab --replay
"""

import argparse
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import uvicorn  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--lab", action="store_true", help="click 'Run Both on Same State'")
    ap.add_argument("--replay", type=int, default=0, help="run a live replay for N seconds")
    ap.add_argument("--bench", default="", help="stored benchmark job id to load")
    ap.add_argument("--stored", default="", help="stored replay run id to open for playback")
    ap.add_argument("--watch", type=int, default=0, help="press Play on the Watch tab for N seconds")
    a = ap.parse_args()
    srv = uvicorn.Server(uvicorn.Config("matchsense.server:app", port=a.port, log_level="warning"))
    threading.Thread(target=srv.run, daemon=True).start()
    while not srv.started:
        time.sleep(0.1)
    out = ROOT / "results" / "screens"
    out.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page(viewport={"width": 1280, "height": 900})
        page.on("console", lambda m: m.type == "error" and errors.append(m.text))
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"http://127.0.0.1:{a.port}/", wait_until="networkidle")
        page.wait_for_selector("#w-pitch svg")
        page.wait_for_function("document.querySelector('#w-a').textContent.length > 20", timeout=15000)
        if a.watch:
            page.click("#w-play")
            page.wait_for_timeout(a.watch * 1000)
            page.click("#w-play")
        page.screenshot(path=str(out / "watch.png"), full_page=True)
        page.click("#w-io summary")
        page.wait_for_selector("#w-io-body .io-call", timeout=15000)
        page.screenshot(path=str(out / "watch_io.png"), full_page=True)
        page.click("[data-tab=replay]")
        page.wait_for_selector("#rp-pitch svg")
        print("mode badge:", page.inner_text("#mode-badge"), "|", page.inner_text("#decider-status"), "|",
              page.inner_text("#bedrock-status"))
        if a.replay:
            page.click("#rp-live")
            page.wait_for_timeout(a.replay * 1000)
            print("replay source:", page.inner_text("#rp-source"))
        if a.stored:
            page.select_option("#rp-stored", a.stored)
            page.click("#rp-load")
            page.wait_for_selector("#rp-play:not([disabled])")
            page.fill("#rp-scrub", "40")
            page.dispatch_event("#rp-scrub", "input")
            page.wait_for_timeout(500)
            print("playback source:", page.inner_text("#rp-source"))
        page.screenshot(path=str(out / "replay.png"), full_page=True)
        page.click("[data-tab=lab]")
        page.wait_for_selector("#lab-pitch svg")
        page.wait_for_function("document.querySelector('#lab-text').textContent.length > 20")
        if a.lab:
            page.click("#lab-run-both")
            page.wait_for_function("!document.querySelector('#lab-run-both').classList.contains('loading')", timeout=60000)
        page.screenshot(path=str(out / "lab.png"), full_page=True)
        page.click("[data-tab=bench]")
        if a.bench:
            page.select_option("#b-stored", a.bench)
            page.click("#b-load")
            page.wait_for_selector("#b-results:not([hidden])")
            page.wait_for_timeout(1000)
        page.screenshot(path=str(out / "bench.png"), full_page=True)
        visible_err = page.locator("#error-box:not([hidden])")
        if visible_err.count():
            errors.append("UI error box: " + visible_err.inner_text())
        b.close()
    srv.should_exit = True
    print("screenshots:", out)
    print("console errors:", errors or "none")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
