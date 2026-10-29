"""Read visible image text without changing imported source files."""
import logging
from pathlib import Path

from .library import IMAGE_EXTENSIONS, ANIMATION_EXTENSIONS


def recognize_import_text(paths, progress=None, cancelled=lambda: False):
    import cv2
    import numpy as np
    from PIL import Image
    from .video_series import SubtitleOCR, caption_text
    engine = None
    texts = {}
    for index, source in enumerate(paths):
        if cancelled():
            break
        source = Path(source)
        if progress:
            progress(round(index * 100 / max(1, len(paths))), f'辨識圖片文字：{source.name}')
        if source.suffix.lower() not in IMAGE_EXTENSIONS | ANIMATION_EXTENSIONS:
            continue
        try:
            choices = []
            with Image.open(source) as image:
                total = getattr(image, 'n_frames', 1)
                # Sample animations as images; keep the original animation bytes on import.
                for frame in sorted({round(i * (total - 1) / 4) for i in range(5)}):
                    if cancelled():
                        break
                    image.seek(frame)
                    rgba = image.convert('RGBA')
                    background = Image.new('RGBA', rgba.size, 'white')
                    background.alpha_composite(rgba)
                    rgb = background.convert('RGB')
                    rgb.thumbnail((1600, 1600))
                    pixels = cv2.cvtColor(np.array(rgb), cv2.COLOR_RGB2BGR)
                    # A uniform image has no visible text and needs no OCR model.
                    if float(pixels.reshape(-1, 3).std(axis=0).max()) < 1:
                        continue
                    if engine is None:
                        engine = SubtitleOCR()
                    text, confidence = engine(pixels)
                    if caption_text(text):
                        choices.append((confidence, len(text), caption_text(text)))
            if choices:
                texts[source] = max(choices)[2]
        except Exception:
            logging.exception('Image text recognition failed for %s; keeping original name', source.name)
    return texts
