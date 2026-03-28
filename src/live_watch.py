from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .config import GameConfig
from .pipeline import analyze_clip_to_record, create_scout, load_jsonl, recompute_outputs, write_jsonl
from .video_utils import get_video_duration_seconds


def _local_timezone():
    return datetime.now().astimezone().tzinfo


def parse_segment_start_iso(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(
            f"Invalid segment_start_iso '{value}'. Use ISO-8601, for example 2026-03-16T19:30:15+11:00"
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_local_timezone())
    return parsed


def parse_segment_filename(segment_path: Path) -> tuple[str, datetime]:
    stem = segment_path.stem
    if "__" not in stem:
        raise ValueError(
            f"Segment filename must look like <camera_id>__YYYYMMDDTHHMMSS.mp4: {segment_path.name}"
        )
    camera_id, timestamp_token = stem.rsplit("__", 1)
    segment_start = datetime.strptime(timestamp_token, "%Y%m%dT%H%M%S").replace(tzinfo=_local_timezone())
    return camera_id, segment_start


def load_manifest(path: Path, config: GameConfig) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {
        "game_id": config.game_id,
        "camera_id": config.camera_id,
        "segments": {},
    }


def save_manifest(path: Path, manifest: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def _append_raw_record(*, output_dir: Path, raw_record: dict, config: GameConfig) -> dict[str, Any]:
    raw_jsonl_path = output_dir / "raw_segments.jsonl"
    raw_records = load_jsonl(raw_jsonl_path)
    candidate_records = [*raw_records, raw_record]
    outputs = recompute_outputs(raw_records=candidate_records, output_dir=output_dir, config=config)
    staging_path = output_dir / "raw_segments.jsonl.tmp"
    write_jsonl(staging_path, candidate_records)
    staging_path.replace(raw_jsonl_path)
    return {
        "raw_record": raw_record,
        "raw_jsonl_path": raw_jsonl_path,
        **outputs,
    }


def _next_window_start(raw_records: list[dict]) -> int:
    if not raw_records:
        return 0
    return max(int(record.get("window_end", 0)) for record in raw_records)


def process_segment_file(*, config: GameConfig, scout, segment_path: Path, output_dir: Path) -> dict[str, Any]:
    parsed_camera_id, segment_start = parse_segment_filename(segment_path)
    if parsed_camera_id != config.camera_id:
        raise ValueError(
            f"Segment camera_id {parsed_camera_id} does not match config camera_id {config.camera_id}"
        )

    segment_duration = max(1.0, get_video_duration_seconds(str(segment_path)))
    segment_end = segment_start + timedelta(seconds=segment_duration)
    raw_record = analyze_clip_to_record(
        scout=scout,
        config=config,
        clip_path=segment_path,
        window_start=0,
        window_end=max(1, int(round(segment_duration))),
        credit_seconds=max(1, int(round(segment_duration))),
        camera_id=config.camera_id,
        segment_file=segment_path.name,
        segment_start_iso=segment_start.isoformat(timespec="seconds"),
        segment_end_iso=segment_end.isoformat(timespec="seconds"),
    )
    return _append_raw_record(output_dir=output_dir, raw_record=raw_record, config=config)


def process_uploaded_clip(
    *,
    config: GameConfig,
    scout,
    input_video: str | Path,
    output_dir: Path,
    camera_id: str | None = None,
    segment_start_iso: str | None = None,
) -> dict[str, Any]:
    clip_path = Path(input_video).expanduser().resolve()
    if not clip_path.exists():
        raise FileNotFoundError(f"Input clip not found: {clip_path}")

    raw_jsonl_path = output_dir / "raw_segments.jsonl"
    existing_records = load_jsonl(raw_jsonl_path)
    window_start = _next_window_start(existing_records)

    segment_start = parse_segment_start_iso(segment_start_iso) if segment_start_iso else None
    segment_duration = max(1.0, get_video_duration_seconds(str(clip_path)))
    rounded_duration = max(1, int(round(segment_duration)))
    segment_end = segment_start + timedelta(seconds=segment_duration) if segment_start is not None else None
    resolved_camera_id = (camera_id or config.camera_id).strip()
    if not resolved_camera_id:
        raise ValueError("camera_id cannot be blank")

    raw_record = analyze_clip_to_record(
        scout=scout,
        config=config,
        clip_path=clip_path,
        window_start=window_start,
        window_end=window_start + rounded_duration,
        credit_seconds=rounded_duration,
        camera_id=resolved_camera_id,
        segment_file=clip_path.name,
        segment_start_iso=segment_start.isoformat(timespec="seconds") if segment_start is not None else None,
        segment_end_iso=segment_end.isoformat(timespec="seconds") if segment_end is not None else None,
    )
    return _append_raw_record(output_dir=output_dir, raw_record=raw_record, config=config)


def run_upload(
    *,
    config: GameConfig,
    input_video: str | Path,
    output_dir: Path,
    camera_id: str | None = None,
    segment_start_iso: str | None = None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    scout = create_scout(config)
    return process_uploaded_clip(
        config=config,
        scout=scout,
        input_video=input_video,
        output_dir=output_dir,
        camera_id=camera_id,
        segment_start_iso=segment_start_iso,
    )


def _failure_manifest_entry(
    *,
    previous_entry: dict[str, Any],
    size_bytes: int | None,
    stage: str,
    exc: Exception,
) -> dict[str, Any]:
    return {
        "status": "failed",
        "stage": stage,
        "failed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "size_bytes": size_bytes,
        "attempts": int(previous_entry.get("attempts", 0)) + 1,
        "error_type": type(exc).__name__,
        "error_message": str(exc),
    }


def watch_segments(*, config: GameConfig, segments_dir: str | Path, output_dir: Path) -> None:
    segments_path = Path(segments_dir).expanduser().resolve()
    segments_path.mkdir(parents=True, exist_ok=True)

    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "manifest.json"
    manifest = load_manifest(manifest_path, config)
    scout = create_scout(config)
    stable_sizes: dict[str, int] = {}
    failed_this_run: set[str] = set()

    print(f"Watching {segments_path} for completed .mp4 segments...")
    try:
        while True:
            candidates = sorted(segments_path.glob("*.mp4"))
            for segment_path in candidates:
                segment_name = segment_path.name
                try:
                    manifest_entry = manifest["segments"].get(segment_name, {})
                    if manifest_entry.get("status") == "processed":
                        continue
                    if segment_name in failed_this_run:
                        continue

                    size_bytes = segment_path.stat().st_size
                    if size_bytes <= 0:
                        continue
                    previous_size = stable_sizes.get(segment_name)
                    stable_sizes[segment_name] = size_bytes
                    if previous_size is None or previous_size != size_bytes:
                        continue

                    print(f"Processing segment {segment_name}")
                    try:
                        outputs = process_segment_file(
                            config=config,
                            scout=scout,
                            segment_path=segment_path,
                            output_dir=output_dir,
                        )
                        manifest["segments"][segment_name] = {
                            "status": "processed",
                            "processed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                            "size_bytes": size_bytes,
                            "attempts": int(manifest_entry.get("attempts", 0)) + 1,
                        }
                        save_manifest(manifest_path, manifest)
                        print(outputs["summary_text"])
                    except Exception as exc:  # noqa: BLE001
                        manifest["segments"][segment_name] = _failure_manifest_entry(
                            previous_entry=manifest_entry,
                            size_bytes=size_bytes,
                            stage="process_segment_file",
                            exc=exc,
                        )
                        save_manifest(manifest_path, manifest)
                        failed_this_run.add(segment_name)
                        print(f"Segment failed: {segment_name}: {exc}")
                except Exception as exc:  # noqa: BLE001
                    previous_entry = manifest["segments"].get(segment_name, {})
                    manifest["segments"][segment_name] = _failure_manifest_entry(
                        previous_entry=previous_entry,
                        size_bytes=None,
                        stage="watch_loop",
                        exc=exc,
                    )
                    save_manifest(manifest_path, manifest)
                    failed_this_run.add(segment_name)
                    print(f"Segment failed before processing: {segment_name}: {exc}")

            time.sleep(config.poll_interval_seconds)
    except KeyboardInterrupt:
        print("Watch loop stopped.")
