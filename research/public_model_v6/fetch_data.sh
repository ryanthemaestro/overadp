#!/usr/bin/env bash
# Downloads the public nflverse inputs (CC BY 4.0) into ./data
set -euo pipefail
mkdir -p data && cd data
B=https://github.com/nflverse/nflverse-data/releases/download
g(){ curl -fsSL -o "$2" "$B/$1"; }
for y in $(seq 2011 2025); do g stats_player/stats_player_week_$y.csv.gz spw_$y.csv.gz; done
g stats_player/stats_player_week_2026.csv.gz stats_player_week_2026.csv.gz
for y in $(seq 2013 2025); do g snap_counts/snap_counts_$y.csv.gz snaps_$y.csv.gz; done
for y in $(seq 2011 2023); do g weekly_rosters/roster_weekly_$y.csv rw_$y.csv; done
for y in 2024 2025; do g weekly_rosters/roster_weekly_$y.csv.gz rw_$y.csv.gz; done
g weekly_rosters/roster_weekly_2026.csv.gz roster_weekly_2026.csv.gz
for y in $(seq 2012 2025); do g depth_charts/depth_charts_$y.csv dc_$y.csv; done
g depth_charts/depth_charts_2026.csv.gz depth_charts_2026.csv.gz
for y in $(seq 2012 2025); do g pbp/play_by_play_$y.csv.gz pbp_$y.csv.gz; done
g players/players.csv.gz players.csv.gz
g combine/combine.csv.gz combine.csv.gz
