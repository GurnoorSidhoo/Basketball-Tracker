from __future__ import annotations

import math
import subprocess
from pathlib import Path


def run_cmd(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, text=True, capture_output=True)


def get_video_duration_seconds(video_path: str) -> float:
    result = run_cmd(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            video_path,
        ]
    )
    return float(result.stdout.strip())


def build_windows(total_duration: float, window_seconds: int, step_seconds: int) -> list[tuple[int, int]]:
    windows: list[tuple[int, int]] = []
    total_duration_ceiled = math.ceil(total_duration)
    start = 0
    while start < total_duration_ceiled:
        end = min(start + window_seconds, total_duration_ceiled)
        windows.append((start, end))
        if end >= total_duration_ceiled:
            break
        start += step_seconds
    return windows


def extract_clip(
    input_video: str,
    output_clip: str,
    start_sec: int,
    end_sec: int,
    scale_width: int = 1280,
) -> None:
    duration = max(1, end_sec - start_sec)
    Path(output_clip).parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        str(start_sec),
        "-i",
        input_video,
        "-t",
        str(duration),
        "-vf",
        f"scale='min({scale_width},iw)':-2",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "28",
        "-c:a",
        "aac",
        "-b:a",
        "96k",
        output_clip,
    ]
    run_cmd(cmd)
