# PosterMaker — Ultra-High-Definition Poster Export (Real-ESRGAN NCNN)

PosterMaker transforms regular images into **print-ready, ultra-high-definition posters** using the Real-ESRGAN NCNN GPU upscaler. It focuses on A-series paper sizes (A1/A2/A3) with full DPI control and a sleek PySide6 GUI.

---

## 🌈 Features

* ✨ **True AI Upscaling** using Real-ESRGAN NCNN (no fallback resampling)
* 🖋️ **A-Series Paper Sizes & DPI control** (A1, A2, A3)
* 💪 **Keep Native Pixels** — skips resizing for high-megapixel images
* 🔦 **Modern Dark GUI** built with PySide6
* 🔒 **Transparent Logging Panel** (right-side live logs)

---

## 🔧 Installation

### 1. Prerequisites

* Windows 10/11
* Python 3.10+
* GPU with updated drivers (NVIDIA/AMD/Intel)
* Real-ESRGAN NCNN executable (not the PyTorch version)

### 2. Install Real-ESRGAN NCNN

Download the Windows ZIP from:

> [https://github.com/xinntao/Real-ESRGAN/releases](https://github.com/xinntao/Real-ESRGAN/releases)

Extract it to:

```
C:\tools\realesrgan-ncnn-vulkan-20220424-windows\
```

Ensure this structure:

```
C:\tools\realesrgan-ncnn-vulkan-20220424-windows\
  realesrgan-ncnn-vulkan.exe
  models\
    realesrgan-x4plus.param
    realesrgan-x4plus.bin
```

### 3. Clone and Setup

```bash
git clone https://github.com/Wiradjuri/Poster-maker.git
cd Poster-maker
py -3.10 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 4. Run the App

```bash
python -m app.ui_main_window
```

Select your input image, choose an output folder, and set:

```
Executable:  C:\tools\realesrgan-ncnn-vulkan-20220424-windows\realesrgan-ncnn-vulkan.exe
```

Then hit **Process**.

---

## 🔊 Troubleshooting

| Problem                            | Solution                                              |
| ---------------------------------- | ----------------------------------------------------- |
| Black output                       | Uncheck FP16 and set tile size to 256                 |
| Models not found                   | Ensure `models/` folder is beside `.exe`              |
| ImportError: No module named `app` | Run from project root: `python -m app.ui_main_window` |
| Too large output / memory error    | Reduce DPI or choose A2/A3 paper                      |

---

## 🔍 Project Structure

```
PosterMaker/
├─ app/
│  ├─ imaging/
│  │  └─ pipeline.py          # Real-ESRGAN orchestration (no fallbacks)
│  ├─ ui_main_window.py       # PySide6 GUI (split log, dark theme)
├─ output/                    # Generated images (ignored by git)
├─ INSTALLATION.md
├─ LICENSE
├─ README.md
└─ requirements.txt
```

---

## 🌐 License

This project is licensed under the **MIT License**.
See [LICENSE](LICENSE) for details.
