import logging
import argparse
import os
import sys
from pathlib import Path

from PySide6.QtCore import QLockFile, QTimer
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication, QMessageBox

from memedrop.library import Library
from memedrop.ui import MainWindow, STYLE
from memedrop import desktop as windows


def main():
    parser = argparse.ArgumentParser(description='MemeDrop desktop media picker')
    parser.add_argument('--library', type=Path, help='Folder containing memes and .memedrop')
    parser.add_argument('--smoke-test', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not windows.AVAILABLE and not args.smoke_test:
        parser.error('Desktop mode requires Windows. Use --smoke-test for Docker UI verification.')
    root = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
    if args.library:
        root = args.library.resolve()
    elif getattr(sys, 'frozen', False) and root.parent.name == 'dist' and (root.parent.parent / 'main.py').is_file():
        root = root.parent.parent
    if args.smoke_test:
        os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    app = QApplication(sys.argv)
    if args.smoke_test and windows.AVAILABLE:
        fonts = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts'
        for name in ('segoeui.ttf', 'segoeuib.ttf', 'msjh.ttc', 'msjhbd.ttc'):
            QFontDatabase.addApplicationFont(str(fonts / name))
    app.setApplicationName('MemeDrop')
    app.setOrganizationName('MemeDrop')
    app.setStyle('Fusion')
    app.setStyleSheet(STYLE)
    app.setQuitOnLastWindowClosed(False)
    try:
        library = Library(root)
    except Exception as exc:
        if args.smoke_test:
            print(f'Cannot open library: {exc}', file=sys.stderr)
            return 1
        QMessageBox.critical(None, 'MemeDrop', f'無法開啟素材庫，請將 App 放在可寫入的資料夾。\n{exc}')
        return 1
    lock = QLockFile(str(library.data_dir / 'app.lock'))
    lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        if args.smoke_test:
            library.close()
            print('Library is already in use', file=sys.stderr)
            return 1
        QMessageBox.information(None, 'MemeDrop 已啟動', '請使用系統匣圖示或全域快捷鍵開啟現有視窗。')
        library.close()
        return 0
    logging.basicConfig(filename=str(library.data_dir / 'app.log'), level=logging.INFO,
                        format='%(asctime)s %(levelname)s %(message)s', encoding='utf-8')

    def exception_handler(exc_type, value, traceback):
        logging.error('Unhandled exception', exc_info=(exc_type, value, traceback))
        if args.smoke_test:
            print(f'Smoke test failed: {value}', file=sys.stderr)
            app.exit(1)
            return
        QMessageBox.critical(None, 'MemeDrop', f'發生錯誤：{value}\n詳細資訊已寫入 .memedrop/app.log')

    sys.excepthook = exception_handler
    previous = windows.foreground()
    window = MainWindow(library, native=not args.smoke_test)
    if windows.external_window(previous):
        window.target = previous
    window.show_picker()
    if args.smoke_test:
        def finish_smoke():
            if not window.grab().save(str(library.data_dir / 'smoke-test.png')):
                raise OSError('Cannot write smoke-test screenshot')
            (library.data_dir / 'smoke-test.ok').write_text('MemeDrop started successfully', encoding='utf-8')
            app.quit()
        QTimer.singleShot(600, finish_smoke)
    app.aboutToQuit.connect(window.cleanup)
    try:
        return app.exec()
    finally:
        library.close()
        lock.unlock()


if __name__ == '__main__':
    sys.exit(main())
