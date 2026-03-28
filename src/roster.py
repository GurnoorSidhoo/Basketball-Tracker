from __future__ import annotations

from pathlib import Path

from .config import GameConfig, RosterPlayer


def _roster_line(player: RosterPlayer, allow_face_hints: bool) -> str:
    parts = [player.name]
    if player.jersey:
        parts.append(f"jersey {player.jersey}")
    if player.aliases:
        parts.append(f"aliases: {', '.join(player.aliases)}")
    if allow_face_hints and player.headshot_path is not None:
        parts.append(f"headshot file: {Path(player.headshot_path).name}")
    return " | ".join(parts)


def roster_to_prompt_section(team_name: str, roster: list[RosterPlayer], allow_face_hints: bool) -> str:
    if not roster:
        return f"{team_name}: no roster provided"

    header = f"{team_name}:"
    lines = [header]
    for player in roster:
        lines.append(f"- {_roster_line(player, allow_face_hints=allow_face_hints)}")
    return "\n".join(lines)


def build_prompt_roster_context(config: GameConfig) -> str:
    team_a = roster_to_prompt_section(
        team_name=config.team_a_name,
        roster=config.team_a_roster,
        allow_face_hints=True,
    )
    team_b = roster_to_prompt_section(
        team_name=config.team_b_name,
        roster=config.team_b_roster,
        allow_face_hints=False,
    )
    return f"{team_a}\n\n{team_b}"


def collect_team_a_headshots(config: GameConfig) -> list[Path]:
    return [Path(path) for path in config.team_a_headshot_paths]
