"""Αφήγηση: μετατροπή κειμένου σε ομιλία (Microsoft Edge neural voices) με χρονισμό υποτίτλων."""

from __future__ import annotations

import asyncio
import os
import re
import ssl
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Narration:
    audio: Path
    duration: float
    cues: list[tuple[float, float, str]] = field(default_factory=list)


def probe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return float(out)


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?;·…])\s+", text.strip())
    return [p for p in (s.strip() for s in parts) if p]


def chunk_cue(start: float, end: float, text: str, max_chars: int = 95) -> list[tuple[float, float, str]]:
    """Σπάει μια μεγάλη πρόταση σε μικρότερους υπότιτλους, με χρόνο ανάλογο του μήκους."""
    words = text.split()
    chunks, cur = [], ""
    for wd in words:
        if cur and len(cur) + 1 + len(wd) > max_chars:
            chunks.append(cur)
            cur = wd
        else:
            cur = f"{cur} {wd}".strip()
    if cur:
        chunks.append(cur)
    total = sum(len(c) for c in chunks) or 1
    out, t = [], start
    for c in chunks:
        dur = (end - start) * len(c) / total
        out.append((t, t + dur, c))
        t += dur
    return out


def proportional_cues(text: str, duration: float) -> list[tuple[float, float, str]]:
    sentences = split_sentences(text)
    total = sum(len(s) for s in sentences) or 1
    cues, t = [], 0.0
    for s in sentences:
        d = duration * len(s) / total
        cues.extend(chunk_cue(t, t + d, s))
        t += d
    return cues


class EdgeTTS:
    def __init__(self, voice: str, rate: str = "+0%"):
        self.voice = voice
        self.rate = rate

    def synthesize(self, text: str, out: Path) -> Narration:
        sentences = asyncio.run(self._run(text, out))
        duration = probe_duration(out)
        if not sentences:
            return Narration(out, duration, proportional_cues(text, duration))
        cues = []
        for i, (start, dur, s) in enumerate(sentences):
            # Ο υπότιτλος μένει στην οθόνη μέχρι να ξεκινήσει η επόμενη πρόταση.
            end = sentences[i + 1][0] if i + 1 < len(sentences) else min(duration, start + dur + 0.4)
            cues.extend(chunk_cue(start, end, s))
        return Narration(out, duration, cues)

    async def _run(self, text: str, out: Path) -> list[tuple[float, float, str]]:
        import aiohttp
        import edge_tts

        cafile = os.environ.get("SSL_CERT_FILE") or os.environ.get("REQUESTS_CA_BUNDLE")
        ctx = ssl.create_default_context(cafile=cafile) if cafile else ssl.create_default_context()
        proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
        comm = edge_tts.Communicate(text, self.voice, rate=self.rate, boundary="SentenceBoundary",
                                    connector=aiohttp.TCPConnector(ssl=ctx), proxy=proxy)
        sentences = []
        with open(out, "wb") as fh:
            async for chunk in comm.stream():
                if chunk["type"] == "audio":
                    fh.write(chunk["data"])
                elif chunk["type"] in ("SentenceBoundary", "WordBoundary"):
                    # offset/duration σε μονάδες των 100ns
                    sentences.append((chunk["offset"] / 1e7, chunk["duration"] / 1e7, chunk["text"]))
        return sentences


class SilentTTS:
    """Για δοκιμές χωρίς δίκτυο: σιωπή με διάρκεια ανάλογη του κειμένου."""

    def __init__(self, words_per_minute: int = 135):
        self.wpm = words_per_minute

    def synthesize(self, text: str, out: Path) -> Narration:
        duration = max(1.5, len(text.split()) / self.wpm * 60)
        out = out.with_suffix(".m4a")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                        "anullsrc=r=24000:cl=mono", "-t", f"{duration:.3f}", "-c:a", "aac", str(out)],
                       check=True)
        return Narration(out, duration, proportional_cues(text, duration))
