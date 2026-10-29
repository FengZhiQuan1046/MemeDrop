import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from memedrop.library import Library
from memedrop.search import search_key
from memedrop.video_series import (CaptionFrame, caption_stem, extract_caption_frames,
                                  read_embedded_subtitles, read_subtitles, render_subtitle)


class VideoSeriesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.lib = Library(self.root, include_builtins=False)
        self.video = self.root / '中文影片.avi'
        self.write_video([np.full((360, 640, 3), 45, dtype=np.uint8)] * 16)

    def tearDown(self):
        self.lib.close()
        self.temp.cleanup()

    def write_video(self, frames):
        writer = cv2.VideoWriter(str(self.video), cv2.VideoWriter_fourcc(*'MJPG'), 4, (640, 360))
        self.assertTrue(writer.isOpened())
        try:
            for frame in frames:
                writer.write(frame)
        finally:
            writer.release()

    def frame(self, text, filename='preview.png'):
        path = self.root / filename
        self.assertTrue(cv2.imwrite(str(path), np.zeros((10, 10, 3), dtype=np.uint8)))
        return CaptionFrame(text, path, 1)

    def test_ocr_groups_continuous_captions_and_keeps_later_repetitions(self):
        readings = iter([('你好', .9), ('你好', .95), ('', 0), ('再見', .9),
                         ('再見', .9), ('', 0), ('你好', .9), ('你好', .9)])
        frames = extract_caption_frames(self.video, self.root / 'frames', interval=.5,
                                       recognizer=lambda crop: next(readings))
        self.assertEqual([frame.text for frame in frames], ['你好', '再見', '你好'])
        self.assertEqual([frame.seconds for frame in frames], [.5, 2, 3.5])
        self.assertTrue(all(cv2.imdecode(np.fromfile(frame.path, dtype=np.uint8), cv2.IMREAD_COLOR).shape == (360, 640, 3)
                            for frame in frames))

    def test_real_video_ocr_extracts_burned_chinese_subtitles_offline(self):
        base = np.full((360, 640, 3), 45, dtype=np.uint8)
        first = render_subtitle(base, '今天也要加油')
        second = render_subtitle(base, '收到謝謝')
        self.write_video([first] * 4 + [base] * 2 + [second] * 4 + [base] * 2 + [first] * 4)
        frames = extract_caption_frames(self.video, self.root / 'real-ocr', interval=.5)
        self.assertEqual(len(frames), 3)
        self.assertIn('今天', frames[0].text)
        self.assertIn('加油', frames[0].text)
        self.assertEqual(search_key(frames[0].text), search_key(frames[2].text))
        sid, count = self.lib.save_caption_series(frames, name='影片台詞')
        self.assertEqual(count, 3)
        names = [item.name for item in self.lib.items(section=f'series:{sid}', sort='name')]
        self.assertIn(frames[0].text, names)
        self.assertIn(frames[0].text + ' (2)', names)

    def test_srt_and_vtt_parse_and_timed_frames_can_render_subtitles(self):
        path = self.root / '台詞.srt'
        path.write_text('1\n00:00:00,000 --> 00:00:01,000\n<i>你好</i>\n世界\n\n'
                        '2\n00:00:02,000 --> 00:00:03,000\nHello &amp; Bye\n', encoding='utf-8-sig')
        self.assertEqual([cue.text for cue in read_subtitles(path)], ['你好\n世界', 'Hello & Bye'])
        frames = extract_caption_frames(self.video, self.root / 'srt', subtitles=path)
        self.assertEqual([frame.text for frame in frames], ['你好 世界', 'Hello & Bye'])
        self.assertEqual([frame.seconds for frame in frames], [.5, 2.5])
        image = cv2.imdecode(np.fromfile(frames[0].path, dtype=np.uint8), cv2.IMREAD_COLOR)
        self.assertGreater(int(image[280:].max()), 200)
        path.write_text('WEBVTT\n\ncue-id\n00:01.000 --> 00:02.000 align:start\n欢迎\n', encoding='utf-16')
        self.assertEqual(read_subtitles(path)[0].start, 1)

    def test_cancel_and_invalid_inputs_do_not_continue_extraction(self):
        progress = []
        frames = extract_caption_frames(self.video, self.root / 'cancel',
            cancelled=lambda: len(progress) >= 3, progress=lambda *args: progress.append(args),
            recognizer=lambda crop: ('停止前', .9))
        self.assertEqual(len(frames), 1)
        with self.assertRaises(ValueError):
            extract_caption_frames(self.video, self.root / 'invalid', interval=0)
        with self.assertRaises(ValueError):
            extract_caption_frames(self.root / 'missing.mp4', self.root / 'missing')
        path = self.root / 'empty.srt'
        path.write_text('沒有時間軸', encoding='utf-8')
        with self.assertRaises(ValueError):
            read_subtitles(path)

    def test_embedded_text_subtitles_are_read_and_rendered_without_ocr(self):
        import av
        srt = self.root / 'embedded.srt'
        srt.write_text('1\n00:00:00,000 --> 00:00:01,000\n內嵌台詞\n\n'
                       '2\n00:00:02,000 --> 00:00:03,000\n第二句\n', encoding='utf-8')
        mkv = self.root / '內嵌字幕.mkv'
        with av.open(str(self.video)) as video_input, av.open(str(srt)) as text_input, av.open(str(mkv), 'w') as output:
            video_stream, text_stream = video_input.streams.video[0], text_input.streams.subtitles[0]
            out_video = output.add_stream_from_template(video_stream)
            out_text = output.add_stream_from_template(text_stream)
            out_text.metadata['language'] = 'zho'
            packets = [(packet, out_video) for packet in video_input.demux(video_stream) if packet.size]
            packets += [(packet, out_text) for packet in text_input.demux(text_stream) if packet.size]
            packets.sort(key=lambda item: float((item[0].dts or 0) * item[0].time_base))
            for packet, stream in packets:
                packet.stream = stream
                output.mux(packet)
        self.assertEqual([cue.text for cue in read_embedded_subtitles(mkv)], ['內嵌台詞', '第二句'])
        with patch('memedrop.video_series.SubtitleOCR', side_effect=AssertionError('OCR should not be used')):
            frames = extract_caption_frames(mkv, self.root / 'embedded-frames')
        self.assertEqual([frame.text for frame in frames], ['內嵌台詞', '第二句'])

    def test_caption_names_are_safe_and_duplicates_get_numbered(self):
        self.assertEqual(caption_stem('  你: 還好嗎?\n下一句/內容  '), '你： 還好嗎？ 下一句／內容')
        self.assertEqual(caption_stem('CON'), '_CON')
        self.assertEqual(caption_stem('...'), '．．．')
        with self.assertRaises(ValueError):
            caption_stem(' \n ')
        frame = self.frame('歡迎：Hello?')
        sid, count = self.lib.save_caption_series([frame, frame], name='電影Happy')
        self.lib.scan()
        self.assertEqual(count, 2)
        self.assertEqual(self.lib.series_counts(), [(sid, '電影Happy', 2)])
        self.assertEqual({m.name for m in self.lib.items()}, {'歡迎：Hello？', '歡迎：Hello？ (2)'})
        self.assertEqual(len(self.lib.items('欢迎 hello?', section=f'series:{sid}')), 2)
        sid2, _ = self.lib.save_caption_series([frame], series_id=sid)
        self.assertEqual(sid2, sid)
        self.assertIn('歡迎：Hello？ (3)', [m.name for m in self.lib.items()])

    def test_import_failure_rolls_back_files_database_and_new_series(self):
        first = self.frame('第一句')
        missing = CaptionFrame('不存在', self.root / 'missing.png', 2)
        with self.assertRaises(OSError):
            self.lib.save_caption_series([first, missing], name='失敗的系列')
        self.assertEqual(self.lib.series_counts(), [])
        self.assertEqual(list(self.lib.media_dir.rglob('*.png')), [])
        self.assertTrue(first.path.is_file())

    def test_full_caption_remains_searchable_when_filename_is_truncated(self):
        text = '開心' * 60 + '最後一句Hello'
        sid, _ = self.lib.save_caption_series([self.frame(text)], name='長台詞')
        meme = self.lib.items('最后一句hELLO', section=f'series:{sid}')[0]
        self.assertLessEqual(len(meme.name), 100)
        self.assertEqual(meme.content, text)

    def test_collection_rename_search_and_merge_preserve_all_metadata(self):
        frame = self.frame('你好')
        source, _ = self.lib.save_caption_series([frame, frame], name='電影HAPPY')
        target = self.lib.create_series('另一集合')
        memes = self.lib.items(section=f'series:{source}')
        self.lib.set_tags([m.id for m in memes], ['保留'])
        self.lib.set_favorite([memes[0].id], True)
        self.lib.record_use(memes[0].id)
        self.lib.trash_items([memes[1].id])
        self.lib.rename_series(source, '新電影Happy')
        self.assertEqual(self.lib.series_counts('新电影hAPPY'), [(source, '新電影Happy', 1)])
        self.assertEqual(self.lib.merge_series(source, target), 2)
        self.lib.restore_items([memes[1].id])
        self.lib.scan()
        moved = self.lib.items(section=f'series:{target}')
        self.assertEqual({m.id for m in moved}, {m.id for m in memes})
        self.assertTrue(all(m.tags == ('保留',) for m in moved))
        favorite = next(m for m in moved if m.id == memes[0].id)
        self.assertTrue(favorite.favorite)
        self.assertEqual(favorite.uses, 1)
        self.assertEqual(self.lib.items(section=f'series:{source}'), [])
        with self.assertRaises(ValueError):
            self.lib.merge_series(target, target)
        with self.assertRaises(ValueError):
            self.lib.rename_series(source, '另一集合')

    def test_merging_duplicate_caption_names_numbers_files_and_rolls_back_on_failure(self):
        frame = self.frame('相同台詞')
        source, _ = self.lib.save_caption_series([frame], name='來源')
        target, _ = self.lib.save_caption_series([frame], name='目標')
        meme = self.lib.items(section=f'series:{source}')[0]
        original = self.lib.path(meme)
        with patch.object(self.lib, '_move_file', side_effect=OSError('locked')):
            with self.assertRaises(OSError):
                self.lib.merge_series(source, target)
        self.assertTrue(original.is_file())
        self.assertEqual(self.lib.items(section=f'series:{source}')[0].name, '相同台詞')
        self.assertEqual(self.lib.merge_series(source, target), 1)
        self.lib.scan()
        self.assertEqual({m.name for m in self.lib.items(section=f'series:{target}')}, {'相同台詞', '相同台詞 (2)'})
        self.assertFalse(original.exists())
        self.assertTrue(original.with_name('相同台詞 (2).png').is_file())


if __name__ == '__main__':
    unittest.main()
