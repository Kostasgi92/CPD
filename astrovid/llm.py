"""Κλήσεις στο Claude: σχεδιασμός αναζήτησης, σύνθεση έρευνας, σενάριο, έλεγχος γεγονότων."""

from __future__ import annotations

import datetime as dt
import json
import logging

import anthropic
from pydantic import BaseModel, Field

from .config import AUTHORITATIVE_DOMAINS, Settings
from .research import Source

log = logging.getLogger(__name__)

FALLBACK_BETA = "server-side-fallback-2026-07-01"
FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5"}
LANG_NAMES = {"el": "Greek (Modern Greek, natural spoken style)", "en": "English"}

SCIENCE_RULES = """\
Scientific integrity rules (non-negotiable):
- Every factual claim must be supported by the supplied sources or the research brief. Never invent \
numbers, dates, names, missions or results. If something is not in the sources, leave it out.
- Quote measured values with units and, where the source gives them, uncertainties \
(e.g. H0 = 73.0 ± 1.0 km/s/Mpc). Prefer the most recent peer-reviewed value; mention tensions \
between measurements when they exist instead of silently picking one.
- Clearly distinguish established consensus, active debate, and speculation/hypotheses.
- Results that only exist as arXiv preprints must be described as "not yet peer-reviewed" / \
"recent preprint".
- Avoid popular myths and oversimplifications that are wrong (e.g. "black holes suck everything \
in", "the Big Bang was an explosion in space").
- Be precise with terminology; in Greek use the established Greek scientific terms \
(e.g. μαύρη τρύπα, ερυθρή μετατόπιση, σκοτεινή ύλη, αστέρας νετρονίων, βαρυτικά κύματα)."""


# ---------------------------------------------------------------- schemas

class SearchPlan(BaseModel):
    queries: list[str] = Field(description="3-5 concise English literature search queries")
    working_title: str


class Scene(BaseModel):
    heading: str = Field(description="Short on-screen heading for the scene (max ~6 words)")
    narration: str = Field(description="Exactly what the narrator says in this scene")
    image_query: str = Field(description="2-4 English keywords to find a matching NASA image")
    source_ids: list[str] = Field(description="IDs of the sources (P#/W#) backing this scene")


class VideoScript(BaseModel):
    title: str
    subtitle: str
    scenes: list[Scene]


class ReviewedScript(BaseModel):
    corrections: list[str] = Field(description="What was changed and why; empty if nothing")
    script: VideoScript


# ---------------------------------------------------------------- client

class Writer:
    def __init__(self, settings: Settings, client: anthropic.Anthropic | None = None):
        self.s = settings
        self.client = client or anthropic.Anthropic()

    def _extra(self) -> dict:
        if self.s.model in FALLBACK_MODELS:
            return {"betas": [FALLBACK_BETA], "fallbacks": "default"}
        return {}

    def _parse(self, output_type: type[BaseModel], system: str, prompt: str, effort: str):
        response = self.client.beta.messages.parse(
            model=self.s.model,
            max_tokens=32000,
            system=system,
            thinking={"type": "adaptive"},
            output_config={"effort": effort},
            output_format=output_type,
            messages=[{"role": "user", "content": prompt}],
            **self._extra(),
        )
        _check_stop(response)
        if response.parsed_output is None:
            raise RuntimeError("Το μοντέλο δεν επέστρεψε έγκυρη δομημένη απάντηση.")
        return response.parsed_output

    # 1. Σχεδιασμός αναζήτησης ------------------------------------------------
    def plan(self, topic: str, description: str) -> SearchPlan:
        return self._parse(
            SearchPlan,
            "You are an astrophysics librarian who designs literature searches.",
            f"Topic: {topic}\nViewer's description of what they want: {description}\n\n"
            "Write 3-5 short English search queries (3-6 words each, technical astrophysics "
            "vocabulary, no boolean operators) that will find the key peer-reviewed papers, review "
            "articles and newest results for this topic in OpenAlex, NASA ADS and arXiv. Cover "
            "different angles (fundamentals, latest observations, open questions).",
            effort="low",
        )

    # 2. Σύνθεση έρευνας (με αναζήτηση μόνο σε έγκυρους ιστότοπους) -----------
    def research_brief(self, topic: str, description: str, papers: list[Source],
                       progress=lambda msg: None) -> tuple[str, list[Source]]:
        today = dt.date.today().isoformat()
        prompt = (
            f"Today is {today}.\nTopic: {topic}\nViewer's description: {description}\n\n"
            f"Below are {len(papers)} sources retrieved from scholarly databases (with abstracts):\n\n"
            f"{_format_sources(papers)}\n\n"
            "Write a research brief in English for a science-video scriptwriter. Structure:\n"
            "1. KEY FACTS - numbered, each one sentence, each ending with the source tag(s), "
            "e.g. [P3] or [P3][P7].\n"
            "2. LATEST DEVELOPMENTS - what changed in the last few years.\n"
            "3. OPEN QUESTIONS & DEBATES.\n"
            "4. COMMON MISCONCEPTIONS to avoid.\n"
        )
        tools = []
        if self.s.use_web_search:
            prompt += (
                "\nUse web search (limited to space agencies, observatories and journal sites) to "
                "verify the latest values and to add any important result newer than these papers "
                "(e.g. new JWST/Euclid/LIGO/EHT/DESI results). Facts from web pages are cited "
                "automatically; do not add P-tags to them.\n"
            )
            tools = [{
                "type": "web_search_20260209",
                "name": "web_search",
                "max_uses": 8,
                "allowed_domains": AUTHORITATIVE_DOMAINS,
            }]
        prompt += "\n" + SCIENCE_RULES

        messages = [{"role": "user", "content": prompt}]
        for _ in range(6):  # συνέχιση μετά από pause_turn
            with self.client.beta.messages.stream(
                model=self.s.model,
                max_tokens=64000,
                system="You are a meticulous astrophysicist preparing a sourced research brief.",
                thinking={"type": "adaptive"},
                output_config={"effort": self.s.effort},
                tools=tools,
                messages=messages,
                **self._extra(),
            ) as stream:
                response = stream.get_final_message()
            _check_stop(response)
            if response.stop_reason != "pause_turn":
                break
            progress("Το Claude συνεχίζει την αναζήτηση…")
            messages = [messages[0], {"role": "assistant", "content": response.content}]

        return _brief_with_web_tags(response.content, start=1)

    # 3. Σενάριο -------------------------------------------------------------
    def write_script(self, topic: str, description: str, brief: str, sources: list[Source],
                     minutes: float, language: str) -> VideoScript:
        words = int(minutes * self.s.words_per_minute)
        scenes = max(6, min(16, round(minutes * 2.6)))
        return self._parse(
            VideoScript,
            "You are an award-winning science communicator writing narration for short "
            "astrophysics documentaries (in the spirit of Kurzgesagt, PBS Space Time, ESA/Hubble "
            "videos): clear, vivid, accurate, never sensational.",
            f"Topic: {topic}\nViewer's description: {description}\n"
            f"Narration language: {LANG_NAMES.get(language, language)}\n"
            f"Target length: {minutes:g} minutes ≈ {words} words of narration in total "
            f"(±10%), split into about {scenes} scenes.\n\n"
            f"RESEARCH BRIEF:\n{brief}\n\nSOURCES:\n{_format_sources(sources, abstracts=False)}\n\n"
            "Write the video script:\n"
            "- Scene 1 is a hook: a striking question or fact that makes the viewer want to watch.\n"
            "- Then build understanding step by step; use one concrete analogy or scale comparison "
            "where it helps, but keep it physically correct.\n"
            "- Include the newest results and say how we know (which telescope/experiment/method).\n"
            "- The final scene summarises the key idea and an open question for the future.\n"
            "- Narration is for the ear: short sentences, numbers written out the way they are "
            "spoken, no lists, no parentheses, no citations read aloud, no markdown.\n"
            "- `heading`, `title`, `subtitle` are in the narration language.\n"
            "- `image_query` must be English keywords suitable for the NASA Image Library "
            "(e.g. 'Webb galaxy cluster', 'neutron star illustration', 'Sun solar flare').\n"
            "- `source_ids` lists the P#/W# sources supporting the facts in that scene.\n\n"
            + SCIENCE_RULES,
            effort=self.s.effort,
        )

    # 4. Έλεγχος γεγονότων ---------------------------------------------------
    def fact_check(self, script: VideoScript, brief: str, sources: list[Source],
                   language: str) -> ReviewedScript:
        return self._parse(
            ReviewedScript,
            "You are a strict scientific fact-checker and editor for an astrophysics channel. "
            "Your job is to catch any error before publication.",
            f"RESEARCH BRIEF:\n{brief}\n\nSOURCES (with abstracts):\n{_format_sources(sources)}\n\n"
            f"DRAFT SCRIPT (JSON):\n{script.model_dump_json(indent=1)}\n\n"
            "Check every sentence of the narration against the brief and the sources:\n"
            "- Fix any claim that is wrong, outdated, overstated or unsupported (remove it if it "
            "cannot be supported). Fix wrong or missing source_ids.\n"
            "- Fix scientific misconceptions and imprecise terminology.\n"
            f"- Fix language problems; narration must be fluent {LANG_NAMES.get(language, language)}.\n"
            "- Keep the length, structure and style otherwise unchanged.\n"
            "Return the corrected script and a list of the corrections you made.\n\n"
            + SCIENCE_RULES,
            effort=self.s.effort,
        )


# ---------------------------------------------------------------- helpers

def _check_stop(response) -> None:
    if response.stop_reason == "refusal":
        details = getattr(response, "stop_details", None)
        raise RuntimeError(f"Το αίτημα απορρίφθηκε από το μοντέλο: {getattr(details, 'explanation', '')}")
    if response.stop_reason == "max_tokens":
        raise RuntimeError("Η απάντηση του μοντέλου κόπηκε (max_tokens).")


def _format_sources(sources: list[Source], abstracts: bool = True) -> str:
    lines = []
    for s in sources:
        head = (f"[{s.id}] {s.short_ref()} — {s.title} | type: {s.kind}"
                + (f" | cited by {s.cited_by}" if s.cited_by else ""))
        lines.append(head)
        if abstracts and s.abstract:
            lines.append(f"    Abstract: {s.abstract[:1800]}")
    return "\n".join(lines)


def _brief_with_web_tags(content, start: int) -> tuple[str, list[Source]]:
    """Ενώνει τα text blocks και προσθέτει ετικέτες [W#] για τις παραπομπές στο web."""
    by_url: dict[str, Source] = {}
    parts: list[str] = []
    for block in content:
        if block.type != "text":
            continue
        tags = []
        for c in getattr(block, "citations", None) or []:
            url = getattr(c, "url", None)
            if not url:
                continue
            if url not in by_url:
                by_url[url] = Source(
                    id=f"W{start + len(by_url)}", title=getattr(c, "title", "") or url,
                    url=url, kind="web", origin="web",
                    abstract=getattr(c, "cited_text", "") or "",
                )
            tag = f"[{by_url[url].id}]"
            if tag not in tags:
                tags.append(tag)
        parts.append(block.text + ("".join(tags) if tags else ""))
    return "".join(parts).strip(), list(by_url.values())


def script_to_json(script: VideoScript) -> str:
    return json.dumps(script.model_dump(), ensure_ascii=False, indent=2)
