"""Ολόκληρη η ροή: θέμα → πηγές → έρευνα → σενάριο → έλεγχος → φωνή → εικόνες → βίντεο."""

from __future__ import annotations

import datetime as dt
import json
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from . import render, visuals
from .config import VOICES, Settings
from .llm import VideoScript, Writer
from .research import Source, gather_sources
from .tts import EdgeTTS, Narration, probe_duration

log = logging.getLogger(__name__)

SIZES = {"16:9": (1920, 1080), "9:16": (1080, 1920), "16:9-720p": (1280, 720)}
LABELS = {
    "el": {"sources": "Πηγές", "image": "Εικόνα", "refs": "Πηγές & βιβλιογραφία",
           "synthetic": "Ψηφιακή απεικόνιση",
           "note": "Το σενάριο γράφτηκε με τη βοήθεια AI αποκλειστικά από τις παραπάνω πηγές και "
                   "ελέγχθηκε αυτόματα για επιστημονική ακρίβεια. Preprint = δεν έχει ακόμη κριθεί "
                   "από ομότιμους. Πλήρης βιβλιογραφία στο αρχείο sources.md."},
    "en": {"sources": "Sources", "image": "Image", "refs": "Sources & references",
           "synthetic": "Digital illustration",
           "note": "Script written with AI assistance strictly from the sources above and "
                   "automatically fact-checked. Preprint = not yet peer-reviewed. Full "
                   "bibliography in sources.md."},
}
MIN_SECONDS, MAX_SECONDS = 120, 300


@dataclass
class Result:
    folder: Path
    video: Path
    script: VideoScript
    sources: list[Source]
    brief: str
    corrections: list[str] = field(default_factory=list)
    duration: float = 0.0
    warnings: list[str] = field(default_factory=list)


GREEK = dict(zip("αβγδεζηθικλμνξοπρσςτυφχψω", ["a", "v", "g", "d", "e", "z", "i", "th", "i", "k", "l", "m",
                                                "n", "x", "o", "p", "r", "s", "s", "t", "y", "f", "ch",
                                                "ps", "o"]))


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c)).replace("ου", "ou")
    text = "".join(GREEK.get(c, c) for c in text)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()[:40] or "video"


def generate(topic: str, description: str, *, minutes: float = 3.0, language: str = "el",
             voice: str | None = None, aspect: str = "16:9", settings: Settings | None = None,
             writer: Writer | None = None, tts=None, images: visuals.NasaImages | None = None,
             progress=lambda msg, frac=None: None) -> Result:
    s = settings or Settings()
    minutes = min(5.0, max(2.0, float(minutes)))
    size = SIZES[aspect]
    labels = LABELS.get(language, LABELS["en"])
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    folder = s.output_dir / f"{stamp}-{slugify(topic)}"
    work = folder / "work"
    work.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []
    writer = writer or Writer(s)

    # 1. Αναζήτηση βιβλιογραφίας ------------------------------------------
    progress("Σχεδιασμός βιβλιογραφικής αναζήτησης…", 0.02)
    plan = writer.plan(topic, description)
    progress("Ερωτήματα: " + " | ".join(plan.queries), 0.05)
    papers = gather_sources(plan.queries, max_papers=s.max_papers, ads_token=s.ads_token,
                            contact_email=s.contact_email, progress=lambda m: progress(m))
    n_ref = sum(p.kind in ("peer-reviewed", "review") for p in papers)
    progress(f"Βρέθηκαν {len(papers)} πηγές ({n_ref} peer-reviewed / ανασκοπήσεις).", 0.15)
    if n_ref < 3:
        warnings.append("Βρέθηκαν λίγες peer-reviewed πηγές· ελέγξτε προσεκτικά το αποτέλεσμα.")

    # 2. Έρευνα, σενάριο, έλεγχος -----------------------------------------
    progress("Μελέτη πηγών και επαλήθευση νεότερων δεδομένων…", 0.18)
    brief, web_sources = writer.research_brief(topic, description, papers, progress=lambda m: progress(m))
    sources = papers + web_sources
    (folder / "research_brief.md").write_text(brief, encoding="utf-8")

    progress("Συγγραφή σεναρίου…", 0.35)
    draft = writer.write_script(topic, description, brief, sources, minutes, language)
    progress("Επιστημονικός έλεγχος σεναρίου…", 0.45)
    reviewed = writer.fact_check(draft, brief, sources, language)
    script = reviewed.script
    if not script.scenes:
        raise RuntimeError("Το σενάριο δεν περιέχει σκηνές.")
    (folder / "script_draft.json").write_text(draft.model_dump_json(indent=2), encoding="utf-8")
    (folder / "script.json").write_text(script.model_dump_json(indent=2), encoding="utf-8")
    by_id = {src.id: src for src in sources}
    _write_markdown(folder, topic, script, sources, by_id, reviewed.corrections)

    # 3. Αφήγηση ----------------------------------------------------------
    voice = voice or VOICES.get(language, VOICES["en"])[0]
    tts = tts or EdgeTTS(voice)
    narrations = _narrate(script, tts, work, progress)
    total = sum(n.duration for n in narrations) + 0.6 * len(narrations) + 12
    target = minutes * 60
    if isinstance(tts, EdgeTTS) and abs(total - target) / target > 0.12:
        pct = max(-15, min(25, round((total / target - 1) * 100)))
        progress(f"Προσαρμογή ρυθμού αφήγησης ({pct:+d}%) για διάρκεια ~{minutes:g}′…", 0.55)
        tts = EdgeTTS(voice, rate=f"{pct:+d}%")
        narrations = _narrate(script, tts, work, progress)
        total = sum(n.duration for n in narrations) + 0.6 * len(narrations) + 12
    if not MIN_SECONDS <= total <= MAX_SECONDS:
        warnings.append(f"Η τελική διάρκεια ({total / 60:.1f}′) είναι εκτός του εύρους 2–5 λεπτών.")

    # 4. Εικόνες ----------------------------------------------------------
    images = images or visuals.NasaImages(s.output_dir / "_image_cache")
    bg_size = (int(size[0] * 1.5), int(size[1] * 1.5))
    pictures: list[visuals.Picture | None] = []
    for i, scene in enumerate(script.scenes):
        progress(f"Εικόνα σκηνής {i + 1}: «{scene.image_query}»", 0.6 + 0.1 * i / len(script.scenes))
        pic = images.find(scene.image_query) if scene.image_query else None
        bg = work / f"bg_{i:02d}.jpg"
        if pic:
            visuals.cover(Image.open(pic.path), bg_size).save(bg, quality=92)
        else:
            visuals.starfield(bg_size, seed=i).save(bg, quality=92)
        pictures.append(pic)

    # 5. Μοντάζ -----------------------------------------------------------
    clips: list[Path] = []
    order = [0, "title"] + list(range(1, len(script.scenes))) + ["refs"]
    for step, item in enumerate(order):
        progress(f"Μοντάζ ({step + 1}/{len(order)})…", 0.7 + 0.27 * step / len(order))
        clip = work / f"clip_{step:02d}.mp4"
        if item == "title":
            title_bg = work / "title.png"
            base = Image.open(work / "bg_00.jpg")
            visuals.title_card(base, script.title, script.subtitle).save(title_bg)
            render.render_scene(title_bg, [], None, 4.0, clip, size, motion="zoom_out")
        elif item == "refs":
            used = _used_sources(script, by_id)
            refs = [f"{src.short_ref()} — {src.title}" + (" [preprint]" if src.kind == "preprint" else "")
                    for src in used]
            credit_list = sorted({p.credit for p in pictures if p})
            credits_line = f"{labels['image']}: " + (", ".join(credit_list) if credit_list else labels["synthetic"])
            card = work / "refs.png"
            visuals.references_card(size, labels["refs"], refs, credits_line, labels["note"]).save(card)
            static = work / "refs_bg.png"
            Image.open(card).resize(bg_size).save(static)
            render.render_scene(static, [], None, 8.0, clip, size, motion="none")
        else:
            _scene_clip(item, script, narrations[item], pictures[item], by_id, labels, size, work, clip)
        clips.append(clip)

    video = folder / f"{slugify(topic)}.mp4"
    progress("Τελική σύνθεση βίντεο…", 0.98)
    render.concat(clips, video, work)
    duration = probe_duration(video)
    _write_credits(folder, pictures)
    progress(f"Έτοιμο! Διάρκεια {int(duration // 60)}:{int(duration % 60):02d}", 1.0)
    return Result(folder, video, script, sources, brief, reviewed.corrections, duration, warnings)


# ---------------------------------------------------------------- helpers

def _narrate(script: VideoScript, tts, work: Path, progress) -> list[Narration]:
    out = []
    for i, scene in enumerate(script.scenes):
        progress(f"Αφήγηση σκηνής {i + 1}/{len(script.scenes)}…", 0.5 + 0.08 * i / len(script.scenes))
        out.append(tts.synthesize(scene.narration, work / f"voice_{i:02d}.mp3"))
    return out


def _scene_clip(i: int, script: VideoScript, narration: Narration, pic, by_id: dict[str, Source],
                labels: dict, size, work: Path, out: Path) -> Path:
    scene = script.scenes[i]
    delay, tail = 0.3, 0.3
    duration = narration.duration + delay + tail
    refs = [by_id[sid].short_ref() for sid in scene.source_ids if sid in by_id][:2]
    footer_parts = []
    if refs:
        footer_parts.append(f"{labels['sources']}: " + "; ".join(refs))
    footer_parts.append(f"{labels['image']}: {pic.credit if pic else labels['synthetic']}")
    static = work / f"overlay_{i:02d}.png"
    visuals.scene_overlay(size, scene.heading, " · ".join(footer_parts)).save(static)
    layers = [render.Layer(static)]
    for j, (start, end, text) in enumerate(narration.cues):
        png = work / f"sub_{i:02d}_{j:02d}.png"
        visuals.subtitle_overlay(size, text).save(png)
        layers.append(render.Layer(png, start + delay, min(end + delay, duration)))
    motion = render.MOTIONS[i % len(render.MOTIONS)]
    return render.render_scene(work / f"bg_{i:02d}.jpg", layers, narration.audio, duration, out, size,
                               motion=motion, audio_delay=delay)


def _used_sources(script: VideoScript, by_id: dict[str, Source]) -> list[Source]:
    seen, used = set(), []
    for scene in script.scenes:
        for sid in scene.source_ids:
            if sid in by_id and sid not in seen:
                seen.add(sid)
                used.append(by_id[sid])
    return used


def _write_markdown(folder: Path, topic: str, script: VideoScript, sources: list[Source],
                    by_id: dict[str, Source], corrections: list[str]) -> None:
    lines = [f"# {script.title}", f"*{script.subtitle}*", "", f"Θέμα: {topic}", ""]
    for i, scene in enumerate(script.scenes, 1):
        tags = ", ".join(by_id[s].short_ref() for s in scene.source_ids if s in by_id)
        lines += [f"## {i}. {scene.heading}", "", scene.narration, "", f"_Πηγές: {tags or '—'}_", ""]
    if corrections:
        lines += ["## Διορθώσεις από τον επιστημονικό έλεγχο", ""] + [f"- {c}" for c in corrections] + [""]
    (folder / "script.md").write_text("\n".join(lines), encoding="utf-8")

    used = {s.id for s in _used_sources(script, by_id)}
    kinds = {"peer-reviewed": "Peer-reviewed", "review": "Άρθρο ανασκόπησης",
             "preprint": "Preprint (χωρίς κρίση)", "web": "Ιστότοπος οργανισμού/περιοδικού"}
    bib = ["# Πηγές", "", "Με ★ οι πηγές που χρησιμοποιούνται στο βίντεο.", ""]
    for src in sources:
        star = "★ " if src.id in used else ""
        bib.append(f"- {star}**[{src.id}]** {src.full_ref()} — _{kinds.get(src.kind, src.kind)}_")
    (folder / "sources.md").write_text("\n".join(bib) + "\n", encoding="utf-8")
    (folder / "sources.json").write_text(
        json.dumps([s.to_dict() for s in sources], ensure_ascii=False, indent=2), encoding="utf-8")


def _write_credits(folder: Path, pictures) -> None:
    lines = ["# Εικόνες", ""]
    for i, p in enumerate(pictures, 1):
        lines.append(f"- Σκηνή {i}: " + (f"{p.title} — {p.credit} — {p.url}" if p else "συνθετικό φόντο"))
    (folder / "image_credits.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
