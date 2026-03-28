from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator


class RosterPlayer(BaseModel):
    name: str = Field(min_length=1)
    jersey: str | None = None
    aliases: list[str] = Field(default_factory=list)
    headshot_path: Path | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("name cannot be blank")
        return cleaned

    @field_validator("jersey")
    @classmethod
    def validate_jersey(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            return None
        return cleaned

    @field_validator("aliases", mode="before")
    @classmethod
    def default_aliases(cls, value: object) -> list[str]:
        if value in (None, ""):
            return []
        return list(value)

    @field_validator("aliases")
    @classmethod
    def clean_aliases(cls, value: list[str]) -> list[str]:
        seen: set[str] = set()
        aliases: list[str] = []
        for alias in value:
            cleaned = alias.strip()
            lowered = cleaned.lower()
            if cleaned and lowered not in seen:
                aliases.append(cleaned)
                seen.add(lowered)
        return aliases


class GameConfig(BaseModel):
    game_id: str = Field(min_length=1)
    camera_id: str = Field(min_length=1)
    team_a_name: str = Field(min_length=1)
    team_b_name: str = Field(min_length=1)
    team_a_roster: list[RosterPlayer] = Field(default_factory=list)
    team_b_roster: list[RosterPlayer] = Field(default_factory=list)
    segment_seconds: int = Field(default=12, ge=1)
    step_seconds: int | None = Field(default=None, ge=1)
    dedupe_time_buffer: float = Field(default=2.0, gt=0.0)
    poll_interval_seconds: float = Field(default=2.0, gt=0.0)
    max_retries: int = Field(default=3, ge=1)
    model_name: str | None = None

    @field_validator("game_id", "camera_id", "team_a_name", "team_b_name")
    @classmethod
    def strip_required_strings(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("value cannot be blank")
        return cleaned

    @field_validator("model_name")
    @classmethod
    def clean_optional_string(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @model_validator(mode="after")
    def validate_rosters(self) -> GameConfig:
        self._validate_unique_jerseys(self.team_a_roster, self.team_a_name)
        self._validate_unique_jerseys(self.team_b_roster, self.team_b_name)
        return self

    @staticmethod
    def _validate_unique_jerseys(roster: list[RosterPlayer], team_name: str) -> None:
        seen: dict[str, str] = {}
        for player in roster:
            if not player.jersey:
                continue
            jersey_key = player.jersey.lower()
            existing = seen.get(jersey_key)
            if existing and existing != player.name:
                raise ValueError(f"Duplicate jersey {player.jersey} in roster for {team_name}")
            seen[jersey_key] = player.name

    @property
    def batch_step_seconds(self) -> int:
        return self.step_seconds or self.segment_seconds

    @property
    def team_a_headshot_paths(self) -> list[Path]:
        return [player.headshot_path for player in self.team_a_roster if player.headshot_path is not None]


class ConfigError(RuntimeError):
    pass


def load_game_config(path: str | Path) -> GameConfig:
    config_path = Path(path).expanduser().resolve()
    if not config_path.exists():
        raise ConfigError(f"Config file not found: {config_path}")

    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Invalid JSON in config file: {config_path}") from exc

    config_dir = config_path.parent

    for team_key in ("team_a_roster", "team_b_roster"):
        roster_payload = payload.get(team_key, []) or []
        for player in roster_payload:
            headshot_value = player.get("headshot_path")
            if headshot_value:
                resolved = Path(headshot_value)
                if not resolved.is_absolute():
                    resolved = (config_dir / resolved).resolve()
                player["headshot_path"] = resolved

    try:
        config = GameConfig.model_validate(payload)
    except ValidationError as exc:
        raise ConfigError(f"Invalid config: {exc}") from exc
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc

    for player in config.team_a_roster:
        if player.headshot_path is not None and not player.headshot_path.exists():
            raise ConfigError(f"Headshot file not found for {player.name}: {player.headshot_path}")

    return config
