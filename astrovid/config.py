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
    "newscientist.com",
]
# Περιοδικά επιστημονικής δημοσιογραφίας: χρήσιμα για νέα και πλαίσιο, όχι peer-reviewed.
MAGAZINE_DOMAINS = ["newscientist.com"]

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

# Φωνές Microsoft Edge (edge-tts) ανά γλώσσα αφήγησης: όνομα φωνής → περιγραφή.
_MULTILINGUAL = {
    "en-US-AndrewMultilingualNeural": "Andrew (πολυγλωσσική, ανδρική)",
    "en-US-AvaMultilingualNeural": "Ava (πολυγλωσσική, γυναικεία)",
    "en-US-BrianMultilingualNeural": "Brian (πολυγλωσσική, ανδρική)",
    "en-US-EmmaMultilingualNeural": "Emma (πολυγλωσσική, γυναικεία)",
}
VOICES = {
    "el": {
        "el-GR-NestorasNeural": "Νέστορας (ελληνική, ανδρική)",
        "el-GR-AthinaNeural": "Αθηνά (ελληνική, γυναικεία)",
        **{k: v + " με αγγλική προφορά" for k, v in _MULTILINGUAL.items()},
    },
    "en": {
        "en-US-AndrewNeural": "Andrew (US, ανδρική)",
        "en-US-AvaNeural": "Ava (US, γυναικεία)",
        "en-US-BrianNeural": "Brian (US, ανδρική)",
        "en-US-EmmaNeural": "Emma (US, γυναικεία)",
        "en-US-ChristopherNeural": "Christopher (US, ανδρική)",
        "en-US-JennyNeural": "Jenny (US, γυναικεία)",
        "en-US-GuyNeural": "Guy (US, ανδρική)",
        "en-US-AriaNeural": "Aria (US, γυναικεία)",
        "en-GB-RyanNeural": "Ryan (UK, ανδρική)",
        "en-GB-SoniaNeural": "Sonia (UK, γυναικεία)",
        "en-GB-ThomasNeural": "Thomas (UK, ανδρική)",
        "en-GB-LibbyNeural": "Libby (UK, γυναικεία)",
        "en-AU-NatashaNeural": "Natasha (Αυστραλία, γυναικεία)",
        **_MULTILINGUAL,
    },
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
