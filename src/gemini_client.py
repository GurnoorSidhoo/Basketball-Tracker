from __future__ import annotations

import json
import time
from pathlib import Path

from google import genai
from pydantic import ValidationError

from .prompts import SYSTEM_INSTRUCTION
from .schemas import WindowResult


class GeminiModelRuntimeError(RuntimeError):
    """Raised when the configured model itself is not usable at runtime."""


class GeminiScout:
    def __init__(
        self,
        api_key: str,
        model_name: str,
        max_retries: int = 3,
        upload_poll_interval_seconds: float = 1.0,
        upload_ready_timeout_seconds: float = 120.0,
    ):
        self.client = genai.Client(api_key=api_key)
        self.model_name = model_name
        self.max_retries = max_retries
        self.upload_poll_interval_seconds = upload_poll_interval_seconds
        self.upload_ready_timeout_seconds = upload_ready_timeout_seconds

    @staticmethod
    def _file_state_name(value: object) -> str:
        state_value = getattr(value, "value", value)
        if state_value is None:
            return "UNKNOWN"
        return str(state_value).upper()

    @staticmethod
    def _looks_like_model_error(exc: Exception) -> bool:
        message = str(exc).lower()
        if "model" not in message:
            return False
        return any(
            token in message
            for token in (
                "not found",
                "does not exist",
                "unsupported",
                "invalid",
                "permission",
                "access denied",
                "404",
            )
        )

    def _upload_file(self, path: str | Path, label: str) -> object:
        try:
            return self.client.files.upload(file=str(path))
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Gemini upload failed for {label} ({path}): {exc}") from exc

    def _wait_until_file_ready(self, upload: object) -> None:
        upload_name = getattr(upload, "name", None)
        if not upload_name:
            raise RuntimeError("Gemini upload completed but no upload name was returned for polling")

        deadline = time.monotonic() + self.upload_ready_timeout_seconds
        while True:
            try:
                latest = self.client.files.get(name=upload_name)
            except Exception as exc:  # noqa: BLE001
                raise RuntimeError(f"Gemini upload polling failed for {upload_name}: {exc}") from exc

            state_name = self._file_state_name(getattr(latest, "state", None))
            if state_name == "ACTIVE":
                return
            if state_name == "FAILED":
                failure = getattr(latest, "error", None)
                failure_message = getattr(failure, "message", None) or str(failure or "unknown processing error")
                raise RuntimeError(f"Gemini file processing failed for {upload_name}: {failure_message}")
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"Timed out waiting for Gemini upload {upload_name} to become ACTIVE (last state: {state_name})"
                )
            time.sleep(self.upload_poll_interval_seconds)

    def _parse_window_result(self, response: object, clip_name: str) -> WindowResult:
        response_text = getattr(response, "text", None)
        if not response_text or not str(response_text).strip():
            raise RuntimeError(
                f"Gemini returned an empty response for {clip_name}. "
                "Try a shorter clip or retry the command."
            )
        try:
            payload = json.loads(response_text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"Gemini returned invalid JSON for {clip_name}: {exc.msg} at line {exc.lineno}, column {exc.colno}"
            ) from exc

        try:
            return WindowResult.model_validate(payload)
        except ValidationError as exc:
            first_error = exc.errors()[0] if exc.errors() else {}
            location = ".".join(str(part) for part in first_error.get("loc", ())) or "unknown"
            message = first_error.get("msg", str(exc))
            raise RuntimeError(f"Gemini JSON schema validation failed for {clip_name} at '{location}': {message}") from exc

    def _cleanup_uploads(self, uploads: list[object]) -> None:
        for upload in uploads:
            try:
                upload_name = getattr(upload, "name", None)
                if upload_name:
                    self.client.files.delete(name=upload_name)
            except Exception:  # noqa: BLE001
                pass

    def analyze_clip(
        self,
        *,
        clip_path: str,
        prompt: str,
        window_start: int,
        window_end: int,
        reference_image_paths: list[str | Path] | None = None,
    ) -> WindowResult:
        last_error: Exception | None = None
        reference_image_paths = [Path(path) for path in reference_image_paths or []]
        clip_name = Path(clip_path).name

        for attempt in range(1, self.max_retries + 1):
            uploads: list[object] = []
            try:
                uploads.append(self._upload_file(clip_path, label="video clip"))
                for image_path in reference_image_paths:
                    uploads.append(self._upload_file(image_path, label=f"reference image {image_path.name}"))
                for upload in uploads:
                    self._wait_until_file_ready(upload)

                try:
                    response = self.client.models.generate_content(
                        model=self.model_name,
                        contents=[*uploads, prompt],
                        config={
                            "system_instruction": SYSTEM_INSTRUCTION,
                            "response_mime_type": "application/json",
                            "response_json_schema": WindowResult.model_json_schema(),
                            "temperature": 0.1,
                        },
                    )
                except Exception as exc:  # noqa: BLE001
                    if self._looks_like_model_error(exc):
                        raise GeminiModelRuntimeError(
                            f"Configured Gemini model '{self.model_name}' failed at runtime. "
                            "Update MODEL_NAME or config.model_name to a valid Gemini 3.1 model for your account, "
                            f"then retry. Original error: {exc}"
                        ) from exc
                    raise RuntimeError(f"Gemini generate_content failed for {clip_name}: {exc}") from exc

                parsed = self._parse_window_result(response, clip_name=clip_name)
                parsed.window_start = window_start
                parsed.window_end = window_end
                return parsed
            except GeminiModelRuntimeError as exc:
                raise RuntimeError(str(exc)) from exc
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt == self.max_retries:
                    raise RuntimeError(
                        f"Gemini failed for clip {clip_name} after {self.max_retries} attempts. Last error: {exc}"
                    ) from exc
                backoff_seconds = min(8.0, 1.5 * (2 ** (attempt - 1)))
                time.sleep(backoff_seconds)
            finally:
                self._cleanup_uploads(uploads)

        raise RuntimeError(f"Unexpected Gemini failure: {last_error}")
