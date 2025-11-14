# 🎨 PosterMaker – AI Ultra-Resolution Poster Generator

PosterMaker is a Windows desktop application that turns any image into a **high-resolution, print-ready poster** using the Real-ESRGAN NCNN Vulkan upscaler.  
It supports A0, A1, A2, A3, A4 paper sizes, up to **600 DPI**, and produces ultra-sharp images suitable for professional printing.

Built with **Python + PySide6** and compiled into a fast, portable `.exe` using **Nuitka**.

---

## 📥 Download (Windows EXE)

Download the latest release here:

👉 **https://github.com/Wiradjuri/PosterMaker/releases/latest**

Click:

### **`PosterMaker.exe`**
to download the standalone Windows application.

---

## 🔧 System Requirements

| Component | Requirement |
|----------|-------------|
| OS | Windows 10 / 11 (64-bit) |
| GPU | NVIDIA GPU recommended (for best speed) |
| Drivers | Latest NVIDIA driver (if using GPU) |
| Disk | 2–4 GB free space per exported poster |

---

## 🚀 Features

✔ Real-ESRGAN NCNN Vulkan upscaling (no CUDA required)  
✔ Multiple AI upscale passes (4×, 2×, Lanczos refinement)  
✔ Crisp output at **300–600 DPI**  
✔ A0 / A1 / A2 / A3 / A4 paper sizes  
✔ Smooth animated progress bar  
✔ Live AI preview thumbnail  
✔ Full log window for debugging  
✔ Cancel / restart support  
✔ Dark-mode modern UI  
✔ Auto-open output folder on success  

---

## 🖼 UI Overview

*(Add your screenshot here once you want)*


---

## 🧩 How to Use the App

1. Launch **PosterMaker.exe**
2. Click **Browse** to choose your input image  
3. Choose an **output folder**  
4. Select:
   - Paper size (A0–A4)  
   - DPI (300–600)  
   - Landscape / Portrait  
   - Tile size  
   - FP16 mode  
5. Confirm the path to your `realesrgan-ncnn-vulkan.exe`
6. Click **“Process Image”**
7. Wait for the progress bar to reach 100%  
8. The app will automatically open the output folder

---

## 📦 Bundled Files

PosterMaker requires:

- **Real-ESRGAN NCNN Vulkan executable**
- **The `models` folder** (ESRGAN .bin & .param files)

The `.exe` build does **not** include these automatically due to file size.

Put them here if you want the app fully portable:

PosterMaker/
├─ PosterMaker.exe
├─ realesrgan-ncnn-vulkan.exe
├─ models/
│ ├─ realesrgan-x4plus.bin
│ ├─ realesrgan-x4plus.param
│ ├─ (...other models)

---

## 🛠 Technical Notes (For Devs)

### Build command (Nuitka)

Your build script runs:

python -m nuitka --onefile --standalone --enable-plugin=pyside6 ...


The build produces:

/dist/PosterMaker.exe


### Development Environment

- Python 3.10
- Pipenv virtual environment
- PySide6 GUI framework
- QThread worker for non-blocking AI upscaling  
- Fully rewritten pipeline (robust, validated PNG outputs)

---

## 🧰 Known Issues

- Very large posters at 600 DPI can take 1–6 minutes depending on hardware  
- On low-VRAM GPUs, FP16 or tile size > 512 may fail  
- Some antivirus tools may false-flag Nuitka .exe builds  

---

## 📄 License

MIT License © 2025 Brad (Wiradjuri)

---

## ⭐ Support the Project

If you like PosterMaker, star the repo:

👉 https://github.com/Wiradjuri/PosterMaker ⭐

It helps visibility and encourages development!
