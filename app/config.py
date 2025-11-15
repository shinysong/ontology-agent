"""Configuration helpers for the ontology ADK MVP."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _load_local_env() -> None:
    """Loads .env files from project root/app before enforcing config."""
    try:
        from dotenv import load_dotenv
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "python-dotenv 패키지를 찾을 수 없습니다. `uv pip install python-dotenv` 후 다시 실행하세요."
        ) from exc
    project_root = Path(__file__).resolve().parents[1]
    env_candidates = (project_root / ".env", project_root / "app" / ".env")
    for env_path in env_candidates:
        if env_path.exists():
            load_dotenv(env_path, override=False)
            break


def _ensure_gemini_api_only() -> None:
    """Forces the ADK stack to use Gemini API credentials only."""
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "False"
    os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")
    if not os.environ.get("GOOGLE_API_KEY"):
        raise RuntimeError(
            "GOOGLE_API_KEY가 설정되어 있지 않습니다. .env 또는 환경 변수에 "
            "Google AI Studio 키를 추가한 뒤 다시 실행하세요."
        )


_load_local_env()
_ensure_gemini_api_only()


@dataclass
class OntologyAgentConfig:
    """Model configuration for the MVP."""

    selector_model: str = os.environ.get("ONTOLOGY_SELECTOR_MODEL", "gemini-2.5-flash-lite")
    extractor_model: str = os.environ.get("ONTOLOGY_EXTRACTOR_MODEL", "gemini-2.5-flash-lite")
    validator_model: str = os.environ.get("ONTOLOGY_VALIDATOR_MODEL", "gemini-2.5-flash-lite")
    max_triples: int = int(os.environ.get("ONTOLOGY_MAX_TRIPLES", "6"))


config = OntologyAgentConfig()
