"""Ρυθμίσεις της εφαρμογής (διαβάζονται από μεταβλητές περιβάλλοντος)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# Ιστότοποι που θεωρούμε έγκυρους για την αναζήτηση στο web: διαστημικές
# υπηρεσίες, παρατηρητήρια, εκδότες peer-reviewed περιοδικών και βάσεις δεδομένων.
AUTHORITATIVE_DOMAINS = [
    "nasa.gov",
    "esa.int",
    "eso.org",
    "noirlab.edu",
    "stsci.edu",
    "cfa.harvard.edu",
    "caltech.edu",
    "ligo.org",
    "iau.org",
    "aas.org",
    "iopscience.iop.org",
    "aanda.org",
    "academic.oup.com",
    "nature.com",
    "science.org",
    "annualreviews.org",
    "link.springer.com",
    "journals.aps.org",
    "arxiv.org",
    "adsabs.harvard.edu",
]

FONT_CANDIDATES = [
    os.environ.get("ASTROVID_FONT", ""),
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
    "C:/Windows/Fonts/arial.ttf",
]
FONT_BOLD_CANDIDATES = [
    os.environ.get("ASTROVID_FONT_BOLD", ""),
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]

VOICES = {
    "el": ["el-GR-NestorasNeural", "el-GR-AthinaNeural"],
    "en": ["en-US-AndrewNeural", "en-US-AvaNeural", "en-GB-RyanNeural"],
}


@dataclass
class Settings:
    model: str = field(default_factory=lambda: os.environ.get("ASTROVID_MODEL", "claude-opus-5-5"))
    effort: str = field(default_factory=lambda: os.environ.get("ASTROVID_EFFORT", "high"))
    ads_token: str | None = field(default_factory=lambda: os.environ.get("ADS_API_TOKEN") or None)
    nasa_api_key: str = field(default_factory=lambda: os.environ.get("NASA_API_KEY", "DEMO_KEY"))
    contact_email: str = field(default_factory=lambda: os.environ.get("ASTROVID_CONTACT_EMAIL", ""))
    output_dir: Path = field(default_factory=lambda: Path(os.environ.get("ASTROVID_OUTPUT", "output")))
    use_web_search: bool = True
    max_papers: int = 24
    words_per_minute: int = 135  # ρυθμός αφήγησης για τον υπολογισμό λέξεων


def find_font(bold: bool = False) -> str | None:
    for path in FONT_BOLD_CANDIDATES if bold else FONT_CANDIDATES:
        if path and Path(path).is_file():
            return path
    return None
