"""Defines the ADK agent hierarchy for the ontology MVP."""

from __future__ import annotations

from pathlib import Path

from google.adk.agents import LlmAgent, SequentialAgent

from .config import config

_PROMPT_DIR = Path(__file__).resolve().parent.parent / "prompts"


def _read_prompt(filename: str) -> str:
    path = _PROMPT_DIR / filename
    return path.read_text(encoding="utf-8")


_ontology_selector_prompt = _read_prompt("ontology_selector.md")
_uome_prompt = _read_prompt("uome_prompt.md").replace("{max_triples}", str(config.max_triples))
_kgqa_prompt = _read_prompt("kgqa_prompt.md")

ontology_profiler = LlmAgent(
    name="ontology_profiler",
    model=config.selector_model,
    description="Classifies the user text and copies it into a reusable structure.",
    instruction=_ontology_selector_prompt
    + "\n\n## Output Only JSON\n대화 이력 대신 JSON만 반환하며, source_text에는 항상 최신 사용자 입력을 포함합니다.",
    output_key="ontology_profile",
)

extraction_instruction = (
    _uome_prompt
    + "\n\n## Context\n"
    "You will receive the ontology profiler output under {ontology_profile}.\n"
    "- Use `source_text` as the extraction payload.\n"
    "- Respect the selected ontology and entities.\n"
    "- Return JSON only."
)

fibo_extractor = LlmAgent(
    name="fibo_uome_agent",
    model=config.extractor_model,
    description="Turns finance snippets into FIBO triples.",
    instruction=extraction_instruction,
    output_key="extracted_triples",
)

kgqa_instruction = (
    _kgqa_prompt
    + "\n\n## Inputs\n"
    "- Ontology profile: {ontology_profile}\n"
    "- Triples to review: {extracted_triples}\n"
    "Return JSON only."
)

kgqa_agent = LlmAgent(
    name="kgqa_agent",
    model=config.validator_model,
    description="Audits extracted triples before downstream ingestion.",
    instruction=kgqa_instruction,
    output_key="kgqa_evaluation",
)


class FiboOntologyPipeline(SequentialAgent):
    """Project-scoped sequential agent to avoid ADK app_name heuristics."""


root_agent = FiboOntologyPipeline(
    name="fibo_ontology_pipeline",
    description=(
        "Minimal FIBO knowledge graph pipeline. "
        "Step 1: profile the text, Step 2: extract triples, Step 3: run KGQA."
    ),
    sub_agents=[ontology_profiler, fibo_extractor, kgqa_agent],
)
