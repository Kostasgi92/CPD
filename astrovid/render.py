"""Μοντάζ με ffmpeg: κίνηση κάμερας (Ken Burns), υπότιτλοι, ήχος και ένωση των σκηνών."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

FPS = 30
MOTIONS = ["zoom_in", "pan_right", "zoom_out", "pan_left"]


@dataclass
class Layer:
    png: Path
    start: float | None = None  # None = σε όλη τη διάρκεια
    end: float | None = None


def _zoompan(motion: str, frames: int, size: tuple[int, int]) -> str:
    n = max(frames, 1)
    w, h = size
    center = "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
    if motion == "zoom_in":
        z, xy = f"'1+0.12*on/{n}'", center
    elif motion == "zoom_out":
        z, xy = f"'1.12-0.12*on/{n}'", center
    elif motion == "pan_right":
        z, xy = "'1.12'", f"x='(iw-iw/zoom)*on/{n}':y='ih/2-(ih/zoom/2)'"
    elif motion == "pan_left":
        z, xy = "'1.12'", f"x='(iw-iw/zoom)*(1-on/{n})':y='ih/2-(ih/zoom/2)'"
    else:
        z, xy = "'1'", center
    return f"zoompan=z={z}:{xy}:d={n}:s={w}x{h}:fps={FPS}"


def render_scene(background: Path, layers: list[Layer], audio: Path | None, duration: float,
                 out: Path, size: tuple[int, int], motion: str = "zoom_in",
                 audio_delay: float = 0.0) -> Path:
    frames = int(round(duration * FPS))
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(background)]
    for layer in layers:
        cmd += ["-i", str(layer.png)]
    if audio:
        cmd += ["-i", str(audio)]
    else:
        cmd += ["-f", "lavfi", "-t", f"{duration:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
    audio_idx = len(layers) + 1

    fade = min(0.5, duration / 4)
    chains = [f"[0:v]{_zoompan(motion, frames, size)},format=yuva420p[v0]"]
    last = "v0"
    for i, layer in enumerate(layers, start=1):
        enable = ""
        if layer.start is not None:
            enable = f":enable='between(t,{layer.start:.3f},{layer.end:.3f})'"
        chains.append(f"[{last}][{i}:v]overlay=0:0:eof_action=repeat{enable}[v{i}]")
        last = f"v{i}"
    chains.append(f"[{last}]fade=t=in:st=0:d={fade:.2f},fade=t=out:st={duration - fade:.3f}:d={fade:.2f},"
                  f"format=yuv420p[vout]")
    delay_ms = int(audio_delay * 1000)
    chains.append(f"[{audio_idx}:a]aresample=48000,aformat=channel_layouts=stereo,"
                  f"adelay={delay_ms}|{delay_ms},apad,atrim=0:{duration:.3f},"
                  f"afade=t=out:st={max(duration - 0.3, 0):.3f}:d=0.3[aout]")
    cmd += ["-filter_complex", ";".join(chains), "-map", "[vout]", "-map", "[aout]",
            "-t", f"{duration:.3f}", "-r", str(FPS),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2", str(out)]
    _run(cmd)
    return out


def concat(clips: list[Path], out: Path, workdir: Path) -> Path:
    listing = workdir / "concat.txt"
    listing.write_text("".join(f"file '{c.resolve().as_posix()}'\n" for c in clips), encoding="utf-8")
    joined = workdir / "joined.mp4"
    _run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
          "-c", "copy", str(joined)])
    # Κανονικοποίηση έντασης (EBU R128) και faststart για αναπαραγωγή στο web.
    _run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(joined), "-c:v", "copy",
          "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-c:a", "aac", "-b:a", "160k", "-ar", "48000",
          "-movflags", "+faststart", str(out)])
    return out


def _run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg απέτυχε:\n{proc.stderr[-2000:]}")
