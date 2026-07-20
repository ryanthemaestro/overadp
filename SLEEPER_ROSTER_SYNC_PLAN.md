# Sleeper roster sync plan

## Outcome

Give an OverADP user a league-aware weekly assistant that reads their Sleeper
league, identifies their team, sets the model to the league's real roster and
scoring rules, and recommends starts, sits, pickups, and drops. The first
release is decision support only; it does not place transactions or wagers.

Sleeper's [official API](https://docs.sleeper.com/) is public and read-only. It
does not require an API token and cannot modify a lineup or roster. The product
must state that limitation clearly instead of presenting a recommendation as
an executed move.

## Milestone 1: read-only league connection

1. Ask for a Sleeper username; resolve and store the stable `user_id` locally.
2. List the user's NFL leagues for the active season and let them select one.
3. Fetch the league, users, rosters, current matchups, and recent transactions.
4. Match `owner_id` to the selected user and normalize Sleeper player IDs to
   OverADP player IDs.
5. Import team count, scoring settings, starter slots, FLEX/Superflex rules,
   bench size, rostered players, current starters, and waiver priority/FAAB.
6. Show the league name, team, current week, and last refresh time before any
   recommendation.

Core endpoints:

- `GET /v1/user/{username}`
- `GET /v1/user/{user_id}/leagues/nfl/{season}`
- `GET /v1/league/{league_id}`
- `GET /v1/league/{league_id}/users`
- `GET /v1/league/{league_id}/rosters`
- `GET /v1/league/{league_id}/matchups/{week}`
- `GET /v1/league/{league_id}/transactions/{week}`
- `GET /v1/state/nfl`
- `GET /v1/players/nfl` and `/v1/players/nfl/trending/{type}`

## Milestone 2: recommendations

- Optimize the legal weekly starting lineup using projected points, injury
  status, uncertainty, and the league's exact scoring and slot rules.
- Rank free agents by expected improvement over the user's weakest starter or
  bench hold—not raw projected points.
- Show an explicit suggested add, conditional drop, FAAB range, lineup impact,
  confidence, and the facts that could reverse the choice.
- Refresh after injuries, transactions, or model updates while caching the
  player catalog daily and staying well below Sleeper's documented limit of
  1,000 requests per minute.
- Provide a Sleeper deep link and a copyable checklist for each move; the user
  confirms and performs the transaction in Sleeper.

## Milestone 3: betting research, separately gated

If player-prop or daily-fantasy analysis is added, keep it separate from roster
recommendations. Compare a timestamped market line with a calibrated outcome
distribution, retain line movement and closing-line value, and display both
model edge and uncertainty. Do not auto-place wagers. Require age and location
eligibility, user-set exposure limits, and prominent responsible-play controls
before exposing money-related features.

## Data and reliability requirements

- Cache league data briefly, but include a manual refresh before lock.
- Persist Sleeper IDs as strings; usernames may change.
- Version player-ID mappings and flag unresolved or duplicate matches.
- Never log a full fetched roster payload with user-identifying metadata.
- Fail closed when scoring or slot rules cannot be represented exactly.
- Test standard, half-PPR, PPR, tight-end premium, Superflex, dynasty, IR, taxi,
  and leagues with empty roster slots.
- Validate lineup recommendations against an independent legal-slot checker.

## Acceptance gate

The first release is ready when a user can connect by username, select a league,
see the correct roster and rules, reproduce the recommendation after refresh,
and receive no illegal lineup or roster suggestion across the test matrix.
