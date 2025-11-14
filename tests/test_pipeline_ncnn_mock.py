from pathlib import Path
from PIL import Image
import subprocess

from app.imaging.pipeline import process_exact, A_SIZES_MM


def _make_dummy_exe_and_models(tmp_path: Path) -> Path:
    # Create a fake executable file and a models directory next to it
    exe_dir = tmp_path / "fake_exe_dir"
    exe_dir.mkdir()
    exe = exe_dir / "realesrgan-ncnn-vulkan.exe"
    exe.write_text("")
    models = exe_dir / "models"
    models.mkdir()
    # create dummy model files so _detect_models_dir is satisfied
    (models / "realesrgan-x4plus.param").write_text("param")
    (models / "realesrgan-x4plus.bin").write_text("bin")
    return exe


def test_force_600_requires_force_flag(tmp_path: Path):
    src = tmp_path / "in.png"
    Image.new("RGB", (200, 200), (128, 128, 128)).save(src)

    exe = _make_dummy_exe_and_models(tmp_path)

    try:
        # Should raise because force_600dpi is False by default
        process_exact(
            input_path=src,
            output_dir=tmp_path,
            paper="a3",
            dpi=600,
            portrait=True,
            exe_path=str(exe),
        )
    except ValueError as e:
        assert "600 DPI is disabled" in str(e)
    else:
        raise AssertionError("Expected ValueError for 600 DPI without force flag")


def test_pipeline_fp16_retry_and_progress(tmp_path: Path, monkeypatch):
    # Create a small source image
    src = tmp_path / "in.png"
    Image.new("RGB", (200, 200), (120, 120, 120)).save(src)

    exe = _make_dummy_exe_and_models(tmp_path)

    progress_calls = []
    preview_calls = []

    def progress_cb(v: int):
        progress_calls.append(int(v))

    def preview_cb(p: str):
        preview_calls.append(p)

    # Mock subprocess.Popen to simulate NCNN behavior. If '-x' (FP16) is in
    # the command, create an all-black image at the output path. Otherwise
    # create a non-black image. Also yield some stdout lines so pipeline
    # streaming works.
    class MockPopen:
        def __init__(self, cmd, cwd=None, stdout=None, stderr=None, text=None, bufsize=None):
            self.cmd = list(cmd)
            self.cwd = cwd
            # find output path after '-o'
            try:
                o_idx = self.cmd.index("-o")
                outp = Path(self.cmd[o_idx + 1])
            except Exception:
                outp = Path(cwd) / "out.png"

            # Simulate writing some stdout lines
            self.stdout = iter(["[INFO] starting\n", "[INFO] finished\n"])

            # Determine whether fp16 was requested
            if "-x" in self.cmd:
                # create an all-black image (to trigger retry logic)
                Image.new("RGB", (16, 16), (0, 0, 0)).save(outp)
            else:
                # create a visible non-black image
                Image.new("RGB", (16, 16), (64, 64, 64)).save(outp)

            self._returncode = 0

        def wait(self):
            return self._returncode

        def kill(self):
            self._returncode = -1

    monkeypatch.setattr(subprocess, "Popen", MockPopen)

    out = process_exact(
        input_path=src,
        output_dir=tmp_path,
        paper="a3",
        dpi=150,
        portrait=True,
        exe_path=str(exe),
        model="realesrgan-x4plus",
        tilesize=512,
        fp16=True,
        progress_cb=progress_cb,
        preview_cb=preview_cb,
    )

    # Output should exist and be a valid PNG
    assert Path(out).exists()
    with Image.open(out) as final:
        tw, th = final.size
        # check that the final image has the expected target pixels
        # compute expected
        w_mm, h_mm = A_SIZES_MM["a3"]
        w_in = w_mm / 25.4
        h_in = h_mm / 25.4
        exp_w = int(round(w_in * 150))
        exp_h = int(round(h_in * 150))
        assert (tw, th) == (exp_w, exp_h)

    # Progress should have moved and ended at 100
    assert len(progress_calls) > 0
    assert progress_calls[-1] == 100
    # Preview should have at least the final path
    assert len(preview_calls) >= 1
