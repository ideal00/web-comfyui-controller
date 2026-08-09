"""Local image processing used by the LayerStyle-compatible preview."""

from __future__ import annotations

from easy_panel_app.numeric import bounded


def _gray_offset(channel: "Image.Image", offset: int, wrap: bool = False) -> "Image.Image":
    """LayerStyle image_gray_offset / image_hue_offset equivalent."""
    import numpy as np
    from PIL import Image

    array = np.array(channel, dtype=np.int16)
    array = (array + offset) % 256 if wrap else np.clip(array + offset, 0, 255)
    return Image.fromarray(array.astype(np.uint8), "L")


def apply_color_correction(image_bytes: bytes, params: dict) -> bytes:
    """Apply the same correction chain used by the panel's ComfyUI workflow."""
    import io

    import numpy as np
    from PIL import Image, ImageEnhance

    brightness = bounded(params.get("brightness"), 1.0, 0.0, 3.0, integer=False)
    contrast = bounded(params.get("contrast"), 1.0, 0.0, 3.0, integer=False)
    saturation = bounded(params.get("saturation"), 1.0, 0.0, 3.0, integer=False)
    red = bounded(params.get("red"), 0, -255, 255)
    green = bounded(params.get("green"), 0, -255, 255)
    blue = bounded(params.get("blue"), 0, -255, 255)
    hue = bounded(params.get("hue"), 0, -255, 255)
    hsv_saturation = bounded(params.get("hsvSaturation"), 0, -255, 255)
    value = bounded(params.get("value"), 0, -255, 255)
    gamma = bounded(params.get("gamma"), 1.0, 0.1, 10.0, integer=False)
    black_point = bounded(params.get("blackPoint"), 0, 0, 254)
    white_point = bounded(params.get("whitePoint"), 255, 1, 255)
    if black_point >= white_point:
        black_point, white_point = 0, 255
    gray_point = bounded(params.get("grayPoint"), 1.0, 0.01, 9.99, integer=False)

    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    if brightness != 1:
        image = ImageEnhance.Brightness(image).enhance(brightness)
    if contrast != 1:
        image = ImageEnhance.Contrast(image).enhance(contrast)
    if saturation != 1:
        image = ImageEnhance.Color(image).enhance(saturation)

    if red or green or blue:
        array = np.array(image).astype(np.int16)
        for index, offset in enumerate((red, green, blue)):
            if offset:
                array[:, :, index] = np.clip(array[:, :, index] + offset, 0, 255)
        image = Image.fromarray(array.astype(np.uint8), "RGB")

    if hue or hsv_saturation or value:
        h_channel, s_channel, v_channel = image.convert("HSV").split()
        if hue:
            h_channel = _gray_offset(h_channel, hue, wrap=True)
        if hsv_saturation:
            s_channel = _gray_offset(s_channel, hsv_saturation)
        if value:
            v_channel = _gray_offset(v_channel, value)
        image = Image.merge("HSV", (h_channel, s_channel, v_channel)).convert("RGB")

    if gamma != 1:
        array = 255.0 * np.power(np.array(image).astype(np.float64) / 255.0, gamma)
        image = Image.fromarray(np.clip(array, 0, 255).astype(np.uint8), "RGB")

    if black_point > 0 or white_point < 255 or gray_point != 1:
        array = np.array(image).astype(np.float64)
        if black_point > 0 or white_point < 255:
            array = np.clip(255.0 * (array - black_point) / (white_point - black_point), 0, 255)
        if gray_point != 1.0:
            array = np.clip(255.0 * np.power(array / 255.0, 1.0 / gray_point), 0, 255)
        image = Image.fromarray(array.astype(np.uint8), "RGB")

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


__all__ = ["apply_color_correction"]
