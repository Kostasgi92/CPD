"""Συλλογή επιστημονικών πηγών από έγκριτες βάσεις δεδομένων.

- OpenAlex: δημοσιεύσεις σε peer-reviewed περιοδικά (ApJ, MNRAS, A&A, Nature, Science, ...)
  και άρθρα ανασκόπησης (π.χ. Annual Review of Astronomy and Astrophysics).
- NASA ADS (προαιρετικά, με ADS_API_TOKEN): η κύρια βιβλιογραφική βάση της αστροφυσικής,
  μόνο refereed δημοσιεύσεις.
- arXiv (astro-ph, gr-qc): τα πιο πρόσφατα αποτελέσματα, σημειώνονται ως preprints.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from urllib.parse import urlparse

import requests

log = logging.getLogger(__name__)

TIMEOUT = 25
ARXIV_CATEGORIES = [
    "astro-ph", "astro-ph.CO", "astro-ph.EP", "astro-ph.GA",
    "astro-ph.HE", "astro-ph.IM", "astro-ph.SR", "gr-qc",
]
# Τα arXiv/repositories δεν είναι peer-reviewed, ακόμα κι αν το OpenAlex τα δίνει ως κύρια θέση.
PREPRINT_VENUES = re.compile(r"arxiv|biorxiv|ssrn|zenodo|research square|preprint", re.I)


@dataclass
class Source:
    id: str = ""
    title: str = ""
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    venue: str = ""
    doi: str = ""
    url: str = ""
    abstract: str = ""
    kind: str = "peer-reviewed"  # peer-reviewed | review | preprint | web | magazine
    cited_by: int = 0
    origin: str = ""  # openalex | ads | arxiv | web

    def short_ref(self) -> str:
        if self.kind in ("web", "magazine") and self.url:
            return re.sub(r"^www\.", "", urlparse(self.url).netloc)
        if not self.authors:
            who = self.venue or "—"
        elif len(self.authors) == 1:
            who = _surname(self.authors[0])
        elif len(self.authors) == 2:
            who = f"{_surname(self.authors[0])} & {_surname(self.authors[1])}"
        else:
            who = f"{_surname(self.authors[0])} et al."
        year = f" ({self.year})" if self.year else ""
        venue = f", {self.venue}" if self.venue and self.authors else ""
        return f"{who}{year}{venue}"

    def full_ref(self) -> str:
        authors = ", ".join(self.authors[:6]) + (" et al." if len(self.authors) > 6 else "")
        parts = [p for p in [authors, f"({self.year})" if self.year else "", self.title, self.venue] if p]
        ref = ". ".join(p.rstrip(". ") for p in parts)
        link = f"https://doi.org/{self.doi}" if self.doi else self.url
        return f"{ref}. {link}".strip()

    def to_dict(self) -> dict:
        return asdict(self)


def _surname(name: str) -> str:
    name = name.strip()
    if "," in name:  # ADS: "Riess, Adam G."
        return name.split(",")[0].strip()
    return name.split()[-1] if name.split() else name


def _norm_title(t: str) -> str:
    return re.sub(r"[^a-z0-9]", "", t.lower())[:80]


def _session(contact_email: str) -> requests.Session:
    s = requests.Session()
    ua = "astrovid/1.0 (educational astrophysics video generator"
    ua += f"; mailto:{contact_email})" if contact_email else ")"
    s.headers["User-Agent"] = ua
    return s


# ---------------------------------------------------------------- OpenAlex

def _abstract_from_index(index: dict | None) -> str:
    if not index:
        return ""
    words: list[tuple[int, str]] = []
    for word, positions in index.items():
        words.extend((p, word) for p in positions)
    return " ".join(w for _, w in sorted(words))


def search_openalex(session: requests.Session, query: str, *, recent_years: int | None,
                    sort_by_citations: bool, per_page: int = 8, email: str = "") -> list[Source]:
    filters = ["type:article|review", "has_abstract:true", "primary_topic.field.id:31"]
    if recent_years:
        since = dt.date.today().replace(year=dt.date.today().year - recent_years)
        filters.append(f"from_publication_date:{since.isoformat()}")
    params = {
        "search": query,
        "filter": ",".join(filters),
        "per_page": per_page,
        "select": "id,doi,display_name,publication_year,authorships,primary_location,"
                  "abstract_inverted_index,cited_by_count,type",
    }
    if sort_by_citations:
        params["sort"] = "cited_by_count:desc"
    if email:
        params["mailto"] = email
    r = session.get("https://api.openalex.org/works", params=params, timeout=TIMEOUT)
    r.raise_for_status()
    out = []
    for w in r.json().get("results", []):
        loc = w.get("primary_location") or {}
        src = loc.get("source") or {}
        venue = src.get("display_name") or ""
        is_journal = src.get("type") == "journal" and not PREPRINT_VENUES.search(venue)
        kind = "preprint" if not is_journal else ("review" if w.get("type") == "review" else "peer-reviewed")
        doi = (w.get("doi") or "").replace("https://doi.org/", "")
        out.append(Source(
            title=w.get("display_name") or "",
            authors=[a["author"]["display_name"] for a in w.get("authorships", []) if a.get("author")],
            year=w.get("publication_year"),
            venue=venue,
            doi=doi,
            url=loc.get("landing_page_url") or w.get("id", ""),
            abstract=_abstract_from_index(w.get("abstract_inverted_index")),
            kind=kind,
            cited_by=w.get("cited_by_count") or 0,
            origin="openalex",
        ))
    return out


# ---------------------------------------------------------------- NASA ADS

def search_ads(session: requests.Session, query: str, token: str, rows: int = 8) -> list[Source]:
    params = {
        "q": f"({query}) property:refereed collection:astronomy year:{dt.date.today().year - 8}-",
        "fl": "title,author,year,pub,doi,abstract,bibcode,citation_count,doctype",
        "rows": rows,
        "sort": "score desc",
    }
    r = session.get("https://api.adsabs.harvard.edu/v1/search/query", params=params,
                    headers={"Authorization": f"Bearer {token}"}, timeout=TIMEOUT)
    r.raise_for_status()
    out = []
    for d in r.json().get("response", {}).get("docs", []):
        if not d.get("abstract"):
            continue
        out.append(Source(
            title=(d.get("title") or [""])[0],
            authors=d.get("author") or [],
            year=int(d["year"]) if d.get("year") else None,
            venue=d.get("pub") or "",
            doi=(d.get("doi") or [""])[0],
            url=f"https://ui.adsabs.harvard.edu/abs/{d.get('bibcode')}",
            abstract=d.get("abstract") or "",
            kind="review" if d.get("doctype") == "review" else "peer-reviewed",
            cited_by=d.get("citation_count") or 0,
            origin="ads",
        ))
    return out


# ---------------------------------------------------------------- arXiv

_ATOM = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}


def search_arxiv(session: requests.Session, query: str, max_results: int = 6) -> list[Source]:
    terms = " AND ".join(f"all:{w}" for w in re.findall(r"[\w\-]+", query)[:6])
    cats = " OR ".join(f"cat:{c}" for c in ARXIV_CATEGORIES)
    params = {
        "search_query": f"({terms}) AND ({cats})",
        "sortBy": "relevance",
        "max_results": max_results,
    }
    r = session.get("https://export.arxiv.org/api/query", params=params, timeout=TIMEOUT)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    out = []
    for e in root.findall("a:entry", _ATOM):
        published = e.findtext("a:published", "", _ATOM)
        journal_ref = e.findtext("arxiv:journal_ref", "", _ATOM)
        doi = e.findtext("arxiv:doi", "", _ATOM)
        out.append(Source(
            title=" ".join(e.findtext("a:title", "", _ATOM).split()),
            authors=[a.findtext("a:name", "", _ATOM) for a in e.findall("a:author", _ATOM)],
            year=int(published[:4]) if published else None,
            # Αν το preprint έχει ήδη δημοσιευτεί σε περιοδικό, το arXiv το δηλώνει στο journal_ref.
            venue=journal_ref or "arXiv",
            doi=doi,
            url=e.findtext("a:id", "", _ATOM),
            abstract=" ".join(e.findtext("a:summary", "", _ATOM).split()),
            kind="peer-reviewed" if journal_ref or doi else "preprint",
            origin="arxiv",
        ))
    return out


# ---------------------------------------------------------------- orchestration

def gather_sources(queries: list[str], *, max_papers: int, ads_token: str | None,
                   contact_email: str = "", progress=lambda msg: None) -> list[Source]:
    session = _session(contact_email)
    buckets: dict[str, list[Source]] = {"recent": [], "classic": [], "ads": [], "arxiv": []}
    for q in queries:
        jobs = [
            ("recent", "OpenAlex (πρόσφατες δημοσιεύσεις)",
             lambda q=q: search_openalex(session, q, recent_years=6, sort_by_citations=False, email=contact_email)),
            ("classic", "OpenAlex (θεμελιώδεις εργασίες/ανασκοπήσεις)",
             lambda q=q: search_openalex(session, q, recent_years=None, sort_by_citations=True,
                                         per_page=5, email=contact_email)),
            ("arxiv", "arXiv", lambda q=q: search_arxiv(session, q)),
        ]
        if ads_token:
            jobs.append(("ads", "NASA ADS", lambda q=q: search_ads(session, q, ads_token)))
        for bucket, label, job in jobs:
            progress(f"Αναζήτηση στο {label}: «{q}»")
            try:
                buckets[bucket].extend(job())
            except (requests.RequestException, ET.ParseError, ValueError, KeyError) as exc:
                log.warning("%s failed for %r: %s", label, q, exc)
                progress(f"⚠️ {label} μη διαθέσιμο ({type(exc).__name__})")

    # Εναλλάσσουμε τις κατηγορίες ώστε να υπάρχει ισορροπία ανάμεσα σε πρόσφατα
    # αποτελέσματα, θεμελιώδεις εργασίες και τα νεότερα preprints.
    order = ["ads", "recent", "classic", "arxiv"]
    seen: set[str] = set()
    picked: list[Source] = []
    while len(picked) < max_papers and any(buckets[b] for b in order):
        for b in order:
            while buckets[b]:
                s = buckets[b].pop(0)
                keys = {k for k in (s.doi.lower(), _norm_title(s.title)) if k}
                if not s.title or not s.abstract or keys & seen:
                    continue
                seen |= keys
                picked.append(s)
                break
            if len(picked) >= max_papers:
                break
    for i, s in enumerate(picked, 1):
        s.id = f"P{i}"
    return picked
