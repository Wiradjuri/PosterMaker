# app/imaging/pipeline.py
# Purpose: True AI upscaling for poster print. No fallback resampling.
# Requires: realesrgan-ncnn-vulkan.exe (set REAL_ESRGAN_EXE or pass exe_path)

from __future__ import annotations

import os
import sys
import time
import shutil
import tempfile
import subprocess
from pathlib import Path
from typing import Tuple

from PIL import Image

# ---------------------------- logging ----------------------------
try:
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    log = logging.getLogger("poster-pipeline")
except Exception:
    class _L:
        def info(self, m): print(time.strftime("%Y-%m-%d %H:%M:%S"), "| INFO |", m)
        def warning(self, m): print(time.strftime("%Y-%m-%d %H:%M:%S"), "| WARNING |", m)
        def error(self, m): print(time.strftime("%Y-%m-%d %H:%M:%S"), "| ERROR |", m)
    log = _L()

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

# ---------------------------- helpers ----------------------------
def _mm_to_inches(mm: float) -> float:
    return mm / 25.4

def target_pixels(paper: str = DEFAULT_PAPER, dpi: int = DEFAULT_DPI, portrait: bool = True) -> Tuple[int, int]:
    if paper.lower() not in A_SIZES_MM:
        raise ValueError(f"Unsupported paper size: {paper}")
    w_mm, h_mm = A_SIZES_MM[paper.lower()]
    w_in, h_in = _mm_to_inches(w_mm), _mm_to_inches(h_mm)
    w_px, h_px = int(round(w_in * dpi)), int(round(h_in * dpi))
    if not portrait:
        w_px, h_px = h_px, w_px
    return w_px, h_px

def _ensure_realesrgan_exe(exe_path: str | None) -> Path:
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
    # Most releases ship models under <exe_dir>/models
    mdir = exe.parent / "models"
    if not mdir.exists():
        raise FileNotFoundError(
            f"Models folder was not found next to the executable:\n{mdir}\n"
            f"Re-extract the official zip so that a 'models' directory sits beside the exe, "
            f"containing .param/.bin files (e.g., realesrgan-x4plus.param/bin)."
        )
    return mdir

def _run_realesrgan(
    exe: Path,
    inp: Path,
    outp: Path,
    model: str = "realesrgan-x4plus",
    scale: int = 4,
    tilesize: int = 512,
    fp16: bool = True,
) -> None:
    """
    Calls the portable NCNN build. This function raises on failure.
    We explicitly pass the models directory (-m) and set cwd=exe.parent
    so the binary reliably finds its assets.
    """
    models_dir = _detect_models_dir(exe)
    cmd = [
        str(exe),
        "-i", str(inp),
        "-o", str(outp),
        "-n", model,
        "-s", str(scale),
        "-t", str(tilesize),
        "-f", "png",
        "-m", str(models_dir),
    ]
    if fp16:
        cmd.append("-x")  # enable FP16

    # Log the full command (models dir visible) for troubleshooting
    log.info("Real-ESRGAN: %s", " ".join(cmd))

    proc = subprocess.run(
        cmd,
        cwd=str(exe.parent),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    if proc.returncode != 0:
        hint = ""
        out = proc.stdout or ""
        # If output mentions typical missing-model errors, append a helpful hint
        if any(token in out for token in (".param", ".bin", "wfopen")):
            hint = (
                "\n\nLikely cause: missing model files. Ensure the 'models' folder next to the exe "
                "contains the required '*.param' and '*.bin' for the selected model "
                f"('{model}')."
            )
        raise RuntimeError(
            f"Real-ESRGAN failed (code {proc.returncode}). Output:\n{out}{hint}"
        )

    if not outp.exists() or outp.stat().st_size == 0:
        raise RuntimeError("Real-ESRGAN reported success but output file was not created.")

def _ai_upscale_exact(
    src_img: Path,
    dst_img: Path,
    target_w: int,
    target_h: int,
    exe: Path,
    model: str = "realesrgan-x4plus",
    tilesize: int = 512,
    fp16: bool = True,
) -> None:
    """
    Repeated 4x passes (and optional 2x) until exceeding target, then tiny LANCZOS to exact size.
    """
    workdir = Path(tempfile.mkdtemp(prefix="esr_work_"))
    try:
        Image.MAX_IMAGE_PIXELS = None

        with Image.open(src_img) as im:
            src_w, src_h = im.size

        log.info(f"Source: {src_img.name} ({src_w}x{src_h}) -> Target: {target_w}x{target_h}")
        need_scale = max(target_w / src_w, target_h / src_h)
        log.info(f"Initial scale needed: ×{need_scale:.2f}")
        # Log the concrete Real-ESRGAN command that would be used in 4x passes (models dir visible)
        try:
            models_dir = _detect_models_dir(exe)
            cmd_preview = [
                str(exe), "-i", str(src_img), "-o", str(Path(tempfile.gettempdir()) / 'esr_preview_out.png'),
                "-n", model, "-s", "4", "-t", str(tilesize), "-f", "png", "-m", str(models_dir)
            ]
            if fp16:
                cmd_preview.append("-x")
            log.info("Real-ESRGAN (command): %s", " ".join(cmd_preview))
        except Exception:
            # models folder missing will be raised by _run_realesrgan/_detect_models_dir later
            pass
        cur_path = src_img

        pass_idx = 0
        while need_scale > 3.2:
            pass_idx += 1
            banner(f"AI UPSCALE PASS {pass_idx} (4x)")
            out_path = workdir / f"pass{pass_idx}_4x.png"
            _run_realesrgan(exe, cur_path, out_path, model=model, scale=4, tilesize=tilesize, fp16=fp16)
            cur_path = out_path
            with Image.open(cur_path) as im:
                cur_w, cur_h = im.size
            need_scale = max(target_w / cur_w, target_h / cur_h)
            log.info(f"Now at {cur_w}x{cur_h}; remaining scale ≈ {need_scale:.2f}")

        if need_scale > 1.6:
            pass_idx += 1
            banner(f"AI UPSCALE PASS {pass_idx} (2x)")
            out_path = workdir / f"pass{pass_idx}_2x.png"
            _run_realesrgan(exe, cur_path, out_path, model=model, scale=2, tilesize=tilesize, fp16=fp16)
            cur_path = out_path
            with Image.open(cur_path) as im:
                cur_w, cur_h = im.size
            need_scale = max(target_w / cur_w, target_h / cur_h)
            log.info(f"Now at {cur_w}x{cur_h}; remaining scale ≈ {need_scale:.2f}")

        banner("FINAL RESAMPLE TO EXACT SIZE")
        log.info(f"Final output will be {target_w}×{target_h} px")
        with Image.open(cur_path) as im:
            final = im.resize((target_w, target_h), Image.Resampling.LANCZOS)
            final.save(dst_img)
        log.info(f"Saved exact-size image: {dst_img} ({target_w}x{target_h})")

    finally:
        try:
            shutil.rmtree(workdir, ignore_errors=True)
        except Exception as e:
            log.warning(f"Could not clean temp dir: {e}")

def _tag_png_dpi(img_path: Path, dpi: int) -> None:
    with Image.open(img_path) as im:
        im.save(img_path, dpi=(dpi, dpi))

# ---------------------------- public API ----------------------------
def process_exact(
    input_path: str | Path,
    output_dir: str | Path,
    paper: str = DEFAULT_PAPER,
    dpi: int = DEFAULT_DPI,
    portrait: bool = True,
    exe_path: str | None = None,
    model: str = "realesrgan-x4plus",
    tilesize: int = 512,
    fp16: bool = True,
    force_600dpi: bool = False,
    keep_native_if_larger: bool = False,
) -> Path:
    """
    AI upscale to exact paper@dpi pixels, then save PNG tagged with DPI.
    If keep_native_if_larger is True and the source image is already larger
    than the target in both dimensions, we keep native pixels and only tag DPI.
    """
    if dpi == 600 and not force_600dpi:
        raise ValueError("600 DPI is disabled by default. Tick 'Force 600 DPI (expert)' to allow it.")

    inp = Path(input_path)
    if not inp.exists():
        raise FileNotFoundError(f"Input image not found: {inp}")

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    exe = _ensure_realesrgan_exe(exe_path)

    tw, th = target_pixels(paper, dpi, portrait=portrait)
    with Image.open(inp) as probe:
        sw, sh = probe.size

    log.info(f"Target pixels: {tw} x {th} @ {dpi} DPI")
    log.info(f"Source pixels: {sw} x {sh}")
    # Extra log: initial scale preview and a Real-ESRGAN command (models dir visible)
    try:
        need_scale_preview = max(tw / sw, th / sh)
        log.info(f"Initial scale factor (preview): ×{need_scale_preview:.2f}")
        models_dir = _detect_models_dir(exe)
        preview_cmd = [
            str(exe), "-i", str(inp), "-o", str(out_dir / (inp.stem + '__preview.png')),
            "-n", model, "-s", "4", "-t", str(tilesize), "-f", "png", "-m", str(models_dir)
        ]
        if fp16:
            preview_cmd.append("-x")
        log.info("Real-ESRGAN (preview): %s", " ".join(preview_cmd))
    except Exception:
        # Do not fail here; keep original behavior where missing models raise later
        pass

    wmm, hmm = A_SIZES_MM[paper.lower()]
    out_path = out_dir / f"{inp.stem}__{wmm}x{hmm}mm_{dpi}dpi.png"

    if keep_native_if_larger and sw >= tw and sh >= th:
        banner("SOURCE ALREADY ABOVE TARGET — KEEPING NATIVE PIXELS")
        shutil.copyfile(inp, out_path)
        _tag_png_dpi(out_path, dpi)
        log.info(f"✅ Kept native {sw}×{sh} pixels (≥ target {tw}×{th}); set DPI tag to {dpi}")
        banner("DONE")
        log.info(f"Output: {out_path}")
        return out_path

    banner("AI UPSCALING (NO FALLBACKS)")
    _ai_upscale_exact(
        src_img=inp,
        dst_img=out_path,
        target_w=tw,
        target_h=th,
        exe=exe,
        model=model,
        tilesize=tilesize,
        fp16=fp16,
    )

    _tag_png_dpi(out_path, dpi)
    banner("DONE")
    log.info(f"Output: {out_path}")
    return out_path

# ---------------------------- CLI ----------------------------
if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Poster AI Upscale (enforces Real-ESRGAN, no fallbacks).")
    ap.add_argument("-i", "--input", required=True, help="Path to source image")
    ap.add_argument("-o", "--outdir", required=True, help="Output directory")
    ap.add_argument("--paper", choices=list(A_SIZES_MM.keys()), default=DEFAULT_PAPER)
    ap.add_argument("--dpi", type=int, default=DEFAULT_DPI)
    og = ap.add_mutually_exclusive_group()
    og.add_argument("--portrait", action="store_true", default=True)
    og.add_argument("--landscape", action="store_true")
    ap.add_argument("--realesrgan", dest="exe_path", help="Path to realesrgan-ncnn-vulkan.exe")
    ap.add_argument("--model", default="realesrgan-x4plus")
    ap.add_argument("--tilesize", type=int, default=512)
    ap.add_argument("--no-fp16", action="store_true", help="Disable FP16 in NCNN exe")
    ap.add_argument("--force-600dpi", action="store_true", help="Allow 600 DPI (use with caution)")
    ap.add_argument("--keep-native", dest="keep_native_if_larger", action="store_true",
                    help="Keep source pixels if already larger than target")
    args = ap.parse_args()

    portrait = not args.landscape
    try:
        process_exact(
            input_path=args.input,
            output_dir=args.outdir,
            paper=args.paper,
            dpi=args.dpi,
            portrait=portrait,
            exe_path=args.exe_path,
            model=args.model,
            tilesize=args.tilesize,
            fp16=(not args.no_fp16),
            force_600dpi=args.force_600dpi,
            keep_native_if_larger=args.keep_native_if_larger,
        )
    except Exception as e:
        log.error(str(e))
        sys.exit(1)
