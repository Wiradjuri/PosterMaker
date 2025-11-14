# PosterMaker — Ultra‑High‑Definition Poster Export (Real‑ESRGAN NCNN)

PosterMaker transforms ordinary images into print‑ready, ultra‑high‑definition posters using the Real‑ESRGAN NCNN upscaler. It targets A‑series paper (A1, A2, A3) and provides precise DPI control via a modern PySide6 GUI.

This README explains what the app does, how the processing pipeline works, and how to run and troubleshoot it.

---

## Key features

- True AI upscaling using the Real‑ESRGAN NCNN backend (no non‑AI fallback for the upscale step)
- A‑series paper sizes (A1/A2/A3) with configurable DPI (150–600)
- Multi‑pass upscaling pipeline (4× & 2× passes plus high‑quality final resample)
- Robust retry and validation logic to avoid scrambled or black outputs
- Tile size safety cap and FP16 handling to reduce GPU/driver issues
- Responsive PySide6 GUI with thumbnail preview, smooth progress and logs

---

## How the upscaling pipeline works (technical overview)

The processing is intentionally strict and defensive to avoid the common pitfalls of NCNN upscaling (scrambled tiles, black outputs, VRAM crashes):

1. Input validation
   - Verifies input file exists and the output folder is writable.
   - Validates the Real‑ESRGAN executable and the `models/` folder (the chosen model must have both `.param` and `.bin`).

2. Target calculation
   - Computes the exact pixel dimensions for the chosen paper size and DPI.

3. Multi‑pass AI upscaling
   - The pipeline performs zero or more NCNN passes, then a final Lanczos resample to the exact target size.
   - Pass logic:
     - If total scale needed > 3.2×: do a 4× pass (mapped to 5–60% progress).
     - If remaining scale > 1.6×: do a 2× pass (mapped to 60–85% progress).
     - Finally, perform a high‑quality Lanczos resize to the exact target (mapped to 85–95%), and then write DPI metadata (95–100%).

4. NCNN invocation and safety
   - The app always passes an explicit `-m <models_dir>` to NCNN so the correct model files are used.
   - We force NVIDIA GPU usage with `-g 0` (and set `CUDA_VISIBLE_DEVICES=0`) to avoid accidental use of Intel integrated GPUs.
   - Tile size is capped to 512 px (minimum 64 px). This prevents many VRAM OOMs and scrambled tile artefacts.
   - FP16 is used by default for performance but the pipeline will retry with FP32 if FP16 produces invalid output or the image is very dark.

5. Robustness and validation
   - Each NCNN pass runs with retry logic (up to 3 attempts). If a pass produces a 0‑byte or corrupted PNG, the pipeline retries with safer settings (smaller tiles, FP32).
   - After each pass the output PNG is validated (size, openability, and non‑all‑black content).
   - Temporary files are cleaned up even on error.

6. Progress reporting
   - The pipeline emits predictable progress ranges so the GUI can animate smoothly:
     - Preview stage: 0–5%
     - Upscale 1 (4×): 5–60%
     - Upscale 2 (2×): 60–85%
     - Final resample: 85–95%
     - DPI tagging / save: 95–100%

7. Final save
   - The final image is converted to RGB (if needed) and saved as a PNG with DPI metadata.

This design minimizes the chance of scrambled outputs, black images, corrupted files, or GUI freezes.

---

## Running the app

Prerequisites:

- Windows 10/11 (or another OS for which you have an NCNN build)
- Python 3.10+
- NVIDIA GPU with up‑to‑date drivers (recommended)
- Real‑ESRGAN NCNN executable (Windows ZIP distribution) with a `models/` folder

Quickstart:

1. Install dependencies

```powershell
py -3.10 -m venv .venv
. .venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

1. Place the NCNN executable and models

Extract the Real‑ESRGAN NCNN release and ensure the layout looks like:

```text
C:\tools\realesrgan-ncnn-vulkan.exe
C:\tools\models\realesrgan-x4plus.param
C:\tools\models\realesrgan-x4plus.bin
```

1. Start the GUI

```powershell
python -m app.ui_main_window
```

In the app: choose the input image, an output folder, set the `Executable` path to your `realesrgan-ncnn-vulkan.exe`, choose model and DPI, then click `Process`.

---

## Troubleshooting

Common problems and solutions:

- Black or scrambled output
  - Try disabling FP16 in the app and reduce tile size (256). The pipeline will automatically retry with FP32 when needed.
- Models not found
  - Ensure the `models/` folder sits next to the `realesrgan-ncnn-vulkan.exe` and contains both `.param` and `.bin` files for the chosen model.
- Wrong GPU used (Intel instead of NVIDIA)
  - The pipeline forces `-g 0` and sets `CUDA_VISIBLE_DEVICES=0`. Make sure your NVIDIA drivers are installed and that the NVIDIA GPU is visible to the system.
- Memory / VRAM crashes
  - Reduce DPI or choose a smaller paper (A2/A3). Lower the tile size if necessary. The app caps tile size at 512 by default.
- ImportError: No module named `app`
  - Run from the project root and use the `-m` switch: `python -m app.ui_main_window`.

If problems persist, check the log panel in the GUI for detailed messages and raise an issue with the included log output.

---

## Project structure (short)

```text
PosterMaker/
├─ app/
│  ├─ imaging/pipeline.py     # NCNN orchestration + robust retry and validation
│  ├─ ui_main_window.py       # PySide6 GUI, worker thread and smooth progress
│  └─ gui.py                  # App entry point
├─ output/                    # Generated images
├─ requirements.txt
├─ README.md
└─ LICENSE
```

---

## Contributing

Contributions are welcome. Please open issues for bugs and feature requests. When submitting PRs, include reproducible steps and small focused changes.

---

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.
