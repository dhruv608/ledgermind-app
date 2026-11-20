"""A picture sent to the AI readers (made-up images): one over the size the service takes is made smaller."""

import io
import os

from PIL import Image

from backend.app.sa.extract import vision


def test_a_small_picture_is_sent_as_it_is():
    buf = io.BytesIO()
    Image.new("RGB", (200, 200), "white").save(buf, "PNG")
    assert vision.fit(buf.getvalue()) == buf.getvalue()


def test_a_large_scan_is_made_to_fit():
    # Noise does not compress: a 2000 x 2800 page saved as PNG is far over the limit
    pic = Image.frombytes("RGB", (2000, 2800), os.urandom(2000 * 2800 * 3))
    buf = io.BytesIO()
    pic.save(buf, "PNG")
    assert buf.tell() > vision.MAX_IMAGE
    out = vision.fit(buf.getvalue())
    assert len(out) <= vision.MAX_IMAGE and out[:3] == b"\xff\xd8\xff"


def test_a_picture_in_another_colour_mode_is_saved_as_plain_rgb():
    buf = io.BytesIO()
    Image.new("CMYK", (300, 300), (0, 0, 0, 0)).save(buf, "JPEG")
    out = vision.plain(buf.getvalue())
    assert out[:3] == b"\xff\xd8\xff" and Image.open(io.BytesIO(out)).mode == "RGB"


def test_a_large_file_the_image_library_cannot_open_is_sent_as_it_is():
    # A HEIC photo or a damaged file over the limit: never a crash before the service has seen it
    odd = b"\x00\x00\x00\x18ftypheic" + os.urandom(vision.MAX_IMAGE + 10)
    assert vision.fit(odd) == odd


def test_a_small_picture_is_enlarged_and_a_large_one_left():
    small = io.BytesIO()
    Image.new("RGB", (989, 550), (255, 255, 255)).save(small, "PNG")
    out = Image.open(io.BytesIO(vision.enlarge(small.getvalue())))
    assert max(out.size) >= vision.SMALL_SIDE
    large = io.BytesIO()
    Image.new("RGB", (1654, 2339), (255, 255, 255)).save(large, "PNG")
    assert vision.enlarge(large.getvalue()) == large.getvalue()
    assert vision.enlarge(b"not a picture") == b"not a picture"
