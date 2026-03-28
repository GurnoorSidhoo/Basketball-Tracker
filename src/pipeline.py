from __future__ import annotations

import json
import os
import shutil
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv

from .box_score import build_box_score
from .config import GameConfig
from .dedupe import deduplicate_events
from .gemini_client import GeminiScout
from .prompts import build_user_prompt
from .roster import build_prompt_roster_context, collect_team_a_headshots
from .video_utils import build_windows, extract_clip, get_video_duration_seconds


DEFAULT_MODEL_NAME = "gemini-3.1-flash-lite-preview"


def require_env(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if value is None or value == "":
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def create_scout(config: GameConfig) -> GeminiScout:
    load_dotenv()
    api_key = require_env("GEMINI_API_KEY")
    model_name = require_env("MODEL_NAME", config.model_name or DEFAULT_MODEL_NAME)
    return GeminiScout(api_key=api_key, model_name=model_name, max_retries=config.max_retries)


def _clip_context_for_batch(window_start: int, window_end: int) -> str:
    return f"full-video window from {window_start}s to {window_end}s"


def _clip_context_for_segment(segment_start_iso: str, segment_end_iso: str) -> str:
    return f"recorded wall-clock segment from {segment_start_iso} to {segment_end_iso}"


def _build_prompt(config: GameConfig, clip_label: str, clip_context: str) -> str:
    return build_user_prompt(
        clip_label=clip_label,
        clip_context=clip_context,
        team_a_name=config.team_a_name,
        team_b_name=config.team_b_name,
        roster_context=build_prompt_roster_context(config),
        headshots_available=bool(config.team_a_headshot_paths),
    )


def analyze_clip_to_record(
    *,
    scout: GeminiScout,
    config: GameConfig,
    clip_path: Path,
    window_start: int,
    window_end: int,
    credit_seconds: int,
    camera_id: str,
    segment_file: str | None = None,
    segment_start_iso: str | None = None,
    segment_end_iso: str | None = None,
) -> dict:
    clip_context = (
        _clip_context_for_segment(segment_start_iso, segment_end_iso)
        if segment_start_iso and segment_end_iso
        else _clip_context_for_batch(window_start, window_end)
    )
    prompt = _build_prompt(config, clip_label=clip_path.name, clip_context=clip_context)
    result = scout.analyze_clip(
        clip_path=str(clip_path),
        prompt=prompt,
        window_start=window_start,
        window_end=window_end,
        reference_image_paths=collect_team_a_headshots(config),
    )
    return {
        "window_start": result.window_start,
        "window_end": result.window_end,
        "on_court_team_a": result.on_court_team_a,
        "on_court_team_b": result.on_court_team_b,
        "events": [event.model_dump(mode="json") for event in result.events],
        "clip_path": str(clip_path),
        "camera_id": camera_id,
        "segment_file": segment_file,
        "segment_start_iso": segment_start_iso,
        "segment_end_iso": segment_end_iso,
        "credit_seconds": credit_seconds,
    }


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record))
            handle.write("\n")


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records: list[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if stripped:
                records.append(json.loads(stripped))
    return records


def _score_by_team(events: list[dict]) -> dict[str, int]:
    scores: defaultdict[str, int] = defaultdict(int)
    for event in events:
        points = event.get("points")
        team = str(event.get("team") or "Unknown")
        if points:
            scores[team] += int(points)
    return dict(scores)


def _recent_event_line(event: dict) -> str:
    timestamp = event.get("absolute_game_time_iso") or event.get("time") or event.get("global_sec")
    team = event.get("team") or "Unknown"
    player = event.get("player_name") or event.get("player") or "Unknown"
    return f"- {timestamp} | {team} | {event['type']} | {player}"


def build_summary_text(config: GameConfig, deduped_events: list[dict], box_score_rows: list[dict], recent_limit: int = 5) -> str:
    scores = _score_by_team(deduped_events)
    top_scorers = sorted(box_score_rows, key=lambda row: (-int(row.get("PTS", 0)), row.get("player", "")))[:5]
    lines = [
        f"Game: {config.game_id}",
        f"Camera: {config.camera_id}",
        f"Score: {config.team_a_name} {scores.get(config.team_a_name, 0)} - {config.team_b_name} {scores.get(config.team_b_name, 0)}",
        "",
        "Top scorers:",
    ]
    if top_scorers:
        for row in top_scorers:
            lines.append(f"- {row['player']} ({row['team']}): {row['PTS']} pts")
    else:
        lines.append("- No scoring events yet")

    lines.append("")
    lines.append("Last 5 events:")
    recent_events = deduped_events[-recent_limit:]
    if recent_events:
        for event in recent_events:
            lines.append(_recent_event_line(event))
    else:
        lines.append("- No events yet")
    return "\n".join(lines)


def recompute_outputs(*, raw_records: list[dict], output_dir: Path, config: GameConfig) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    deduped_events = deduplicate_events(raw_records, time_buffer=config.dedupe_time_buffer)
    deduped_path = output_dir / "deduped_events.json"
    deduped_path.write_text(json.dumps(deduped_events, indent=2), encoding="utf-8")

    box_score_df = build_box_score(
        raw_windows=raw_records,
        deduped_events=deduped_events,
        team_a_label=config.team_a_name,
        team_b_label=config.team_b_name,
    )
    box_score_path = output_dir / "box_score.csv"
    box_score_df.to_csv(box_score_path, index=False)

    summary_text = build_summary_text(
        config=config,
        deduped_events=deduped_events,
        box_score_rows=box_score_df.to_dict(orient="records"),
    )
    summary_path = output_dir / "summary.txt"
    summary_path.write_text(summary_text + "\n", encoding="utf-8")

    return {
        "deduped_events": deduped_events,
        "deduped_path": deduped_path,
        "box_score_path": box_score_path,
        "summary_path": summary_path,
        "summary_text": summary_text,
    }


def run_batch(*, config: GameConfig, input_video: str | Path, output_dir: Path, clips_dir: Path) -> dict[str, Path | str | list[dict]]:
    input_video_path = Path(input_video).expanduser().resolve()
    if not input_video_path.exists():
        raise FileNotFoundError(f"Input video not found: {input_video_path}")

    duration = get_video_duration_seconds(str(input_video_path))
    windows = build_windows(
        total_duration=duration,
        window_seconds=config.segment_seconds,
        step_seconds=config.batch_step_seconds,
    )

    if clips_dir.exists():
        shutil.rmtree(clips_dir)
    clips_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    scout = create_scout(config)
    raw_records: list[dict] = []

    for idx, (start_sec, end_sec) in enumerate(windows, start=1):
        clip_path = clips_dir / f"clip_{idx:03d}_{start_sec:05d}_{end_sec:05d}.mp4"
        print(f"[{idx}/{len(windows)}] Extracting {clip_path.name}")
        extract_clip(
            input_video=str(input_video_path),
            output_clip=str(clip_path),
            start_sec=start_sec,
            end_sec=end_sec,
        )

        print(f"[{idx}/{len(windows)}] Analyzing with Gemini")
        credit_seconds = int(min(config.batch_step_seconds, max(0, round(duration - start_sec))))
        credit_seconds = max(1, credit_seconds)
        raw_records.append(
            analyze_clip_to_record(
                scout=scout,
                config=config,
                clip_path=clip_path,
                window_start=start_sec,
                window_end=end_sec,
                credit_seconds=credit_seconds,
                camera_id=config.camera_id,
            )
        )

    raw_path = output_dir / "raw_windows.json"
    raw_path.write_text(json.dumps(raw_records, indent=2), encoding="utf-8")

    outputs = recompute_outputs(raw_records=raw_records, output_dir=output_dir, config=config)
    return {
        "raw_path": raw_path,
        **outputs,
    }
