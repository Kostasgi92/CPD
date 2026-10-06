"""Δοκιμές χωρίς δίκτυο: ψεύτικο LLM, σιωπηλή αφήγηση, συνθετικές εικόνες, πραγματικό ffmpeg."""

from __future__ import annotations

from types import SimpleNamespace

from astrovid import pipeline
from astrovid.config import Settings
from astrovid.llm import ReviewedScript, Scene, SearchPlan, VideoScript, _brief_with_web_tags
from astrovid.research import Source, _abstract_from_index
from astrovid.tts import SilentTTS, probe_duration


class FakeWriter:
    def answer(self, topic, description):
        return "Οι αστέρες νετρονίων είναι τα πυκνότερα ορατά αντικείμενα."

    def plan(self, topic, description, answer=""):
        return SearchPlan(queries=["neutron star equation of state"], working_title=topic)

    def research_brief(self, topic, description, papers, answer="", progress=None):
        web = [Source(id="W1", title="NICER", url="https://www.nasa.gov/nicer", kind="web", origin="web")]
        return "1. Neutron stars have radii of about 12 km [P1].[W1]", web

    def write_script(self, topic, description, brief, sources, minutes, language, answer=""):
        text = ("Ένας αστέρας νετρονίων έχει διάμετρο περίπου είκοσι τεσσάρων χιλιομέτρων. "
                "Κι όμως, η μάζα του ξεπερνά τη μάζα του Ήλιου. ") * 2
        return VideoScript(title="Αστέρες νετρονίων", subtitle="Η πιο πυκνή ύλη του Σύμπαντος",
                           scenes=[Scene(heading=f"Σκηνή {i}", narration=text, image_query="neutron star",
                                         source_ids=["P1", "W1"]) for i in range(3)])

    def fact_check(self, script, brief, sources, language):
        return ReviewedScript(corrections=["Καμία ουσιαστική διόρθωση."], script=script)


class NoImages:
    def find(self, query):
        return None


def test_full_pipeline_offline(tmp_path, monkeypatch):
    paper = Source(id="P1", title="A NICER view of PSR J0030+0451", authors=["Riley, T. E.", "Watts, A."],
                   year=2019, venue="ApJL", doi="10.3847/2041-8213/ab481c", abstract="...")
    monkeypatch.setattr(pipeline, "gather_sources", lambda *a, **k: [paper])
    settings = Settings(output_dir=tmp_path)
    messages = []
    result = pipeline.generate("Αστέρες νετρονίων", "Πόσο πυκνοί είναι;", minutes=2, settings=settings,
                               writer=FakeWriter(), tts=SilentTTS(), images=NoImages(),
                               aspect="16:9-720p", progress=lambda m, f=None: messages.append(m))
    assert result.video.exists()
    assert abs(probe_duration(result.video) - result.duration) < 0.5
    # 3 σκηνές + τίτλος (4s) + βιβλιογραφία (8s)
    assert result.duration > 12 + 3 * 5
    assert (result.folder / "sources.md").read_text(encoding="utf-8").count("- ★") == 2
    assert "Riley & Watts (2019), ApJL" in (result.folder / "script.md").read_text(encoding="utf-8")
    assert any("Έτοιμο" in m for m in messages)
    assert result.answer and (result.folder / "claude_answer.md").exists()
    assert result.video.name == "asteres-netronion.mp4"


def test_abstract_reconstruction():
    assert _abstract_from_index({"dark": [0], "energy": [1, 3], "and": [2]}) == "dark energy and energy"


def test_web_citations_become_sources():
    cite = SimpleNamespace(url="https://www.esa.int/x", title="ESA Euclid", cited_text="Euclid saw...")
    blocks = [SimpleNamespace(type="text", text="Euclid launched in 2023.", citations=[cite]),
              SimpleNamespace(type="server_tool_use"),
              SimpleNamespace(type="text", text=" Again.", citations=[cite])]
    text, web = _brief_with_web_tags(blocks, start=1)
    assert text == "Euclid launched in 2023.[W1] Again.[W1]"
    assert [w.id for w in web] == ["W1"] and web[0].kind == "web"


def test_new_scientist_is_marked_as_magazine():
    cite = SimpleNamespace(url="https://www.newscientist.com/article/x", title="NS", cited_text="...")
    _, web = _brief_with_web_tags([SimpleNamespace(type="text", text="a", citations=[cite])], start=1)
    assert web[0].kind == "magazine" and web[0].short_ref() == "newscientist.com"
