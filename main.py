from __future__ import annotations

import argparse
from pathlib import Path

from src.config import load_game_config
from src.live_watch import run_upload, watch_segments
from src.merge import merge_event_exports
from src.pipeline import run_batch
from src.smoke_test import run_smoke_test


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Basketball MVP rescue CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    batch_parser = subparsers.add_parser("batch", help="Analyze a full video offline")
    batch_parser.add_argument("--config", required=True, help="Path to game config JSON")
    batch_parser.add_argument("--input-video", required=True, help="Path to the full game video")
    batch_parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory for outputs. Default: runs/outputs",
    )
    batch_parser.add_argument(
        "--clips-dir",
        default=None,
        help="Directory for extracted clips. Default: runs/clips/<input-video-stem>",
    )

    watch_parser = subparsers.add_parser("watch", help="Watch a directory for completed local segments")
    watch_parser.add_argument("--config", required=True, help="Path to game config JSON")
    watch_parser.add_argument("--segments-dir", required=True, help="Directory containing .mp4 segments")
    watch_parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory for outputs. Default: runs/outputs/<camera_id>",
    )

    upload_parser = subparsers.add_parser("upload", help="Process one local .mp4 clip directly")
    upload_parser.add_argument("--config", required=True, help="Path to game config JSON")
    upload_parser.add_argument("--input-video", required=True, help="Path to one local .mp4 clip")
    upload_parser.add_argument("--camera-id", default=None, help="Override camera_id for this clip")
    upload_parser.add_argument(
        "--segment-start-iso",
        default=None,
        help="Optional segment start timestamp (ISO-8601) for absolute_game_time_iso",
    )
    upload_parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory for outputs. Default: runs/outputs/<camera_id>",
    )

    smoke_parser = subparsers.add_parser("smoke", help="Validate setup and process one short clip")
    smoke_parser.add_argument("--config", required=True, help="Path to game config JSON")
    smoke_parser.add_argument("--input-video", required=True, help="Path to a short local .mp4 clip")
    smoke_parser.add_argument("--camera-id", default=None, help="Optional camera_id override")
    smoke_parser.add_argument(
        "--segment-start-iso",
        default=None,
        help="Optional segment start timestamp (ISO-8601)",
    )
    smoke_parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory for smoke outputs. Default: runs/smoke/<camera_id>",
    )

    merge_parser = subparsers.add_parser("merge", help="Merge deduped camera exports")
    merge_parser.add_argument("--inputs", nargs="+", required=True, help="Event JSON files or output directories")
    merge_parser.add_argument("--output-dir", required=True, help="Directory for merged outputs")
    merge_parser.add_argument(
        "--time-buffer",
        type=float,
        default=2.0,
        help="Timestamp tolerance in seconds when merging duplicates",
    )

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    root = Path(__file__).resolve().parent

    if args.command == "batch":
        config = load_game_config(args.config)
        output_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else root / "runs" / "outputs"
        default_clips_dir = root / "runs" / "clips" / Path(args.input_video).stem
        clips_dir = Path(args.clips_dir).expanduser().resolve() if args.clips_dir else default_clips_dir
        outputs = run_batch(
            config=config,
            input_video=args.input_video,
            output_dir=output_dir,
            clips_dir=clips_dir,
        )
        print("\nBatch complete.")
        print(f"Raw windows:    {outputs['raw_path']}")
        print(f"Deduped events: {outputs['deduped_path']}")
        print(f"Box score:      {outputs['box_score_path']}")
        print(f"Summary:        {outputs['summary_path']}")
        return

    if args.command == "watch":
        config = load_game_config(args.config)
        output_dir = (
            Path(args.output_dir).expanduser().resolve()
            if args.output_dir
            else root / "runs" / "outputs" / config.camera_id
        )
        watch_segments(config=config, segments_dir=args.segments_dir, output_dir=output_dir)
        return

    if args.command == "upload":
        config = load_game_config(args.config)
        resolved_camera_id = args.camera_id or config.camera_id
        output_dir = (
            Path(args.output_dir).expanduser().resolve()
            if args.output_dir
            else root / "runs" / "outputs" / resolved_camera_id
        )
        outputs = run_upload(
            config=config,
            input_video=args.input_video,
            output_dir=output_dir,
            camera_id=args.camera_id,
            segment_start_iso=args.segment_start_iso,
        )
        print("Upload processing complete.")
        print(f"Raw segments:   {outputs['raw_jsonl_path']}")
        print(f"Deduped events: {outputs['deduped_path']}")
        print(f"Box score:      {outputs['box_score_path']}")
        print(f"Summary:        {outputs['summary_path']}")
        return

    if args.command == "smoke":
        config = load_game_config(args.config)
        resolved_camera_id = args.camera_id or config.camera_id
        output_dir = (
            Path(args.output_dir).expanduser().resolve()
            if args.output_dir
            else root / "runs" / "smoke" / resolved_camera_id
        )
        outputs = run_smoke_test(
            config=config,
            input_video=args.input_video,
            output_dir=output_dir,
            camera_id=args.camera_id,
            segment_start_iso=args.segment_start_iso,
        )
        print("Smoke test complete.")
        print(f"Model:          {outputs['model_name']}")
        print(f"Raw segments:   {outputs['raw_jsonl_path']}")
        print(f"Deduped events: {outputs['deduped_path']}")
        print(f"Box score:      {outputs['box_score_path']}")
        print(f"Summary:        {outputs['summary_path']}")
        return

    if args.command == "merge":
        outputs = merge_event_exports(
            inputs=args.inputs,
            output_dir=args.output_dir,
            time_buffer=args.time_buffer,
        )
        print("Merge complete.")
        print(f"Merged events:   {outputs['merged_path']}")
        print(f"Merged boxscore: {outputs['merged_box_score_path']}")
        return

    parser.error(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()
