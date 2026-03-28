from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta


POINT_EVENTS = {"2pt_make": 2, "3pt_make": 3, "ft_make": 1}


def mmss_to_seconds(value: str) -> int:
    mm, ss = value.split(":")
    return int(mm) * 60 + int(ss)


def _parse_iso_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


def _sort_timestamp(event: dict) -> float:
    absolute_value = _parse_iso_timestamp(event.get("absolute_game_time_iso"))
    if absolute_value is not None:
        return absolute_value.timestamp()
    return float(event.get("global_sec", 0))


def _compare_seconds(a: dict, b: dict) -> float:
    a_abs = _parse_iso_timestamp(a.get("absolute_game_time_iso"))
    b_abs = _parse_iso_timestamp(b.get("absolute_game_time_iso"))
    if a_abs is not None and b_abs is not None:
        return abs((a_abs - b_abs).total_seconds())
    if (a_abs is None) != (b_abs is None):
        return float("inf")
    return abs(float(a.get("global_sec", 0)) - float(b.get("global_sec", 0)))


def _normalize_team(event: dict) -> str:
    return str(event.get("team", "")).strip().lower()


def _normalize_text(value: object) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip().lower()
    if not cleaned or cleaned == "unknown":
        return None
    return cleaned


def _identity_parts(event: dict, prefix: str = "") -> dict[str, str | None]:
    return {
        "team": _normalize_text(event.get(f"{prefix}team")) or _normalize_team(event),
        "jersey": _normalize_text(event.get(f"{prefix}jersey")),
        "name": _normalize_text(event.get(f"{prefix}player_name")),
        "label": _normalize_text(event.get(f"{prefix}player")),
    }


def _supporting_identity_text(event: dict, key: str) -> str | None:
    value = _normalize_text(event.get(key))
    return value


def _identity_matches(a: dict, b: dict, prefix: str = "") -> bool:
    a_identity = _identity_parts(a, prefix=prefix)
    b_identity = _identity_parts(b, prefix=prefix)

    a_team = a_identity["team"]
    b_team = b_identity["team"]
    if a_team and b_team and a_team != b_team:
        return False

    a_jersey = a_identity["jersey"]
    b_jersey = b_identity["jersey"]
    if a_jersey and b_jersey and a_jersey != b_jersey:
        return False

    a_name = a_identity["name"] or a_identity["label"]
    b_name = b_identity["name"] or b_identity["label"]
    if a_name and b_name and a_name != b_name:
        if a_jersey and b_jersey and a_jersey == b_jersey:
            return True
        if a_jersey or b_jersey:
            return False

    return True


def _field_matches(a: dict, b: dict, key: str) -> bool:
    left = _supporting_identity_text(a, key)
    right = _supporting_identity_text(b, key)
    if left and right and left != right:
        return False
    return True


def _event_specificity(event: dict) -> int:
    score = 0
    if _normalize_text(event.get("player_name")):
        score += 3
    if _normalize_text(event.get("jersey")):
        score += 2
    if _normalize_text(event.get("assist_by")):
        score += 1
    if _normalize_text(event.get("against_player")):
        score += 1
    identity_method = _normalize_text(event.get("identity_method"))
    if identity_method == "face_hint":
        score += 1
    return score


def _preferred_event(a: dict, b: dict) -> dict:
    a_rank = (float(a.get("confidence", 0)), _event_specificity(a))
    b_rank = (float(b.get("confidence", 0)), _event_specificity(b))
    return a if a_rank >= b_rank else b


def enrich_events(raw_windows: list[dict]) -> list[dict]:
    enriched: list[dict] = []
    for window in raw_windows:
        segment_start = _parse_iso_timestamp(window.get("segment_start_iso"))
        for event in window.get("events", []):
            item = deepcopy(event)
            clip_seconds = mmss_to_seconds(item["time"])
            item["window_start"] = window.get("window_start", 0)
            item["window_end"] = window.get("window_end", 0)
            item["camera_id"] = item.get("camera_id") or window.get("camera_id")
            item["segment_file"] = item.get("segment_file") or window.get("segment_file")
            item["segment_start_iso"] = item.get("segment_start_iso") or window.get("segment_start_iso")
            item["segment_end_iso"] = item.get("segment_end_iso") or window.get("segment_end_iso")
            item["global_sec"] = window.get("window_start", 0) + clip_seconds
            if segment_start is not None:
                item["absolute_game_time_iso"] = (segment_start + timedelta(seconds=clip_seconds)).isoformat(timespec="seconds")
            elif item.get("absolute_game_time_iso"):
                item["absolute_game_time_iso"] = datetime.fromisoformat(item["absolute_game_time_iso"]).isoformat(
                    timespec="seconds"
                )
            if item.get("points") is None and item["type"] in POINT_EVENTS:
                item["points"] = POINT_EVENTS[item["type"]]
            enriched.append(item)
    return sort_events(enriched)


def sort_events(events: list[dict]) -> list[dict]:
    return sorted(
        events,
        key=lambda event: (
            _sort_timestamp(event),
            str(event.get("type", "")),
            str(event.get("team", "")),
            str(event.get("player_name") or event.get("player") or ""),
        ),
    )


def same_event(a: dict, b: dict, time_buffer: float = 2.0) -> bool:
    if _compare_seconds(a, b) > time_buffer:
        return False

    if _normalize_text(a.get("type")) != _normalize_text(b.get("type")):
        return False
    if _normalize_team(a) != _normalize_team(b):
        return False
    if not _identity_matches(a, b):
        return False
    if not _field_matches(a, b, "assist_by"):
        return False
    if not _field_matches(a, b, "against_player"):
        return False
    return True


def deduplicate_event_list(events: list[dict], time_buffer: float = 2.0) -> list[dict]:
    deduped: list[dict] = []

    for current in sort_events(events):
        duplicate_index = None
        for idx, existing in enumerate(deduped):
            if same_event(current, existing, time_buffer=time_buffer):
                duplicate_index = idx
                break

        if duplicate_index is None:
            deduped.append(current)
            continue

        deduped[duplicate_index] = _preferred_event(current, deduped[duplicate_index])

    return sort_events(deduped)


def deduplicate_events(raw_windows: list[dict], time_buffer: float = 2.0) -> list[dict]:
    return deduplicate_event_list(enrich_events(raw_windows), time_buffer=time_buffer)
