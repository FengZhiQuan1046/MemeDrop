"""Local subtitle OCR and caption-frame extraction, independent of the Qt UI."""
from __future__ import annotations

import html
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from .search import search_key


@dataclass
class CaptionFrame:
    text: str
    path: Path
    seconds: float


@dataclass
class Subtitle:
    start: float
    end: float
    text: str


def caption_text(text: str) -> str:
    return ' '.join(text.split())


def caption_stem(text: str) -> str:
    replacements = str.maketrans('<>:"/\\|?*', '＜＞：＂／＼｜？＊')
    name = re.sub(r'[\x00-\x1f]', '', caption_text(text)).translate(replacements).strip()[:100].rstrip()
    name = re.sub(r'\.+$', lambda match: '．' * len(match.group()), name)
    if not name:
        raise ValueError('台詞內容不能為空。')
    if re.match(r'^(CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])(?:\.|$)', name, re.IGNORECASE):
        name = '_' + name
    return name


def _seconds(value: str) -> float:
    parts = value.replace(',', '.').split(':')
    return sum(float(part) * (60 ** index) for index, part in enumerate(reversed(parts)))


def read_subtitles(path: Path) -> list[Subtitle]:
    data = path.read_bytes()
    try:
        text = data.decode('utf-16' if data.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig')
    except UnicodeDecodeError as exc:
        raise ValueError('請將字幕檔另存為 UTF-8 或 UTF-16 編碼後再匯入。') from exc
    timestamp = r'(?:\d+:)?\d{2}:\d{2}[.,]\d{1,3}'
    cues = []
    for block in re.split(r'\n\s*\n', text.replace('\r\n', '\n').replace('\r', '\n')):
        lines = block.strip().splitlines()
        for index, line in enumerate(lines):
            match = re.match(rf'^\s*({timestamp})\s*-->\s*({timestamp})', line)
            if not match:
                continue
            start, end = map(_seconds, match.groups())
            content = html.unescape(re.sub(r'<[^>]+>|\{\\[^}]*\}', '', '\n'.join(lines[index + 1:]))).strip()
            if content and math.isfinite(start) and math.isfinite(end) and 0 <= start < end:
                cues.append(Subtitle(start, end, content))
            break
    if not cues:
        raise ValueError('字幕檔沒有有效台詞，請使用含時間軸的 SRT 或 VTT 字幕。')
    return sorted(cues, key=lambda cue: (cue.start, cue.end))


def read_embedded_subtitles(video: Path, cancelled: Callable = lambda: False) -> list[Subtitle]:
    import av
    try:
        with av.open(str(video)) as container:
            streams = [stream for stream in container.streams.subtitles
                       if stream.codec_context.name in {'ass', 'ssa', 'subrip', 'srt', 'mov_text', 'webvtt', 'text'}]
            streams.sort(key=lambda stream: not stream.metadata.get('language', '').lower().startswith(('zh', 'chi', 'zho')))
            if not streams:
                return []
            cues = []
            stream = streams[0]
            for packet in container.demux(stream):
                if cancelled():
                    return cues
                if not packet.size:
                    continue
                subtitle = stream.codec_context.decode2(packet)
                if subtitle is None:
                    continue
                lines = []
                for rectangle in subtitle:
                    ass = getattr(rectangle, 'ass', b'')
                    text = ass or getattr(rectangle, 'text', b'')
                    if isinstance(text, bytes):
                        text = text.decode('utf-8', errors='replace')
                    if ass:
                        text = text.split(',', 8)[-1]
                    text = re.sub(r'\{[^}]*\}', '', text).replace('\\N', '\n').replace('\\n', '\n').replace('\\h', ' ')
                    if text.strip():
                        lines.append(text.strip())
                base = (float(subtitle.pts) / av.time_base if subtitle.pts is not None and subtitle.pts > -1e15
                        else float((packet.pts or 0) * packet.time_base))
                start = base + subtitle.start_display_time / 1000
                end = base + subtitle.end_display_time / 1000
                if (end <= start or end - start > 3600) and packet.duration:
                    end = start + float(packet.duration * packet.time_base)
                if lines and 0 <= start < end:
                    cues.append(Subtitle(start, end, '\n'.join(lines)))
            return cues
    except av.FFmpegError:
        return []  # A video decoder may still be able to read burned subtitles.


def _subtitle_font(size: int):
    from PIL import ImageFont
    candidates = [Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / 'msjh.ttc',
                  Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'),
                  Path('/System/Library/Fonts/PingFang.ttc')]
    for path in candidates:
        if path.is_file():
            return ImageFont.truetype(str(path), size)
    raise ValueError('找不到中文字幕字型，請安裝 Microsoft JhengHei 或 Noto Sans CJK。')


def render_subtitle(frame, text: str):
    import cv2
    import numpy as np
    from PIL import Image, ImageDraw
    image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(image)
    font = _subtitle_font(max(16, round(image.height * 0.045)))
    lines, line = [], ''
    for char in caption_text(text):
        if line and draw.textlength(line + char, font=font) > image.width * 0.9:
            lines.append(line)
            line = ''
        line += char
    if line:
        lines.append(line)
    spacing = max(20, round(image.height * 0.06))
    y = max(0, image.height - spacing * (len(lines) + 0.6))
    for line in lines:
        draw.text((image.width / 2, y), line, font=font, fill='white', anchor='mt',
                  stroke_width=max(1, spacing // 15), stroke_fill='black')
        y += spacing
    return cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)


class SubtitleOCR:
    def __init__(self):
        from rapidocr import RapidOCR
        self.engine = RapidOCR(params={'Global.use_cls': False, 'Global.log_level': 'warning',
                                      'Det.limit_type': 'max', 'Det.limit_side_len': 1280,
                                      'EngineConfig.onnxruntime.intra_op_num_threads': 2,
                                      'EngineConfig.onnxruntime.inter_op_num_threads': 1})

    def __call__(self, image) -> tuple[str, float]:
        result = self.engine(image, use_cls=False)
        if result.txts is None or result.scores is None or result.boxes is None:
            return '', 0
        rows = [(box, text.strip(), float(score))
                for box, text, score in zip(result.boxes, result.txts, result.scores)
                if text.strip() and float(score) >= 0.65]
        rows.sort(key=lambda row: (float(row[0][0][1]) // 12, float(row[0][0][0])))
        return ' '.join(row[1] for row in rows), sum(row[2] for row in rows) / len(rows) if rows else 0


def extract_caption_frames(video: Path, output_dir: Path, *, interval: float = 0.5,
                           bottom_fraction: float = 0.4, subtitles: Optional[Path] = None,
                           draw_subtitles: bool = True, embedded: bool = True, progress: Optional[Callable] = None,
                           cancelled: Optional[Callable] = None, recognizer=None) -> list[CaptionFrame]:
    import cv2
    if not video.is_file():
        raise ValueError('影片檔案不存在。')
    if not 0.1 <= interval <= 5 or not 0.1 <= bottom_fraction <= 1:
        raise ValueError('擷取間隔或字幕範圍無效。')
    progress = progress or (lambda value, message: None)
    cancelled = cancelled or (lambda: False)
    output_dir.mkdir(parents=True, exist_ok=True)
    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        capture.release()
        raise ValueError('無法開啟影片，請確認檔案完整且格式受支援。')
    frames = []

    def save(frame, text, seconds):
        text = caption_text(text)
        if not text:
            return
        ok, png = cv2.imencode('.png', frame)
        if not ok:
            raise ValueError('無法儲存影片截圖。')
        path = output_dir / f'{len(frames) + 1:06d}.png'
        with path.open('xb') as stream:
            stream.write(png.tobytes())
        frames.append(CaptionFrame(text, path, seconds))

    def frame_at(seconds):
        capture.set(cv2.CAP_PROP_POS_MSEC, seconds * 1000)
        ok, frame = capture.read()
        if not ok:
            raise ValueError(f'無法讀取影片 {seconds:.1f} 秒的畫面。')
        return frame

    try:
        fps = capture.get(cv2.CAP_PROP_FPS)
        count = capture.get(cv2.CAP_PROP_FRAME_COUNT)
        if not math.isfinite(fps) or not math.isfinite(count) or fps <= 0 or count <= 0:
            raise ValueError('無法讀取影片長度，請先將影片轉成一般 MP4 格式。')
        duration = count / fps
        cues = read_subtitles(subtitles) if subtitles else []
        if not subtitles and embedded and recognizer is None:
            progress(0, '正在檢查影片內的文字字幕…')
            cues = read_embedded_subtitles(video, cancelled)
        if cancelled():
            return frames
        if subtitles or cues:
            cues = [cue for cue in cues if cue.start < duration]
            if not cues:
                raise ValueError('字幕時間軸未落在這段影片內。')
            for index, cue in enumerate(cues):
                if cancelled():
                    break
                seconds = (cue.start + min(cue.end, duration - 1 / fps)) / 2
                frame = frame_at(max(0, seconds))
                if draw_subtitles:
                    frame = render_subtitle(frame, cue.text)
                save(frame, cue.text, seconds)
                progress(round((index + 1) * 100 / len(cues)), f'已擷取 {len(frames)} 句台詞')
        else:
            progress(0, '準備本機字幕辨識模型…')
            ocr = recognizer or SubtitleOCR()
            pending = None
            samples = max(1, math.ceil(duration / interval))
            for index in range(samples):
                if cancelled():
                    break
                seconds = min(index * interval, duration - 1 / fps)
                frame = frame_at(max(0, seconds))
                height = frame.shape[0]
                crop = frame[round(height * (1 - bottom_fraction)):]
                text, score = ocr(crop)
                text = caption_text(text)
                key = search_key(re.sub(r'\s+', '', text))
                if pending is not None and pending[0] != key:
                    save(pending[3], pending[1], pending[4])
                    pending = None
                if text and (pending is None or score >= pending[2]):
                    pending = (key, text, score, frame.copy(), seconds)
                progress(round((index + 1) * 100 / samples),
                         f'已掃描 {seconds:.1f} / {duration:.1f} 秒 · 找到 {len(frames) + int(pending is not None)} 句台詞')
            if pending is not None:
                save(pending[3], pending[1], pending[4])
        return frames
    finally:
        capture.release()
