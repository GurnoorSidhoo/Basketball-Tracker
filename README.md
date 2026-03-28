<<<<<<< HEAD
# Basketball Stat Tracking CLI (MVP)

Local Python CLI for same-day basketball stat tracking from uploaded clips and watched local segments.

Commands:
- `python main.py batch ...`: analyze one full game video offline
- `python main.py watch ...`: process completed local `.mp4` segments from one camera/laptop
- `python main.py upload ...`: process one local `.mp4` clip directly (no watch loop)
- `python main.py merge ...`: merge deduped exports from multiple laptops after the game
- `python main.py smoke ...`: setup + pipeline smoke test on one short clip

The app stays local: `ffmpeg`/`ffprobe` + Gemini + JSON/CSV outputs.

## Requirements

- macOS or Linux
- Python 3.11+
- `ffmpeg` and `ffprobe` on `PATH`
- Gemini API key (`GEMINI_API_KEY`)

Install:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## 1) Create Game Config

Start from [`config/game_config.example.json`](/Users/gurnoorsidhu/Desktop/Coding/phase1_api_scout/config/game_config.example.json):

```bash
cp config/game_config.example.json config/game_config.json
```

Set:
- `game_id` (shared for all laptops)
- `camera_id` (unique per laptop)
- team rosters with jersey numbers
- optional Team A headshots only (`headshot_path`) for fallback hints

Identity behavior remains conservative:
- jersey is primary
- Team A headshots are fallback only
- opponents never use face hints
- unknown stays unknown

## 2) Set Environment

Set `.env`:

```env
GEMINI_API_KEY=your_google_ai_studio_api_key_here
MODEL_NAME=gemini-3.1-flash-lite-preview
```

Default model is intentionally `gemini-3.1-flash-lite-preview`.
Keep this default unless you manually override with `MODEL_NAME` or `model_name` in config.

## 3) Run Smoke Test First

Use one short clip (around 10-20 seconds):

```bash
python main.py smoke \
  --config config/game_config.json \
  --input-video path/to/short_clip.mp4
```

Smoke validates:
- config loading
- `.env` loading
- `ffmpeg`/`ffprobe` availability
- `GEMINI_API_KEY` presence
- one real clip processing through Gemini and output generation

Default smoke outputs:
- `runs/smoke/<camera_id>/raw_segments.jsonl`
- `runs/smoke/<camera_id>/deduped_events.json`
- `runs/smoke/<camera_id>/box_score.csv`
- `runs/smoke/<camera_id>/summary.txt`

## 4) Run Direct Upload on One Clip

Use `upload` to process a local clip directly:

```bash
python main.py upload \
  --config config/game_config.json \
  --input-video path/to/clip.mp4
```

Optional fields:

```bash
python main.py upload \
  --config config/game_config.json \
  --input-video path/to/clip.mp4 \
  --camera-id cam_a_sideline \
  --segment-start-iso 2026-03-16T19:30:15+11:00 \
  --output-dir runs/outputs/cam_a_sideline
```

Behavior:
- appends to `raw_segments.jsonl` if it already exists
- recomputes `deduped_events.json`, `box_score.csv`, `summary.txt`
- if `segment_start_iso` is provided, also emits `absolute_game_time_iso`
- if omitted, still produces valid relative + global timing

## 5) During Game: Watch or Batch

### Watch mode (camera/laptop segments)

Segments must be named:

```text
<camera_id>__YYYYMMDDTHHMMSS.mp4
```

Example:

```text
cam_a_sideline__20260316T193015.mp4
```

Run watcher:

```bash
python main.py watch \
  --config config/game_config.json \
  --segments-dir runs/incoming_segments/cam_a_sideline
```

Watcher behavior:
- waits for file size stability before processing
- keeps running if one segment fails
- records per-segment status/errors in `manifest.json`
- recomputes deduped outputs after each successful segment

### Batch mode (full game file)

```bash
python main.py batch \
  --config config/game_config.json \
  --input-video path/to/full_game.mp4
```

Default batch outputs:
- `runs/outputs/raw_windows.json`
- `runs/outputs/deduped_events.json`
- `runs/outputs/box_score.csv`
- `runs/outputs/summary.txt`
- extracted clips in `runs/clips/<input-video-stem>/`

## 6) After Game: Merge Camera Exports

```bash
python main.py merge \
  --inputs runs/outputs/cam_a_sideline runs/outputs/cam_b_baseline runs/outputs/cam_c_diagonal \
  --output-dir runs/merged
```

Merge outputs:
- `runs/merged/merged_events.json`
- `runs/merged/merged_box_score.csv`

## Output Compatibility

This repo preserves output compatibility and keeps producing:
- `raw_windows.json` (batch)
- `raw_segments.jsonl` (watch/upload)
- `deduped_events.json`
- `box_score.csv`
- `summary.txt`
- merge outputs
=======
# Basketball-Tracker
>>>>>>> 8897d4baac54111a2dde93abc749fee7077e0bad
