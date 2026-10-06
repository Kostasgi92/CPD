"""Γραμμή εντολών: python -m astrovid "Θέμα" -d "Περιγραφή" -m 3"""

from __future__ import annotations

import argparse
import logging

from .config import VOICES, Settings
from .pipeline import SIZES, generate


def main() -> None:
    p = argparse.ArgumentParser(prog="astrovid", description="Βίντεο αστροφυσικής 2–5 λεπτών από έγκριτες πηγές.")
    p.add_argument("topic", help="Θέμα, π.χ. «Η ένταση του Hubble»")
    p.add_argument("-d", "--description", default="", help="Τι θέλετε να καλύπτει το βίντεο")
    p.add_argument("-m", "--minutes", type=float, default=3.0, help="Διάρκεια σε λεπτά (2–5)")
    p.add_argument("-l", "--language", default="el", choices=sorted(VOICES), help="Γλώσσα αφήγησης")
    p.add_argument("--voice", help="Φωνή edge-tts (π.χ. el-GR-AthinaNeural)")
    p.add_argument("--aspect", default="16:9", choices=sorted(SIZES), help="Μορφή εικόνας")
    p.add_argument("--no-web", action="store_true", help="Χωρίς αναζήτηση σε ιστότοπους NASA/ESA/περιοδικών")
    p.add_argument("-o", "--output", help="Φάκελος εξόδου")
    args = p.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    settings = Settings()
    settings.use_web_search = not args.no_web
    if args.output:
        from pathlib import Path
        settings.output_dir = Path(args.output)

    def progress(msg: str, frac: float | None = None) -> None:
        print(f"[{frac * 100:5.1f}%] {msg}" if frac is not None else f"         {msg}", flush=True)

    result = generate(args.topic, args.description or args.topic, minutes=args.minutes,
                      language=args.language, voice=args.voice, aspect=args.aspect,
                      settings=settings, progress=progress)
    print(f"\nΒίντεο: {result.video}\nΣενάριο: {result.folder / 'script.md'}\n"
          f"Πηγές: {result.folder / 'sources.md'}")
    for w in result.warnings:
        print(f"⚠️  {w}")


if __name__ == "__main__":
    main()
