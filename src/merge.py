from __future__ import annotations

import json
from pathlib import Path

from .box_score import build_box_score
from .dedupe import deduplicate_event_list


def _resolve_event_input(path: str | Path) -> Path:
    input_path = Path(path).expanduser().resolve()
    if input_path.is_dir():
        for candidate_name in ("deduped_events.json", "merged_events.json"):
            candidate = input_path / candidate_name
            if candidate.exists():
                return candidate
        raise FileNotFoundError(f"No deduped event export found in directory: {input_path}")
    if not input_path.exists():
        raise FileNotFoundError(f"Input not found: {input_path}")
    return input_path


def merge_event_exports(*, inputs: list[str | Path], output_dir: str | Path, time_buffer: float = 2.0) -> dict[str, Path | list[dict]]:
    output_path = Path(output_dir).expanduser().resolve()
    output_path.mkdir(parents=True, exist_ok=True)

    all_events: list[dict] = []
    for input_item in inputs:
        event_path = _resolve_event_input(input_item)
        events = json.loads(event_path.read_text(encoding="utf-8"))
        for event in events:
            item = dict(event)
            item.setdefault("source_export", str(event_path))
            all_events.append(item)

    merged_events = deduplicate_event_list(all_events, time_buffer=time_buffer)
    merged_path = output_path / "merged_events.json"
    merged_path.write_text(json.dumps(merged_events, indent=2), encoding="utf-8")

    merged_box_score = build_box_score(
        raw_windows=[],
        deduped_events=merged_events,
        team_a_label="",
        team_b_label="",
    )
    merged_box_score_path = output_path / "merged_box_score.csv"
    merged_box_score.to_csv(merged_box_score_path, index=False)

    return {
        "merged_events": merged_events,
        "merged_path": merged_path,
        "merged_box_score_path": merged_box_score_path,
    }
