from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


EventType = Literal[
    "2pt_make",
    "2pt_miss",
    "3pt_make",
    "3pt_miss",
    "ft_make",
    "ft_miss",
    "rebound_off",
    "rebound_def",
    "steal",
    "block",
    "turnover",
    "foul",
]

IdentityMethod = Literal["jersey", "face_hint", "unknown"]


class Event(BaseModel):
    time: str = Field(description="Event timestamp relative to the clip start, MM:SS")
    type: EventType
    team: str = Field(description="Exact team name from the provided roster context")
    player: str = Field(
        description='Legacy display label. Use the exact player name when known, otherwise "<TeamName> #<Jersey>" or "Unknown".'
    )
    player_name: str | None = Field(default=None, description="Exact roster name when confidently identified")
    jersey: str | None = Field(default=None, description="Visible jersey number when readable")
    against_player: str | None = Field(default=None, description="Readable opponent label when known")
    assist_by: str | None = Field(default=None, description="Readable passer label when clearly identifiable")
    points: int | None = Field(default=None, description="Points scored by this event when relevant: 1, 2, or 3")
    identity_method: IdentityMethod | None = Field(
        default=None,
        description="How the primary player was identified: jersey, face_hint, or unknown",
    )
    confidence: float = Field(default=0.5, ge=0.0, le=1.0, description="Model confidence from 0 to 1")
    notes: str | None = Field(default=None, description="Short note only when useful")

    @field_validator("time")
    @classmethod
    def validate_time(cls, value: str) -> str:
        parts = value.split(":")
        if len(parts) != 2:
            raise ValueError("time must be MM:SS")
        mm, ss = parts
        if not (mm.isdigit() and ss.isdigit()):
            raise ValueError("time must be MM:SS")
        seconds = int(ss)
        if seconds < 0 or seconds > 59:
            raise ValueError("seconds must be between 00 and 59")
        return f"{int(mm):02d}:{seconds:02d}"

    @field_validator("team", "player", "player_name", "jersey", "against_player", "assist_by", "notes")
    @classmethod
    def clean_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @model_validator(mode="after")
    def normalize_identity(self) -> Event:
        player_value = self.player or "Unknown"
        if player_value.lower() == "unknown":
            self.player = "Unknown"
            self.player_name = None
            self.identity_method = self.identity_method or "unknown"
            if not self.jersey:
                self.jersey = None
            return self

        self.player = player_value
        if self.player_name is None and not player_value.startswith(f"{self.team} #"):
            self.player_name = player_value
        if self.identity_method is None:
            self.identity_method = "jersey" if self.jersey else "unknown"
        return self


class WindowResult(BaseModel):
    window_start: int = 0
    window_end: int = 0
    on_court_team_a: list[str] = Field(default_factory=list)
    on_court_team_b: list[str] = Field(default_factory=list)
    events: list[Event] = Field(default_factory=list)

    @field_validator("on_court_team_a", "on_court_team_b")
    @classmethod
    def clean_on_court_players(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for player in value:
            label = player.strip()
            if not label:
                continue
            lowered = label.lower()
            if lowered not in seen:
                cleaned.append(label)
                seen.add(lowered)
        return cleaned


class RawWindowRecord(BaseModel):
    window_start: int
    window_end: int
    on_court_team_a: list[str]
    on_court_team_b: list[str]
    events: list[dict]
    clip_path: str
    camera_id: str | None = None
    segment_file: str | None = None
    segment_start_iso: str | None = None
    segment_end_iso: str | None = None
    credit_seconds: int | None = None
