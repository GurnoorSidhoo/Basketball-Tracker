from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from .config import GameConfig
from .live_watch import run_upload
from .pipeline import DEFAULT_MODEL_NAME


def _require_binary(name: str) -> None:
    if shutil.which(name) is None:
        raise RuntimeError(
            f"Required tool '{name}' was not found on PATH. Install ffmpeg so both ffmpeg and ffprobe are available."
        )


def run_smoke_test(
    *,
    config: GameConfig,
    input_video: str | Path,
    output_dir: Path,
    camera_id: str | None = None,
    segment_start_iso: str | None = None,
) -> dict[str, Any]:
    _require_binary("ffmpeg")
    _require_binary("ffprobe")

    load_dotenv()
    api_key = (os.getenv("GEMINI_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("Missing GEMINI_API_KEY. Set it in your shell or .env before running smoke.")

    model_name = (os.getenv("MODEL_NAME") or config.model_name or DEFAULT_MODEL_NAME).strip()
    outputs = run_upload(
        config=config,
        input_video=input_video,
        output_dir=output_dir,
        camera_id=camera_id,
        segment_start_iso=segment_start_iso,
    )
    return {
        "model_name": model_name,
        **outputs,
    }
