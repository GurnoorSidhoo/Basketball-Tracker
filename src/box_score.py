from __future__ import annotations

from datetime import datetime

import pandas as pd


SCORING_EVENTS = {"2pt_make": 2, "3pt_make": 3, "ft_make": 1}
SHOT_ATTEMPTS_2 = {"2pt_make", "2pt_miss"}
SHOT_ATTEMPTS_3 = {"3pt_make", "3pt_miss"}
FT_ATTEMPTS = {"ft_make", "ft_miss"}
REBOUND_OFF = {"rebound_off"}
REBOUND_DEF = {"rebound_def"}


def _blank_statline() -> dict:
    return {
        "player": "",
        "team": "",
        "PTS": 0,
        "FGM": 0,
        "FGA": 0,
        "3PM": 0,
        "3PA": 0,
        "FTM": 0,
        "FTA": 0,
        "OREB": 0,
        "DREB": 0,
        "REB": 0,
        "AST": 0,
        "STL": 0,
        "BLK": 0,
        "TOV": 0,
        "PF": 0,
        "PLUS_MINUS": 0,
        "SECONDS": 0,
        "MIN": "0:00",
    }


def _normalize_label(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned or cleaned.lower() == "unknown":
        return None
    return cleaned


def _event_player_label(event: dict, fallback_team: str) -> str:
    player_name = _normalize_label(event.get("player_name"))
    if player_name:
        return player_name

    player_label = _normalize_label(event.get("player"))
    if player_label:
        return player_label

    jersey = _normalize_label(event.get("jersey"))
    if jersey:
        return f"{fallback_team} #{jersey}"
    return f"{fallback_team} Unknown"


def _ensure_player(stats: dict[str, dict], player: str, team: str) -> dict:
    if player not in stats:
        stats[player] = _blank_statline()
        stats[player]["player"] = player
        stats[player]["team"] = team
    return stats[player]


def _window_identity(window: dict) -> str:
    return str(
        window.get("segment_start_iso")
        or window.get("clip_path")
        or window.get("segment_file")
        or window.get("window_start")
    )


def _window_sort_value(window: dict) -> tuple[int, str]:
    if window.get("segment_start_iso"):
        return (0, str(window["segment_start_iso"]))
    return (1, f"{int(window.get('window_start', 0)):08d}")


def _credit_minutes(stats: dict[str, dict], windows: list[dict], team_a_label: str, team_b_label: str) -> None:
    seen_windows: set[str] = set()
    for window in sorted(windows, key=_window_sort_value):
        window_key = _window_identity(window)
        if window_key in seen_windows:
            continue
        seen_windows.add(window_key)

        credit = int(max(0, round(float(window.get("credit_seconds", 0)))))
        if credit <= 0:
            continue

        for player in window.get("on_court_team_a", []):
            statline = _ensure_player(stats, player or f"{team_a_label} Unknown", team=team_a_label)
            statline["SECONDS"] += credit
        for player in window.get("on_court_team_b", []):
            statline = _ensure_player(stats, player or f"{team_b_label} Unknown", team=team_b_label)
            statline["SECONDS"] += credit


def _window_contains_event(window: dict, event: dict) -> bool:
    event_absolute = event.get("absolute_game_time_iso")
    window_start_iso = window.get("segment_start_iso")
    window_end_iso = window.get("segment_end_iso")
    if event_absolute and window_start_iso and window_end_iso:
        event_dt = datetime.fromisoformat(event_absolute)
        return datetime.fromisoformat(window_start_iso) <= event_dt <= datetime.fromisoformat(window_end_iso)

    global_sec = event.get("global_sec")
    if global_sec is None:
        return False
    return float(window.get("window_start", 0)) <= float(global_sec) <= float(window.get("window_end", 0))


def _window_for_event(raw_windows: list[dict], event: dict) -> dict | None:
    candidates = [window for window in raw_windows if _window_contains_event(window, event)]
    if not candidates:
        return None
    return max(candidates, key=_window_sort_value)


def _apply_plus_minus(stats: dict[str, dict], raw_windows: list[dict], event: dict, team_a_label: str, team_b_label: str) -> None:
    if event["type"] not in SCORING_EVENTS or not raw_windows:
        return

    window = _window_for_event(raw_windows, event)
    if window is None:
        return

    points = SCORING_EVENTS[event["type"]]
    event_team = str(event.get("team", "")).strip().lower()
    team_a_players = window.get("on_court_team_a", [])
    team_b_players = window.get("on_court_team_b", [])

    if not event_team:
        return

    if event_team == team_a_label.lower():
        for player in team_a_players:
            _ensure_player(stats, player, team=team_a_label)["PLUS_MINUS"] += points
        for player in team_b_players:
            _ensure_player(stats, player, team=team_b_label)["PLUS_MINUS"] -= points
    elif event_team == team_b_label.lower():
        for player in team_b_players:
            _ensure_player(stats, player, team=team_b_label)["PLUS_MINUS"] += points
        for player in team_a_players:
            _ensure_player(stats, player, team=team_a_label)["PLUS_MINUS"] -= points


def build_box_score(
    *,
    raw_windows: list[dict] | None,
    deduped_events: list[dict],
    team_a_label: str,
    team_b_label: str,
) -> pd.DataFrame:
    stats: dict[str, dict] = {}
    raw_windows = raw_windows or []

    if raw_windows:
        _credit_minutes(stats, raw_windows, team_a_label=team_a_label, team_b_label=team_b_label)

    for event in deduped_events:
        team = str(event.get("team") or "Unknown")
        player = _event_player_label(event, fallback_team=team)
        statline = _ensure_player(stats, player, team=team)
        event_type = event["type"]

        if event_type in SHOT_ATTEMPTS_2:
            statline["FGA"] += 1
        if event_type == "2pt_make":
            statline["FGM"] += 1
            statline["PTS"] += 2

        if event_type in SHOT_ATTEMPTS_3:
            statline["FGA"] += 1
            statline["3PA"] += 1
        if event_type == "3pt_make":
            statline["FGM"] += 1
            statline["3PM"] += 1
            statline["PTS"] += 3

        if event_type in FT_ATTEMPTS:
            statline["FTA"] += 1
        if event_type == "ft_make":
            statline["FTM"] += 1
            statline["PTS"] += 1

        if event_type in REBOUND_OFF:
            statline["OREB"] += 1
            statline["REB"] += 1
        if event_type in REBOUND_DEF:
            statline["DREB"] += 1
            statline["REB"] += 1

        if event_type == "steal":
            statline["STL"] += 1
        if event_type == "block":
            statline["BLK"] += 1
        if event_type == "turnover":
            statline["TOV"] += 1
        if event_type == "foul":
            statline["PF"] += 1

        assist_by = _normalize_label(event.get("assist_by"))
        if assist_by:
            _ensure_player(stats, assist_by, team)["AST"] += 1

        _apply_plus_minus(stats, raw_windows, event, team_a_label=team_a_label, team_b_label=team_b_label)

    rows = list(stats.values())
    rows.sort(key=lambda row: (row["team"], row["player"]))

    for row in rows:
        minutes = row["SECONDS"] // 60
        seconds = row["SECONDS"] % 60
        row["MIN"] = f"{minutes}:{seconds:02d}"

    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=list(_blank_statline().keys()))

    return df[
        [
            "player",
            "team",
            "MIN",
            "PTS",
            "FGM",
            "FGA",
            "3PM",
            "3PA",
            "FTM",
            "FTA",
            "OREB",
            "DREB",
            "REB",
            "AST",
            "STL",
            "BLK",
            "TOV",
            "PF",
            "PLUS_MINUS",
        ]
    ]
