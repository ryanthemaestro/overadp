#!/usr/bin/env python3
"""Local Chrome rehearsal for the highest-risk draft-day behaviors."""

from __future__ import annotations

import argparse
import json
import tempfile
import time
from pathlib import Path
from urllib.parse import urljoin

from selenium import webdriver
from selenium.webdriver.common.action_chains import ActionChains
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

            injury_badge_count = len(
                driver.find_elements("css selector", "#playerPool details.injury-details")
            )
            expected_injury_badges = driver.execute_script(
                "return Number(dataMetadata.injuries?.skill_players_flagged||0)"
            )
            if injury_badge_count != expected_injury_badges:
                raise AssertionError(
                    "Injury badge count differs from metadata: "
                    f"{injury_badge_count} != {expected_injury_badges}"
                )
            driver.execute_script(
                """
                const host=document.createElement('div');
                host.id='injurySmokeFixture';
                host.style.cssText='position:fixed;left:8px;top:8px;z-index:99999;display:block';
                host.innerHTML=injuryBadgeHtml({
                  injury_status:'Questionable',
                  injury_body_part:'Knee',
                  practice_description:'Limited Participation in Practice',
                  injury_source_updated_at:new Date().toISOString(),
                });
                document.body.appendChild(host);
                """
            )
            injury_fixture = driver.find_element(
                "css selector", "#injurySmokeFixture details.injury-details"
            )
            injury_summary = injury_fixture.find_element("css selector", "summary")
            ActionChains(driver).move_to_element(injury_summary).perform()
            wait.until(
                lambda d: injury_fixture.find_element(
                    "css selector", ".injury-popover"
                ).value_of_css_property("display") == "block"
            )
            if injury_fixture.get_attribute("open"):
                raise AssertionError("Hover should reveal injury detail without opening the control")
            injury_popover = injury_fixture.find_element("css selector", ".injury-popover")
            ActionChains(driver).move_to_element(injury_popover).perform()
            time.sleep(0.2)
            if injury_popover.value_of_css_property("display") != "block":
                raise AssertionError("Injury detail should remain visible while moving into it")
            driver.execute_script("arguments[0].open=true", injury_fixture)
            injury_detail_text = injury_fixture.find_element(
                "css selector", ".injury-popover"
            ).get_attribute("textContent").strip()
            if "nflverse" not in injury_detail_text or "updated" not in injury_detail_text:
                raise AssertionError(f"Injury detail provenance is missing: {injury_detail_text}")
            injury_code_map = driver.execute_script(
                """
                return ['Questionable','Doubtful','Out'].map(status =>
                  injuryStatusInfo({injury_status:status}).code
                );
                """
            )
            if injury_code_map != ["Q", "D", "O"]:
                raise AssertionError(f"Injury status mapping failed: {injury_code_map}")
            preseason_injury_policy = driver.execute_script(
                """
                const prior=dataMetadata.injuries.reporting_mode;
                dataMetadata.injuries.reporting_mode='preseason_availability';
                const result={
                  neutral:injuryAvailabilityAdjustment({injury_status:'INJ'}).penalty,
                  reserve:injuryAvailabilityAdjustment({injury_status:'Injured Reserve'}).penalty,
                  code:injuryStatusInfo({injury_status:'INJ'}).code,
                };
                dataMetadata.injuries.reporting_mode=prior;
                return result;
                """
            )
            if preseason_injury_policy != {"neutral": 0, "reserve": 220, "code": "INJ"}:
                raise AssertionError(
                    f"Preseason injury policy failed: {preseason_injury_policy}"
                )
            preseason_outlook_policy = driver.execute_script(
                """
                const prior=dataMetadata.injuries.reporting_mode;
                dataMetadata.injuries.reporting_mode='preseason_availability';
                const projection=170;
                const result={
                  ready:injuryAvailabilityAdjustment({injury_status:'INJ',season_outlook:'expected_week_1',expected_games_missed:0,projected_points:projection}).penalty,
                  monitor:injuryAvailabilityAdjustment({injury_status:'INJ',season_outlook:'monitor_week_1',expected_games_missed:0.5,projected_points:projection}).penalty,
                  missed:injuryAvailabilityAdjustment({injury_status:'INJ',season_outlook:'expected_absence',expected_games_missed:2,projected_points:projection}).penalty,
                  season:injuryAvailabilityAdjustment({injury_status:'INJ',season_outlook:'season_out',expected_games_missed:17,projected_points:projection}).penalty,
                  codes:['expected_week_1','monitor_week_1','expected_absence','season_out'].map(season_outlook => injuryStatusInfo({injury_status:'INJ',season_outlook}).code),
                };
                dataMetadata.injuries.reporting_mode=prior;
                return result;
                """
            )
            if preseason_outlook_policy != {
                "ready": 0,
                "monitor": 6.2,
                "missed": 14.8,
                "season": 500,
                "codes": ["W1", "W1?", "MISS", "SZN"],
            }:
                raise AssertionError(
                    f"Preseason season-outlook policy failed: {preseason_outlook_policy}"
                )

            first_pick_recommendations = driver.execute_script(
                """
                scoringFormat='ppr';
                adjustScoring();
                buildDraftIntel();
                rosterConfig.draft_slot=1;
                myTeamIds=[];
                opponentIds=[];
                computeClientVBD();
                getRecommendations();
                const names=[...recommendedIds].map(id=>playerMap[id].player_name);
                scoringFormat='half_ppr';
                adjustScoring();
                buildDraftIntel();
                rosterConfig.draft_slot=6;
                computeClientVBD();
                getRecommendations();
                renderPlayerPool();
                return names;
                """
            )
            if "Jahmyr Gibbs" not in first_pick_recommendations:
                raise AssertionError(
                    f"Gibbs missing from PPR 1.01 recommendations: {first_pick_recommendations}"
                )
            if (
                "Kyren Williams" in first_pick_recommendations
                and first_pick_recommendations.index("Kyren Williams")
                < first_pick_recommendations.index("Jahmyr Gibbs")
            ):
                raise AssertionError(
                    f"Kyren incorrectly ranked above Gibbs at PPR 1.01: {first_pick_recommendations}"
                )

            driver.execute_script("currentFilter='K'; searchQuery=''; renderPlayerPool()")
            wait.until(
                lambda d: len(d.find_elements("css selector", "#playerPool tbody tr")) >= 33
            )
            kicker_rows = [
                row for row in driver.find_elements("css selector", "#playerPool tbody tr")
                if row.find_elements("css selector", ".name-cell")
            ]
            first_kicker = kicker_rows[0].find_element("css selector", ".name-cell").text.splitlines()[0]
            if first_kicker != "Cameron Dicker":
                raise AssertionError(f"Opening kicker rank failed: {first_kicker}")
            if len(kicker_rows[0].find_elements("css selector", ".matchup-chip")) != 3:
                raise AssertionError("Kicker row does not show three opening matchups")
            if "LAST ROUND" not in kicker_rows[0].text:
                raise AssertionError("Kicker row does not show last-round guidance")

            driver.execute_script("currentFilter='DEF'; renderPlayerPool()")
            wait.until(
                lambda d: len(d.find_elements("css selector", "#playerPool tbody tr")) >= 33
            )
            defense_rows = [
                row for row in driver.find_elements("css selector", "#playerPool tbody tr")
                if row.find_elements("css selector", ".name-cell")
            ]
            first_defense = defense_rows[0].find_element("css selector", ".name-cell").text.splitlines()[0]
            if first_defense != "LAC Defense":
                raise AssertionError(f"Opening defense rank failed: {first_defense}")
            if "FINAL 2 ROUNDS" not in defense_rows[0].text:
                raise AssertionError("Defense row does not show final-two-round guidance")

            recommendation_timing = driver.execute_script(
                """
                const skillIds=allPlayers.filter(p=>!['K','DEF'].includes(p.position)).map(p=>p.player_id);
                myTeamIds=[]; opponentIds=[]; getRecommendations();
                const early=[...recommendedIds].map(id=>playerMap[id].position);
                const draftTeam=[
                  ...allPlayers.filter(p=>p.position==='QB').slice(0,1),
                  ...allPlayers.filter(p=>p.position==='RB').slice(0,5),
                  ...allPlayers.filter(p=>p.position==='WR').slice(0,5),
                  ...allPlayers.filter(p=>p.position==='TE').slice(0,2)
                ].map(p=>p.player_id);
                const teamSet=new Set(draftTeam);
                const otherSkill=allPlayers
                  .filter(p=>!['K','DEF'].includes(p.position)&&!teamSet.has(p.player_id))
                  .sort((a,b)=>(Number(a.adp||200)-Number(b.adp||200))||(Number(b.projected_points||0)-Number(a.projected_points||0)))
                  .map(p=>p.player_id);
                myTeamIds=draftTeam; opponentIds=otherSkill.slice(0,143); getRecommendations();
                const round14=[...recommendedIds].map(id=>playerMap[id].position);
                const topDef=allPlayers.find(p=>p.position==='DEF'&&p.stream_rank===1);
                myTeamIds=[...draftTeam,topDef.player_id];
                opponentIds=otherSkill.slice(0,154); getRecommendations();
                const round15=[...recommendedIds].map(id=>playerMap[id].position);
                myTeamIds=[]; opponentIds=[]; currentFilter='ALL'; renderPlayerPool(); getRecommendations();
                return {early,round14,round15};
                """
            )
            if any(pos in {"K", "DEF"} for pos in recommendation_timing["early"]):
                raise AssertionError(f"K/DEF recommended early: {recommendation_timing}")
            if not {"DEF", "K"}.issubset(recommendation_timing["round14"]):
                raise AssertionError(f"Defense timing policy failed: {recommendation_timing}")
            if "K" not in recommendation_timing["round15"]:
                raise AssertionError(f"Kicker timing policy failed: {recommendation_timing}")

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

            funnel_result = driver.execute_async_script(
                """
                const done=arguments[arguments.length-1];
                window.__smokeEvents=[];
                window.gtag=(...args)=>window.__smokeEvents.push(args);
                currentUser=null;
                userPlan='free';
                userPlanType='draft';
                myTeamIds=[];
                opponentIds=[];
                recommendedIds=new Set();
                recommendationViewMilestones=new Set();
                demoStartedTracked=false;
                localStorage.setItem('oa_plan',JSON.stringify('free'));
                localStorage.setItem('oa_plan_type',JSON.stringify('draft'));
                localStorage.removeItem('oa_user');
                localStorage.setItem('warroom_myTeam',JSON.stringify([]));
                localStorage.setItem('warroom_opponentPicks',JSON.stringify([]));
                refreshAll();
                updateUserUI();
                const initialGuide=document.querySelector('.proof-guide')?.textContent||'';
                const initialAccess=document.getElementById('previewStatus').textContent;
                const firstTarget=[...recommendedIds][0];
                draftPlayer(firstTarget,'opponent');
                const changedTarget=[...recommendedIds][0];
                const changedGuide=document.querySelector('.proof-guide')?.textContent||'';
                draftPlayer(changedTarget,'mine');
                setTimeout(()=>{
                  const events=window.__smokeEvents
                    .filter(args=>args[0]==='event')
                    .map(args=>args[1]);
                  const overlay=document.getElementById('upgradeOverlay');
                  const result={
                    initialGuide,
                    initialAccess,
                    firstTarget,
                    changedTarget,
                    changedGuide,
                    pickCount:myTeamIds.length,
                    accessAfter:document.getElementById('previewStatus').textContent,
                    offerVisible:!overlay.classList.contains('hidden'),
                    offerHeadline:document.getElementById('upgradeHeadline').textContent,
                    seasonChoicePresent:!!overlay.querySelector('.upgrade-secondary'),
                    events,
                  };
                  done(result);
                },500);
                """
            )
            if funnel_result["initialAccess"] != "1 LIVE PICK":
                raise AssertionError(f"One-pick preview label failed: {funnel_result}")
            if "60-SECOND LIVE TEST" not in funnel_result["initialGuide"]:
                raise AssertionError(f"Proof guide missing: {funnel_result}")
            if funnel_result["firstTarget"] == funnel_result["changedTarget"]:
                raise AssertionError(f"TAKEN did not change the top target: {funnel_result}")
            if "BOARD UPDATED" not in funnel_result["changedGuide"]:
                raise AssertionError(f"Board-reaction guide missing: {funnel_result}")
            if funnel_result["pickCount"] != 1 or funnel_result["accessAfter"] != "UNLOCK DRAFT":
                raise AssertionError(f"One-pick gate failed: {funnel_result}")
            if not funnel_result["offerVisible"] or funnel_result["seasonChoicePresent"]:
                raise AssertionError(f"Focused single-draft offer failed: {funnel_result}")
            for event_name in ("recommendation_changed", "proof_demo_completed", "offer_shown"):
                if event_name not in funnel_result["events"]:
                    raise AssertionError(f"Missing funnel event {event_name}: {funnel_result}")

            driver.set_window_size(390, 844)
            driver.execute_script(
                """
                if(!document.getElementById('injurySmokeFixture')){
                  const host=document.createElement('div');
                  host.id='injurySmokeFixture';
                  host.style.cssText='position:fixed;left:8px;top:8px;z-index:99999;display:block';
                  host.innerHTML=injuryBadgeHtml({
                    injury_status:'Questionable',
                    injury_body_part:'Knee',
                    practice_description:'Limited Participation in Practice',
                    injury_source_updated_at:new Date().toISOString(),
                  });
                  document.body.appendChild(host);
                }
                """
            )
            mobile_injury = driver.find_element(
                "css selector", "#injurySmokeFixture details.injury-details"
            )
            if not mobile_injury.get_attribute("open"):
                driver.execute_script("arguments[0].open=true", mobile_injury)
            injury_rect = driver.execute_script(
                """
                const rect=arguments[0].querySelector('.injury-popover').getBoundingClientRect();
                return {left:rect.left,right:rect.right,width:rect.width};
                """,
                mobile_injury,
            )
            mobile_widths = driver.execute_script(
                "return {scroll:document.documentElement.scrollWidth,client:document.documentElement.clientWidth}"
            )
            if mobile_widths["scroll"] > mobile_widths["client"]:
                raise AssertionError(f"Mobile horizontal overflow: {mobile_widths}")
            if injury_rect["left"] < -1 or injury_rect["right"] > mobile_widths["client"] + 1:
                raise AssertionError(f"Mobile injury detail overflow: {injury_rect}")

            driver.get(urljoin(args.url, "../draft-assistant/"))
            wait.until(lambda d: d.find_element("css selector", "main h1").is_displayed())
            landing_widths = driver.execute_script(
                "return {scroll:document.documentElement.scrollWidth,client:document.documentElement.clientWidth}"
            )
            landing_ctas = [
                element.text
                for element in driver.find_elements("css selector", ".app-cta")
            ]
            if landing_widths["scroll"] > landing_widths["client"]:
                raise AssertionError(f"Landing-page mobile overflow: {landing_widths}")
            if not landing_ctas or any("5 PICKS" in label for label in landing_ctas):
                raise AssertionError(f"Landing-page offer is stale: {landing_ctas}")
            if "ASK THE AI WHO TO DRAFT NEXT" not in landing_ctas[0]:
                raise AssertionError(f"Landing-page CTA mismatch: {landing_ctas}")

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
                "ppr_1_01_recommendations": first_pick_recommendations,
                "injury_badges": injury_badge_count,
                "injury_detail": injury_detail_text,
                "injury_code_map": injury_code_map,
                "opening_kicker_1": first_kicker,
                "opening_defense_1": first_defense,
                "recommendation_timing": recommendation_timing,
                "saved_pick_survived_reload": True,
                "one_pick_funnel": funnel_result,
                "csv_backup_bytes": download_path.stat().st_size,
                "mobile_widths": mobile_widths,
                "mobile_injury_rect": injury_rect,
                "landing_mobile_widths": landing_widths,
                "landing_ctas": landing_ctas,
                "console_errors": 0,
            }, indent=2))
        finally:
            driver.quit()


if __name__ == "__main__":
    main()
