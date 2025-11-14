# app/imaging/pipeline.py
# Purpose: True AI upscaling for poster print (Real-ESRGAN NCNN).
# FIXED VERSION - Addresses all critical bugs:
# - Prevents Real-ESRGAN NCNN scrambled/broken output
# - Fixes black output with retry logic
# - Forces NVIDIA GPU usage (-g 0)
# - Caps tile size to prevent VRAM crashes
# - Proper progress callback emission
# - Enhanced error handling and PNG validation

from __future__ import annotations

import os
import sys
import time
import shutil
import tempfile
import subprocess
from pathlib import Path
from typing import Tuple, Callable, Optional

from PIL import Image, ImageStat

# Pillow compatibility for resampling constant (LANCZOS moved in newer versions)
try:
    RESAMPLE_LANCZOS = Image.Resampling.LANCZOS  # type: ignore[attr-defined]
except Exception:
    RESAMPLE_LANCZOS = getattr(Image, "LANCZOS", getattr(Image, "BICUBIC", 1))

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
    if paper.lower() not in A_SIZES_MM:
        raise ValueError(f"Unsupported paper size: {paper}")
    w_mm, h_mm = A_SIZES_MM[paper.lower()]
    w_in, h_in = _mm_to_inches(w_mm), _mm_to_inches(h_mm)
    w_px, h_px = int(round(w_in * dpi)), int(round(h_in * dpi))
    if not portrait:
        w_px, h_px = h_px, w_px
    return w_px, h_px


# ---------------------------- NCNN helpers ----------------------------
def _ensure_realesrgan_exe(path: Optional[str]) -> Path:
    if not path:
        raise FileNotFoundError(
            "No path provided for realesrgan-ncnn-vulkan.exe. "
            "Set it in the GUI or pass exe_path to process_exact()."
        )
    exe = Path(path)
    if not exe.exists() or not exe.is_file():
        raise FileNotFoundError(f"Real-ESRGAN executable not found: {exe}")
    return exe


def _detect_models_dir(exe: Path) -> Path:
    # Expect models in <exe_dir>/models
    mdir = exe.parent / "models"
    if not mdir.exists():
        raise FileNotFoundError(
            f"Models folder was not found next to the executable:\n{mdir}\n"
            f"Ensure a 'models' directory sits beside the exe, containing "
            f"*.param and *.bin files (e.g., realesrgan-x4plus.param/bin)."
        )
    return mdir


def _validate_model_exists(exe: Path, model: str) -> None:
    """
    Ensure that model.param and model.bin exist in <exe.parent>/models.
    """
    mdir = exe.parent / "models"
    log.info("Looking for models in: %s", mdir)
    try:
        files = sorted([p.name for p in mdir.iterdir() if p.is_file()])
    except Exception:
        files = []
    log.info("Discovered model files: %s", ", ".join(files) if files else "(none)")

    p_param = mdir / f"{model}.param"
    p_bin = mdir / f"{model}.bin"
    if not p_param.exists() or not p_bin.exists():
        raise FileNotFoundError(
            f"Required model files for '{model}' not found in {mdir}:\n"
            f"Missing: {p_param if not p_param.exists() else ''} {p_bin if not p_bin.exists() else ''}\n"
            f"Ensure you have installed the correct model files (e.g., {model}.param and {model}.bin) into the models directory next to the executable."
        )


def _emit_progress(cb: Optional[Callable[[int], None]], value: int) -> None:
    """Safely emit progress callback, ensuring value is between 0-100"""
    if cb is None:
        return
    try:
        # Clamp progress to valid range
        clamped_value = max(0, min(100, int(value)))
        cb(clamped_value)
    except Exception as e:
        log.warning(f"Failed to emit progress {value}: {e}")


def _emit_preview(cb: Optional[Callable[[str], None]], path: Path) -> None:
    if cb is None:
        return
    try:
        cb(str(path))
    except Exception as e:
        log.warning(f"Failed to emit preview {path}: {e}")


def _validate_png_output(path: Path) -> bool:
    """
    CRITICAL: Validate that PNG output is not corrupted or empty.
    Returns True if valid, False otherwise.
    """
    try:
        if not path.exists():
            log.error(f"Output PNG does not exist: {path}")
            return False
            
        if path.stat().st_size == 0:
            log.error(f"Output PNG is 0 bytes: {path}")
            return False
            
        # Try to open and verify the image
        with Image.open(path) as im:
            # Verify it has valid dimensions
            if im.width <= 0 or im.height <= 0:
                log.error(f"PNG has invalid dimensions: {im.width}x{im.height}")
                return False
                
            # Quick pixel sanity check - ensure not entirely black/transparent
            try:
                rgb_im = im.convert("RGB")
                bbox = rgb_im.getbbox()
                if bbox is None:
                    log.error(f"PNG appears to be entirely black/transparent")
                    return False
            except Exception as e:
                log.warning(f"Could not verify PNG content: {e}")
                
        log.info(f"PNG validation passed: {path}")
        return True
        
    except Exception as e:
        log.error(f"PNG validation failed for {path}: {e}")
        return False


def _run_ncnn_with_retry(
    exe: Path,
    inp: Path,
    outp: Path,
    model: str,
    scale: int,
    tilesize: int,
    fp16: bool,
    progress_cb: Optional[Callable[[int], None]] = None,
    base_pct: int = 0,
    step_pct: int = 0,
    max_retries: int = 3,
) -> None:
    """
    CRITICAL FIX: Run NCNN with retry logic to handle scrambled/black output.
    """
    # CRITICAL: Cap tile size to prevent VRAM crashes and scrambling
    safe_tile = max(64, min(tilesize, 512))
    if safe_tile != tilesize:
        log.warning(
            "Tile size clamped from %d to %d to prevent GPU issues",
            tilesize, safe_tile
        )

    for attempt in range(max_retries):
        try:
            log.info(f"NCNN attempt {attempt + 1}/{max_retries}")
            
            # Remove any existing output file
            if outp.exists():
                outp.unlink()
                
            # CRITICAL: Always force NVIDIA GPU with -g 0
            cmd = [
                str(exe),
                "-i", str(inp),
                "-o", str(outp),
                "-n", model,
                "-s", str(scale),
                "-t", str(safe_tile),
                "-f", "png",
                "-g", "0",  # CRITICAL: Force NVIDIA GPU (never auto-select)
            ]
            
            # CRITICAL: Always specify explicit models directory
            models_dir = exe.parent / "models"
            cmd.extend(["-m", str(models_dir)])
            
            # Add FP16 flag if requested and not retrying due to FP16 issues
            use_fp16 = fp16 and attempt == 0  # Only use FP16 on first attempt
            if use_fp16:
                cmd.append("-x")
                
            log.info("Real-ESRGAN command: %s", " ".join(cmd))

            # Start process with proper environment
            env = os.environ.copy()
            # Ensure NVIDIA GPU is preferred
            env['CUDA_VISIBLE_DEVICES'] = '0'
            
            proc = subprocess.Popen(
                cmd,
                cwd=str(exe.parent),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=env
            )

            out_lines = []
            last_progress = base_pct
            
            try:
                # Emit initial progress
                if step_pct > 0:
                    _emit_progress(progress_cb, base_pct + 1)

                if proc.stdout is not None:
                    for raw in proc.stdout:
                        line = raw.rstrip()
                        out_lines.append(line)
                        log.info(f"NCNN: {line}")

                        # Extract progress and emit smooth updates
                        try:
                            import re
                            m = re.search(r"(\d{1,3})\s*%", line)
                            if m:
                                pct = int(m.group(1))
                                if step_pct > 0:
                                    # Map NCNN progress to our progress range
                                    mapped = base_pct + int(round((pct / 100.0) * step_pct))
                                    mapped = max(base_pct, min(base_pct + step_pct, mapped))
                                    # Only emit if progress actually increased
                                    if mapped > last_progress:
                                        _emit_progress(progress_cb, mapped)
                                        last_progress = mapped
                        except Exception:
                            pass

                ret = proc.wait()
                
            except Exception:
                proc.kill()
                proc.wait()
                raise

            stdout_text = "\n".join(out_lines)
            
            # Check return code
            if ret != 0:
                error_msg = f"Real-ESRGAN failed (code {ret}). Output:\n{stdout_text}"
                if attempt < max_retries - 1:
                    log.warning(f"{error_msg} - Retrying...")
                    continue
                else:
                    raise RuntimeError(error_msg)

            # CRITICAL: Validate output PNG is not corrupted
            if not _validate_png_output(outp):
                error_msg = f"NCNN produced invalid/corrupted PNG on attempt {attempt + 1}"
                if attempt < max_retries - 1:
                    log.warning(f"{error_msg} - Retrying with different settings...")
                    # On retry, disable FP16 and try smaller tile size
                    safe_tile = max(64, safe_tile // 2)
                    continue
                else:
                    raise RuntimeError(f"{error_msg} after {max_retries} attempts")

            # Success! Emit final progress for this pass
            if step_pct > 0:
                _emit_progress(progress_cb, base_pct + step_pct)
                
            log.info(f"NCNN pass successful on attempt {attempt + 1}")
            return
            
        except Exception as e:
            if attempt < max_retries - 1:
                log.warning(f"NCNN attempt {attempt + 1} failed: {e} - Retrying...")
                # Wait a bit before retry
                time.sleep(1)
            else:
                log.error(f"All NCNN attempts failed. Last error: {e}")
                raise


def _ai_pass(
    exe: Path,
    cur_img: Path,
    out_img: Path,
    model: str,
    scale: int,
    tilesize: int,
    fp16: bool,
    progress_cb: Optional[Callable[[int], None]] = None,
    preview_cb: Optional[Callable[[str], None]] = None,
    base_pct: int = 0,
    step_pct: int = 0,
) -> Path:
    """
    FIXED: One NCNN AI pass with proper retry logic and validation.
    """
    log.info(f"Starting AI pass: scale={scale}x, tile={tilesize}, fp16={fp16}")
    
    # Use retry logic to handle scrambling/corruption
    _run_ncnn_with_retry(
        exe,
        cur_img,
        out_img,
        model=model,
        scale=scale,
        tilesize=tilesize,
        fp16=fp16,
        progress_cb=progress_cb,
        base_pct=base_pct,
        step_pct=step_pct,
    )

    # Emit preview after successful completion
    _emit_preview(preview_cb, out_img)
    
    # Log final dimensions for verification
    try:
        with Image.open(out_img) as im_check:
            log.info(f"AI pass output: {im_check.width}x{im_check.height} pixels")
    except Exception as e:
        log.warning(f"Could not verify output dimensions: {e}")
    
    return out_img


# ---------------------------- public API ----------------------------
def process_exact(
    input_path: str | Path,
    output_dir: str | Path,
    paper: str = DEFAULT_PAPER,
    dpi: int = DEFAULT_DPI,
    portrait: bool = True,
    exe_path: Optional[str] = None,
    model: str = "realesrgan-x4plus",
    tilesize: int = 512,
    fp16: bool = True,
    force_600dpi: bool = False,
    keep_native_if_larger: bool = False,
    progress_cb: Optional[Callable[[int], None]] = None,
    preview_cb: Optional[Callable[[str], None]] = None,
) -> Path:
    """
    FIXED: AI upscale using Real-ESRGAN NCNN with proper error handling.
    
    PROGRESS ALLOCATION (FIXED):
    - Preview: 0-5%
    - First 4x pass: 5-60% 
    - Second 2x pass: 60-85%
    - Final resize: 85-95%
    - DPI tagging: 95-100%
    """

    # Backwards compatibility check
    if not isinstance(output_dir, (str, Path)) and hasattr(output_dir, "width_mm"):
        result = process_and_save(input_path, None, output_dir)
        return Image.open(result)

    # Validation
    if dpi == 600 and not force_600dpi:
        raise ValueError("600 DPI is disabled by default. Enable 'Force 600 DPI' to allow it.")

    src = Path(input_path)
    if not src.exists():
        raise FileNotFoundError(f"Input image not found: {src}")

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # CRITICAL: Validate Real-ESRGAN setup
    exe = _ensure_realesrgan_exe(exe_path)
    models_dir = _detect_models_dir(exe)
    _validate_model_exists(exe, model)

    # CRITICAL: Cap tile size to prevent VRAM crashes  
    tilesize = max(64, min(tilesize, 512))
    log.info(f"Using tile size: {tilesize} (capped to prevent VRAM issues)")

    # Calculate target dimensions
    tw, th = target_pixels(paper, dpi, portrait)
    with Image.open(src) as im_src:
        sw, sh = im_src.size

    log.info(f"Target: {tw}x{th} @ {dpi}DPI, Source: {sw}x{sh}")

    # Derive output filename
    wmm, hmm = A_SIZES_MM[paper.lower()]
    out_path = out_dir / f"{src.stem}__{wmm}x{hmm}mm_{dpi}dpi.png"

    # FIXED: Progress allocation starts
    _emit_progress(progress_cb, 0)

    # Keep native if already large enough
    if keep_native_if_larger and sw >= tw and sh >= th:
        banner("SOURCE ALREADY LARGE — KEEPING NATIVE PIXELS")
        _emit_progress(progress_cb, 50)
        
        shutil.copyfile(src, out_path)
        with Image.open(out_path) as im:
            im.save(out_path, dpi=(dpi, dpi))
            
        _emit_preview(preview_cb, out_path)
        _emit_progress(progress_cb, 100)
        
        log.info(f"Output: {out_path}")
        return out_path

    banner("AI UPSCALING (Real-ESRGAN NCNN)")

    # Create temporary work directory
    workdir = Path(tempfile.mkdtemp(prefix="esr_work_"))
    try:
        Image.MAX_IMAGE_PIXELS = None  # Allow very large images

        # Calculate total scale needed
        need_scale = max(tw / sw, th / sh)
        log.info(f"Total scale factor needed: ×{need_scale:.2f}")

        cur = src
        _emit_progress(progress_cb, 5)  # Preview stage complete

        # FIXED: Multi-pass logic with proper progress allocation
        # Pass 1: 4x if we need > 3.2x scale
        if need_scale > 3.2:
            banner("AI UPSCALE PASS 1 (4x)")
            out_p1 = workdir / f"pass1_4x_{int(time.time())}.png"
            
            cur = _ai_pass(
                exe,
                cur_img=cur,
                out_img=out_p1,
                model=model,
                scale=4,
                tilesize=tilesize,
                fp16=fp16,
                progress_cb=progress_cb,
                preview_cb=preview_cb,
                base_pct=5,   # Start at 5%
                step_pct=55,  # Take 55% (5% to 60%)
            )
            
            # Verify pass 1 results
            with Image.open(cur) as im_cur:
                sw, sh = im_cur.size
            need_scale = max(tw / sw, th / sh)
            log.info(f"After pass 1: {sw}x{sh}, remaining scale ≈ ×{need_scale:.2f}")

        # Pass 2: 2x if we still need > 1.6x scale
        if need_scale > 1.6:
            banner("AI UPSCALE PASS 2 (2x)")
            out_p2 = workdir / f"pass2_2x_{int(time.time())}.png"
            
            cur = _ai_pass(
                exe,
                cur_img=cur,
                out_img=out_p2,
                model=model,
                scale=2,
                tilesize=tilesize,
                fp16=fp16,
                progress_cb=progress_cb,
                preview_cb=preview_cb,
                base_pct=60,  # Start at 60%
                step_pct=25,  # Take 25% (60% to 85%)
            )
            
            # Verify pass 2 results  
            with Image.open(cur) as im_cur:
                sw, sh = im_cur.size
            need_scale = max(tw / sw, th / sh)
            log.info(f"After pass 2: {sw}x{sh}, remaining scale ≈ ×{need_scale:.2f}")

        # FIXED: Final exact-size resample with progress
        banner("FINAL RESAMPLE TO EXACT SIZE")
        _emit_progress(progress_cb, 85)
        
        log.info(f"Final target: {tw}×{th} px")

        with Image.open(cur) as im_final:
            # Ensure proper color mode
            if im_final.mode != "RGB":
                im_final = im_final.convert("RGB")
                
            # High-quality resize
            im_final = im_final.resize((tw, th), resample=RESAMPLE_LANCZOS)
            
            _emit_progress(progress_cb, 95)
            
            # Save with DPI metadata
            im_final.save(out_path, format="PNG", dpi=(dpi, dpi))

        # CRITICAL: Validate final output
        if not _validate_png_output(out_path):
            raise RuntimeError("Final output PNG is corrupted or invalid")

        _emit_preview(preview_cb, out_path)
        _emit_progress(progress_cb, 100)
        
        banner("SUCCESS")
        log.info(f"Output: {out_path}")
        return out_path

    finally:
        # Clean up temporary files
        try:
            shutil.rmtree(workdir, ignore_errors=True)
        except Exception as e:
            log.warning(f"Could not clean temp dir: {e}")


def process_and_save(input_path: str | Path, output_path: str | Path, settings, *,
                     exe_path: Optional[str] = None,
                     model: str = "realesrgan-x4plus",
                     tilesize: int = 512,
                     fp16: bool = True,
                     force_600dpi: bool = False,
                     keep_native_if_larger: bool = False,
                     progress_cb: Optional[Callable[[int], None]] = None,
                     preview_cb: Optional[Callable[[str], None]] = None,
                     ) -> Path:
    """
    Compatibility wrapper for older code paths that pass a RunSettings object.
    """
    # Infer paper key from settings
    w = float(getattr(settings, "width_mm", 0))
    h = float(getattr(settings, "height_mm", 0))
    paper_key = None
    for k, (mw, mh) in A_SIZES_MM.items():
        if (abs(mw - w) < 1e-6 and abs(mh - h) < 1e-6) or (abs(mw - h) < 1e-6 and abs(mh - w) < 1e-6):
            paper_key = k
            break
            
    if paper_key is None:
        # Support arbitrary paper sizes with fallback to Lanczos
        tw = int(round((w / 25.4) * settings.dpi))
        th = int(round((h / 25.4) * settings.dpi))
        out_dir = Path(settings.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{Path(input_path).stem}__{int(w)}x{int(h)}mm_{settings.dpi}dpi.png"
        
        with Image.open(input_path) as im_in:
            im_out = im_in.convert("RGB")
            im_out = im_out.resize((tw, th), resample=RESAMPLE_LANCZOS)
            im_out.save(out_path, format="PNG", dpi=(settings.dpi, settings.dpi))
        return out_path

    # Default exe path fallback
    if exe_path is None:
        fallback = Path(r"C:\tools\realesrgan-ncnn-vulkan.exe")
        if fallback.exists():
            exe_path = str(fallback)

    return process_exact(
        input_path=input_path,
        output_dir=Path(output_path).parent if Path(output_path).is_file() else output_path,
        paper=paper_key,
        dpi=int(getattr(settings, "dpi", DEFAULT_DPI)),
        portrait=(w <= h),
        exe_path=exe_path,
        model=model,
        tilesize=tilesize,
        fp16=fp16,
        force_600dpi=force_600dpi,
        keep_native_if_larger=keep_native_if_larger,
        progress_cb=progress_cb,
        preview_cb=preview_cb,
    )


# ---------------------------- CLI helper ----------------------------
if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Poster AI Upscale (Real-ESRGAN NCNN).")
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
    ap.add_argument("--no-fp16", action="store_true", help="Disable FP16 in NCNN")
    ap.add_argument("--force-600dpi", action="store_true", help="Allow 600 DPI (use with caution)")
    ap.add_argument("--keep-native", dest="keep_native_if_larger", action="store_true",
                    help="Keep source pixels if already larger than target")

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
            fp16=(not args.no_fp16),
            force_600dpi=args.force_600dpi,
            keep_native_if_larger=args.keep_native_if_larger,
        )
    except Exception as e:
        log.error(str(e))
        sys.exit(1)