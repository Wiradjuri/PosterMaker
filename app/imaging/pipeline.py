# app/imaging/pipeline.py
# Simplified, robust Real-ESRGAN pipeline.
# - Single NCNN 4x pass (no multi-pass tiling, no scrambling)
# - Final resize that PRESERVES aspect ratio:
#     * scale to fit inside paper size
#     * pad with black bars as needed (no stretching)
# - Progress + preview callbacks for the GUI
# - Same public API as previous versions

from __future__ import annotations

import os
import sys
import time
import tempfile
import subprocess
from pathlib import Path
from typing import Callable, Optional, Tuple

from PIL import Image

# ---------------------------- logging ----------------------------
try:
    import logging

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    log: "logging.Logger" = logging.getLogger("poster-pipeline")
except Exception:  # pragma: no cover - ultra fallback for weird envs

    class _L:
        def info(self, m: str) -> None:
            print(time.strftime("%Y-%m-%d %H:%M:%S"), "| INFO |", m)

        def warning(self, m: str) -> None:
            print(time.strftime("%Y-%m-%d %H:%M:%S"), "| WARNING |", m)

        def error(self, m: str) -> None:
            print(time.strftime("%Y-%m-%d %H:%M:%S"), "| ERROR |", m)

    log = _L()  # type: ignore[assignment]


def banner(msg: str) -> None:
    line = "=" * 70
    log.info("\n%s\n%s\n%s", line, msg, line)


# ---------------------------- paper sizes ----------------------------

A_SIZES_MM = {
    "a0": (841, 1189),
    "a1": (594, 841),
    "a2": (420, 594),
    "a3": (297, 420),
    "a4": (210, 297),
}


DEFAULT_PAPER = "a1"
DEFAULT_DPI = 300


def _mm_to_inches(mm: float) -> float:
    return mm / 25.4


def target_pixels(
    paper: str = DEFAULT_PAPER, dpi: int = DEFAULT_DPI, portrait: bool = True
) -> Tuple[int, int]:
    paper_key = paper.lower()
    if paper_key not in A_SIZES_MM:
        raise ValueError(f"Unsupported paper size: {paper}")
    w_mm, h_mm = A_SIZES_MM[paper_key]
    w_in, h_in = _mm_to_inches(w_mm), _mm_to_inches(h_mm)
    w_px, h_px = int(round(w_in * dpi)), int(round(h_in * dpi))
    if not portrait:
        w_px, h_px = h_px, w_px
    return w_px, h_px


# ---------------------------- helpers ----------------------------


def _ensure_realesrgan_exe(exe_path: Optional[str]) -> Path:
    path = exe_path or os.environ.get("REAL_ESRGAN_EXE", "")
    if not path:
        raise FileNotFoundError(
            "Real-ESRGAN not configured. Set REAL_ESRGAN_EXE or pass exe_path to process_exact()."
        )
    exe = Path(path)
    if not exe.exists() or not exe.is_file():
        raise FileNotFoundError(f"Real-ESRGAN executable not found: {exe}")
    return exe


def _detect_models_dir(exe: Path) -> Path:
    """
    Real-ESRGAN NCNN zips ship a 'models' dir next to the exe.
    We always point -m at that folder so there is no ambiguity.
    """
    mdir = exe.parent / "models"
    if not mdir.exists():
        raise FileNotFoundError(
            f"Models folder was not found next to the executable:\n{mdir}\n"
            "Make sure you extracted the official archive so that a "
            "'models' directory sits beside realesrgan-ncnn-vulkan.exe."
        )
    return mdir


def _run_realesrgan_single(
    exe: Path,
    models_dir: Path,
    inp: Path,
    outp: Path,
    model: str = "realesrgan-x4plus",
    tilesize: int = 256,
    fp16: bool = False,
) -> None:
    """
    One clean Real-ESRGAN NCNN invocation:
    - Always 4x upscale
    - Always passes -m <models_dir>
    - Forces GPU 0 with -g 0
    """

    # Clamp tile size defensively
    tilesize = max(64, min(tilesize, 512))

    cmd = [
        str(exe),
        "-i",
        str(inp),
        "-o",
        str(outp),
        "-n",
        model,
        "-s",
        "4",
        "-t",
        str(tilesize),
        "-f",
        "png",
        "-m",
        str(models_dir),
        "-g",
        "0",  # force NVIDIA (GPU 0)
    ]
    if fp16:
        # Only add -x if user explicitly requested FP16
        cmd.append("-x")

    log.info("Real-ESRGAN command: %s", " ".join(cmd))

    env = os.environ.copy()
    # Small nudge that also keeps things deterministic
    env.setdefault("CUDA_VISIBLE_DEVICES", "0")

    # Remove any stale output from previous runs
    try:
        if outp.exists():
            outp.unlink()
    except Exception as e:
        log.warning("Could not remove old NCNN output '%s': %s", outp, e)

    proc = subprocess.run(
        cmd,
        cwd=str(exe.parent),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    log.info("Real-ESRGAN output:\n%s", proc.stdout or "")

    if proc.returncode != 0:
        raise RuntimeError(
            f"Real-ESRGAN failed with exit code {proc.returncode}.\n"
            f"Command: {' '.join(cmd)}\n\nOutput:\n{proc.stdout or ''}"
        )

    if not outp.exists() or outp.stat().st_size == 0:
        raise RuntimeError(
            "Real-ESRGAN reported success but did not produce a valid output file."
        )

    # Sanity-check that the image is readable and non-empty
    Image.MAX_IMAGE_PIXELS = None
    with Image.open(outp) as im:
        w, h = im.size
    log.info("NCNN output size: %dx%d", w, h)
    if w <= 0 or h <= 0:
        raise RuntimeError("Real-ESRGAN produced an invalid image (zero dimension).")


def _tag_png_dpi(img_path: Path, dpi: int) -> None:
    """Re-save PNG with DPI metadata set."""
    Image.MAX_IMAGE_PIXELS = None
    with Image.open(img_path) as im:
        im.save(img_path, dpi=(dpi, dpi))


# ---------------------------- public API ----------------------------

ProgressCb = Optional[Callable[[int], None]]
PreviewCb = Optional[Callable[[str], None]]


def _emit_progress(cb: ProgressCb, value: int) -> None:
    if cb is not None:
        try:
            cb(int(max(0, min(100, value))))
        except Exception:
            # Avoid progress callbacks killing the pipeline
            log.warning("Progress callback raised an exception", exc_info=True)


def process_exact(
    input_path: str | Path,
    output_dir: str | Path,
    paper: str = DEFAULT_PAPER,
    dpi: int = DEFAULT_DPI,
    portrait: bool = True,
    exe_path: Optional[str] = None,
    model: str = "realesrgan-x4plus",
    tilesize: int = 256,
    fp16: bool = False,
    force_600dpi: bool = False,
    keep_native_if_larger: bool = False,
    progress_cb: ProgressCb = None,
    preview_cb: PreviewCb = None,
) -> Path:
    """
    High-level entry point used by the GUI.

    Steps:
    1. Compute target pixels from paper + DPI.
    2. Run a single Real-ESRGAN NCNN 4x upscale into a temp PNG.
    3. Emit preview callback with the NCNN 4x result.
    4. Resize WITH ASPECT RATIO PRESERVED:
         - scale to fit within paper size
         - centre on black canvas of exact A-size
    5. Tag DPI metadata.
    """

    banner("STARTING POSTER UPSCALE")
    _emit_progress(progress_cb, 0)

    if dpi == 600 and not force_600dpi:
        raise ValueError(
            "600 DPI is disabled by default. Tick 'Force 600 DPI (expert mode)' to allow it."
        )

    inp = Path(input_path)
    if not inp.exists():
        raise FileNotFoundError(f"Input image not found: {inp}")

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    exe = _ensure_realesrgan_exe(exe_path)
    models_dir = _detect_models_dir(exe)

    # Probe source dimensions
    Image.MAX_IMAGE_PIXELS = None
    with Image.open(inp) as probe:
        sw, sh = probe.size

    tw, th = target_pixels(paper, dpi, portrait=portrait)
    log.info("Target pixels: %d x %d @ %d DPI", tw, th, dpi)
    log.info("Source pixels: %d x %d", sw, sh)

    if keep_native_if_larger and sw >= tw and sh >= th:
        banner("SOURCE ALREADY >= TARGET — KEEPING NATIVE PIXELS")
        w_mm, h_mm = A_SIZES_MM[paper.lower()]
        out_path = out_dir / f"{inp.stem}__{w_mm}x{h_mm}mm_{dpi}dpi.png"
        Image.MAX_IMAGE_PIXELS = None
        with Image.open(inp) as im:
            im = im.convert("RGB")
            im.save(out_path, format="PNG", dpi=(dpi, dpi))
        _emit_progress(progress_cb, 100)
        banner("DONE (NATIVE)")
        log.info("Output: %s", out_path)
        return out_path

    _emit_progress(progress_cb, 5)

    # Workspace for NCNN output
    workdir = Path(tempfile.mkdtemp(prefix="poster_esr_"))
    ncnn_out = workdir / "esr_4x.png"

    try:
        banner("AI UPSCALE (SINGLE 4x PASS)")
        _emit_progress(progress_cb, 10)

        _run_realesrgan_single(
            exe=exe,
            models_dir=models_dir,
            inp=inp,
            outp=ncnn_out,
            model=model,
            tilesize=tilesize,
            fp16=fp16,
        )

        _emit_progress(progress_cb, 60)

        # Offer the raw NCNN 4x output as a preview if requested
        if preview_cb is not None:
            try:
                preview_copy = out_dir / f"{inp.stem}__ncnn_4x_preview.png"
                Image.MAX_IMAGE_PIXELS = None
                with Image.open(ncnn_out) as im:
                    im = im.convert("RGB")
                    im.save(preview_copy, format="PNG")
                preview_cb(str(preview_copy))
            except Exception:
                log.warning("Could not generate preview PNG", exc_info=True)

        _emit_progress(progress_cb, 70)

        banner("FINAL RESAMPLE TO EXACT SIZE (NO STRETCHING)")
        log.info("Final canvas will be %dx%d px", tw, th)

        w_mm, h_mm = A_SIZES_MM[paper.lower()]
        out_path = out_dir / f"{inp.stem}__{w_mm}x{h_mm}mm_{dpi}dpi.png"

        Image.MAX_IMAGE_PIXELS = None
        with Image.open(ncnn_out) as im:
            im = im.convert("RGB")
            src_w, src_h = im.size

            # Scale to FIT INSIDE the target while preserving aspect ratio
            scale = min(tw / src_w, th / src_h)
            new_w = max(1, int(round(src_w * scale)))
            new_h = max(1, int(round(src_h * scale)))
            log.info(
                "Resizing 4x NCNN output %dx%d -> %dx%d (scale %.3f)",
                src_w,
                src_h,
                new_w,
                new_h,
                scale,
            )

            resized = im.resize((new_w, new_h), resample=Image.LANCZOS)

            # Create black canvas and centre the resized image on it
            canvas = Image.new("RGB", (tw, th), color=(0, 0, 0))
            off_x = (tw - new_w) // 2
            off_y = (th - new_h) // 2
            canvas.paste(resized, (off_x, off_y))

            canvas.save(out_path, format="PNG")

        _emit_progress(progress_cb, 90)

        _tag_png_dpi(out_path, dpi)
        _emit_progress(progress_cb, 100)

        banner("DONE")
        log.info("Output: %s", out_path)
        return out_path

    finally:
        # Best-effort cleanup of temp directory
        try:
            for child in workdir.glob("*"):
                try:
                    child.unlink()
                except Exception:
                    pass
            workdir.rmdir()
        except Exception:
            log.warning("Could not clean temp dir %s", workdir)


# ---------------------------- CLI ----------------------------

if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(
        description="Poster AI Upscale (single 4x Real-ESRGAN pass + final resize with padding)."
    )
    ap.add_argument("-i", "--input", required=True, help="Path to source image")
    ap.add_argument("-o", "--outdir", required=True, help="Output directory")
    ap.add_argument("--paper", choices=list(A_SIZES_MM.keys()), default=DEFAULT_PAPER)
    ap.add_argument("--dpi", type=int, default=DEFAULT_DPI)
    og = ap.add_mutually_exclusive_group()
    og.add_argument("--portrait", action="store_true", default=True)
    og.add_argument("--landscape", action="store_true")
    ap.add_argument("--realesrgan", dest="exe_path", help="Path to realesrgan-ncnn-vulkan.exe")
    ap.add_argument("--model", default="realesrgan-x4plus")
    ap.add_argument("--tilesize", type=int, default=256)
    ap.add_argument("--fp16", action="store_true", help="Enable FP16 in NCNN exe")
    ap.add_argument("--force-600dpi", action="store_true", help="Allow 600 DPI (huge files!)")
    ap.add_argument(
        "--keep-native",
        dest="keep_native_if_larger",
        action="store_true",
        help="Keep source pixels if already larger than target",
    )
    args = ap.parse_args()

    portrait_flag = not args.landscape

    try:
        process_exact(
            input_path=args.input,
            output_dir=args.outdir,
            paper=args.paper,
            dpi=args.dpi,
            portrait=portrait_flag,
            exe_path=args.exe_path,
            model=args.model,
            tilesize=args.tilesize,
            fp16=args.fp16,
            force_600dpi=args.force_600dpi,
            keep_native_if_larger=args.keep_native_if_larger,
        )
    except Exception as e:  # pragma: no cover - CLI convenience
        log.error(str(e))
        sys.exit(1)
