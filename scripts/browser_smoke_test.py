#!/usr/bin/env python3
"""Local Chrome rehearsal for the highest-risk draft-day behaviors."""

from __future__ import annotations

import argparse
import json
import tempfile
import time
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8765/app/")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="overadp-browser-") as download_dir:
        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1440,900")
        options.set_capability("goog:loggingPrefs", {"browser": "ALL"})
        options.add_experimental_option("prefs", {
            "download.default_directory": download_dir,
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
        })

        driver = webdriver.Chrome(options=options)
        try:
            wait = WebDriverWait(driver, 20)
            driver.get(args.url)
            driver.execute_script(
                """
                localStorage.setItem('oa_plan', JSON.stringify('paid'));
                localStorage.setItem('oa_plan_type', JSON.stringify('season'));
                localStorage.setItem('oa_user', JSON.stringify({id:'smoke-test',email:'smoke@example.invalid'}));
                """
            )
            driver.refresh()
            wait.until(
                lambda d: d.execute_script(
                    "return typeof allPlayers==='undefined'?0:allPlayers.length"
                ) >= 900
            )
            wait.until(lambda d: len(d.find_elements("css selector", "#playerPool tbody tr")) >= 900)

            player_count = driver.execute_script("return allPlayers.length")
            status_text = driver.find_element("id", "dataStatus").text
            status_color = driver.find_element("id", "dataStatus").value_of_css_property("color")
            first_ten = [
                row.find_element("css selector", ".name-cell").text.splitlines()[0]
                for row in driver.find_elements("css selector", "#playerPool tbody tr")[:10]
                if row.find_elements("css selector", ".name-cell")
            ]
            if "Jahmyr Gibbs" not in first_ten or "Puka Nacua" not in first_ten:
                raise AssertionError(f"Top-ten sanity failed: {first_ten}")

            gibbs_id = driver.execute_script(
                "return allPlayers.find(p=>p.player_name==='Jahmyr Gibbs').player_id"
            )
            driver.execute_script("draftPlayer(arguments[0], 'mine')", gibbs_id)
            if driver.execute_script("return myTeamIds.length") != 1:
                raise AssertionError("Draft action did not update the local roster")
            driver.refresh()
            wait.until(
                lambda d: d.execute_script(
                    "return typeof allPlayers==='undefined'?0:allPlayers.length"
                ) >= 900
            )
            wait.until(
                lambda d: d.execute_script(
                    "return typeof myTeamIds==='undefined'?-1:myTeamIds.length"
                ) == 1
            )

            driver.execute_script("exportDraftBoard()")
            download_path = None
            deadline = time.time() + 10
            while time.time() < deadline:
                candidates = list(Path(download_dir).glob("overadp-draft-board-*.csv"))
                if candidates and candidates[0].stat().st_size > 10000:
                    download_path = candidates[0]
                    break
                time.sleep(0.2)
            if download_path is None:
                raise AssertionError("CSV backup was not downloaded")

            driver.set_window_size(390, 844)
            mobile_widths = driver.execute_script(
                "return {scroll:document.documentElement.scrollWidth,client:document.documentElement.clientWidth}"
            )
            if mobile_widths["scroll"] > mobile_widths["client"]:
                raise AssertionError(f"Mobile horizontal overflow: {mobile_widths}")

            severe_logs = [
                entry for entry in driver.get_log("browser")
                if entry.get("level") == "SEVERE"
                and "google-analytics.com" not in entry.get("message", "")
                and "googletagmanager.com" not in entry.get("message", "")
            ]
            if severe_logs:
                raise AssertionError(f"Browser console errors: {severe_logs[:5]}")

            print(json.dumps({
                "player_count": player_count,
                "data_status": status_text,
                "data_status_color": status_color,
                "top_ten": first_ten,
                "saved_pick_survived_reload": True,
                "csv_backup_bytes": download_path.stat().st_size,
                "mobile_widths": mobile_widths,
                "console_errors": 0,
            }, indent=2))
        finally:
            driver.quit()


if __name__ == "__main__":
    main()
