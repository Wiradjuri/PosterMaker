from app.imaging.sizes import target_pixels

def test_target_pixels_basic():
    w, h = target_pixels(594, 841, 300)  # A1 @ 300 DPI
    assert (w, h) == (7016, 9933)
