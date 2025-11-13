# app/imaging/pipeline.py
# Completely rewritten pipeline: emits preview frames, real progress,
# and produces correct (non-black) output from NCNN Real-ESRGAN.

from __future__ import annotations
import os, sys, time, shutil, tempfile, subprocess
from pathlib import Path
from typing import Tuple, Callable
from PIL import Image

# ---------------------------- logging ----------------------------
import logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("poster-pipeline")

def banner(msg: str) -> None:
    line = "=" * 72
    log.info("\n%s\n%s\n%s", line, msg, line)

# ---------------------------- paper sizes ----------------------------
A_SIZES_MM = {
    "a1": (594, 841),
    "a2": (420, 594),
    "a3": (297, 420),
}

DEFAULT_PAPER = "a1"
DEFAULT_DPI = 300

def _mm_to_inches(mm: float) -> float:
    return mm / 25.4

def target_pixels(paper: str, dpi: int, portrait: bool) -> Tuple[int, int]:
    w_mm, h_mm = A_SIZES_MM[paper.lower()]
    w_in, h_in = _mm_to_inches(w_mm), _mm_to_inches(h_mm)
    w_px, h_px = int(w_in * dpi), int(h_in * dpi)
    if not portrait:
        w_px, h_px = h_px, w_px
    return w_px, h_px

# ---------------------------- NCNN helpers ----------------------------
def _ensure_realesrgan_exe(path: str | None) -> Path:
    if not path:
        raise FileNotFoundError("No path provided for realesrgan-ncnn-vulkan.exe")
    exe = Path(path)
    if not exe.exists():
        raise FileNotFoundError(f"Missing executable: {exe}")
    return exe

def _detect_models_dir(exe: Path) -> Path:
    m = exe.parent / "models"
    if not m.exists():
        raise FileNotFoundError(
            f"Models folder missing beside exe: {m}"
        )
    return m

def _run_ncnn(
    exe: Path, inp: Path, out: Path,
    model: str, scale: int, tilesize: int, fp16: bool
):
    cmd = [
        str(exe),
        "-i", str(inp),
        "-o", str(out),
        "-n", model,
        "-s", str(scale),
        "-t", str(tilesize),
        "-f", "png",
        "-g", "0",  # force GPU 0
    ]
    if fp16:
        cmd.append("-x")

    log.info("Real-ESRGAN: %s", " ".join(cmd))

    p = subprocess.run(
        cmd,
        cwd=str(exe.parent),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    if p.returncode != 0:
        raise RuntimeError(f"NCNN failed:\n{p.stdout}")

    if not out.exists() or out.stat().st_size == 0:
        raise RuntimeError("NCNN returned no output file")

# ---------------------------- pipeline core ----------------------------
def _emit_preview(preview_cb, path: Path):
    try:
        if preview_cb:
            preview_cb(str(path))
    except Exception:
        pass

def _emit_progress(progress_cb, pct: int):
    try:
        if progress_cb:
            progress_cb(pct)
    except Exception:
        pass

def _ai_pass(
    exe: Path,
    cur: Path,
    out: Path,
    model: str,
    scale: int,
    tilesize: int,
    fp16: bool,
    progress_cb=None,
    preview_cb=None,
    base_pct=0,
    step_pct=0,
):
    _run_ncnn(exe, cur, out, model=model, scale=scale, tilesize=tilesize, fp16=fp16)
    _emit_preview(preview_cb, out)
    _emit_progress(progress_cb, base_pct + step_pct)

    return out

def process_exact(
    input_path: str | Path,
    output_dir: str | Path,
    paper: str,
    dpi: int,
    portrait: bool,
    exe_path: str,
    model: str,
    tilesize: int,
    fp16: bool,
    force_600dpi: bool,
    keep_native_if_larger: bool,
    progress_cb: Callable[[int], None] | None = None,
    preview_cb: Callable[[str], None] | None = None,
) -> Path:

    if dpi == 600 and not force_600dpi:
        raise ValueError("For safety, 600 DPI requires Force 600 DPI enabled.")

    src = Path(input_path)
    if not src.exists():
        raise FileNotFoundError(src)

    outdir = Path(output_dir)
    outdir.mkdir(parents=True, exist_ok=True)

    exe = _ensure_realesrgan_exe(exe_path)
    _detect_models_dir(exe)

    tw, th = target_pixels(paper, dpi, portrait)
    sw, sh = Image.open(src).size

    log.info(f"Target: {tw}x{th}")
    log.info(f"Source: {sw}x{sh}")

    out_path = outdir / f"{src.stem}__{tw}x{th}px_{dpi}dpi.png"

    if keep_native_if_larger and sw >= tw and sh >= th:
        shutil.copyfile(src, out_path)
        return out_path

    work = Path(tempfile.mkdtemp(prefix="esr_"))
    cur = src

    need = max(tw / sw, th / sh)

    # PASS 1 — 4x
    if need > 3.2:
        banner("PASS 1 (4x)")
        out1 = work / "pass1.png"
        cur = _ai_pass(
            exe, cur, out1, model, 4, tilesize, fp16,
            progress_cb=progress_cb,
            preview_cb=preview_cb,
            base_pct=10,
            step_pct=40,
        )

        sw, sh = Image.open(cur).size
        need = max(tw / sw, th / sh)

    # PASS 2 — 2x
    if need > 1.6:
        banner("PASS 2 (2x)")
        out2 = work / "pass2.png"
        cur = _ai_pass(
            exe, cur, out2, model, 2, tilesize, fp16,
            progress_cb=progress_cb,
            preview_cb=preview_cb,
            base_pct=50,
            step_pct=40,
        )

    # FINAL resize to exact
    banner("FINAL RESIZE")
    im = Image.open(cur).convert("RGB")
    im = im.resize((tw, th), Image.LANCZOS)
    im.save(out_path, dpi=(dpi, dpi))

    _emit_preview(preview_cb, out_path)
    _emit_progress(progress_cb, 100)

    shutil.rmtree(work, ignore_errors=True)
    return out_path
