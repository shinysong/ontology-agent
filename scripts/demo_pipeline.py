"""Runs the ontology pipeline locally via the InMemoryRunner."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import json
from datetime import datetime
from pathlib import Path
import textwrap

from dotenv import load_dotenv
from google.adk.runners import InMemoryRunner
from google.genai.errors import ServerError
from google.genai.types import Part, UserContent

from app import root_agent
from app.config import config

DEFAULT_TEXT = textwrap.dedent(
    """
    Cboe Global Markets reported that its derivatives unit generated $1.1B in trading
    fees during Q3 2024. The corporate treasury noted that Treasury futures continue
    to be the core financial instrument supporting that revenue stream.
    """
).strip()


logger = logging.getLogger("demo_pipeline")


def _configure_logging(debug: bool) -> None:
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        force=True,
    )


def _log_env_snapshot() -> None:
    def _mask(value: str | None) -> str | None:
        if not value:
            return value
        if len(value) <= 8:
            return "****"
        return f"{value[:4]}...{value[-4:]}"

    env_vars = {
        "GOOGLE_GENAI_USE_VERTEXAI": os.getenv("GOOGLE_GENAI_USE_VERTEXAI"),
        "GOOGLE_CLOUD_LOCATION": os.getenv("GOOGLE_CLOUD_LOCATION"),
        "GOOGLE_CLOUD_PROJECT": os.getenv("GOOGLE_CLOUD_PROJECT"),
        "GOOGLE_API_KEY": _mask(os.getenv("GOOGLE_API_KEY")),
    }
    logger.info("Env snapshot: %s", env_vars)
    logger.info(
        "Model plan selector=%s extractor=%s validator=%s max_triples=%s",
        config.selector_model,
        config.extractor_model,
        config.validator_model,
        config.max_triples,
    )


def _log_runner_event(event) -> None:
    agent_name = getattr(event, "agent", None)
    invocation_id = getattr(event, "invocation_id", None)
    parts = []
    if getattr(event, "content", None) and event.content.parts:
        for part in event.content.parts:
            snippet = (part.text or "").strip()
            if len(snippet) > 120:
                snippet = snippet[:117] + "..."
            parts.append(snippet)
    logger.debug(
        "Event agent=%s invocation=%s type=%s parts=%s",
        getattr(agent_name, "name", agent_name),
        invocation_id,
        type(event).__name__,
        parts,
    )


async def run_pipeline(user_text: str) -> tuple[str, dict]:
    runner = InMemoryRunner(agent=root_agent, app_name="app")
    logger.info("Starting runner %s with agent %s", runner.app_name, root_agent.name)
    session = await runner.session_service.create_session(
        app_name=runner.app_name, user_id="demo_user"
    )
    logger.info("Created session id=%s user=%s", session.id, session.user_id)
    content = UserContent(parts=[Part(text=user_text)])
    last_response = ""
    session_state: dict = {}
    try:
        async for event in runner.run_async(
            user_id=session.user_id,
            session_id=session.id,
            new_message=content,
        ):
            _log_runner_event(event)
            if not event.content or not event.content.parts:
                continue
            chunk = "".join(part.text or "" for part in event.content.parts)
            if chunk:
                logger.debug("Chunk update (len=%s)", len(chunk))
                last_response = chunk
    finally:
        fetched_session = await runner.session_service.get_session(
            app_name=runner.app_name, user_id=session.user_id, session_id=session.id
        )
        if fetched_session:
            session_state = dict(fetched_session.state or {})
        await runner.close()
        logger.info("Runner session closed")
    return last_response, session_state


def _load_input_text(text_arg: str | None, text_file: Path | None) -> str:
    if text_arg:
        return text_arg
    if text_file:
        return text_file.read_text(encoding="utf-8")
    return DEFAULT_TEXT


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the ontology ADK MVP in memory.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--text",
        type=str,
        help="Inline finance snippet to convert into FIBO triples.",
    )
    group.add_argument(
        "--text-file",
        type=Path,
        help="Path to a UTF-8 text file used as the extraction payload.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable verbose logging for troubleshooting.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Directory to store run artifacts (default: runs/run-YYYYmmdd-HHMMSS).",
    )
    args = parser.parse_args()
    _configure_logging(args.debug)
    logger.info(
        "CLI args text=%s text_file=%s debug=%s",
        bool(args.text),
        args.text_file,
        args.debug,
    )
    project_root = Path(__file__).resolve().parents[1]
    for env_path in (project_root / ".env", project_root / "app" / ".env"):
        if env_path.exists():
            load_dotenv(env_path, override=False)
    payload = _load_input_text(args.text, args.text_file)
    logger.info("Loaded input text length=%s", len(payload))
    _log_env_snapshot()
    run_id = datetime.now().strftime("run-%Y%m%d-%H%M%S")
    output_dir = (args.output_dir or (project_root / "runs" / run_id)).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    input_path = output_dir / "input.txt"
    input_path.write_text(payload, encoding="utf-8")
    logger.info("Persisting artifacts under %s", output_dir)
    try:
        response, session_state = asyncio.run(run_pipeline(payload))
    except ServerError as err:
        status_code = getattr(err, "code", None) or getattr(err, "status_code", None)
        status = getattr(err, "status", None)
        logger.error(
            "Gemini API ServerError code=%s status=%s raw=%s",
            status_code,
            status,
            err,
        )
        if getattr(err, "response", None):
            logger.error("ServerError response detail: %s", err.response)
        raise
    _persist_artifacts(session_state, response, output_dir)
    (output_dir / "final_response.json").write_text(
        json.dumps(_safe_json(response), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(response)


def _safe_json(value: str) -> dict | str:
    try:
        return json.loads(value)
    except Exception:
        return value


def _persist_artifacts(session_state: dict, final_response: str, output_dir: Path) -> None:
    if not session_state:
        logger.warning("No session state found; skipping artifact persistence")
        return
    artifacts = {
        "ontology_profile": session_state.get("ontology_profile"),
        "extracted_triples": session_state.get("extracted_triples"),
        "kgqa_evaluation": session_state.get("kgqa_evaluation"),
        "session_state": session_state,
    }
    for name, payload in artifacts.items():
        if payload is None:
            continue
        target = output_dir / f"{name}.json"
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("Saved %s to %s", name, target)


if __name__ == "__main__":
    main()
