"""Build a portable Windows folder, including Conda DLLs when applicable."""
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
args = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
        '--windowed', '--onedir', '--name', 'MemeDrop']
conda_bin = Path(sys.base_prefix) / 'Library' / 'bin'
for filename in ('sqlite3.dll', 'libcrypto-3-x64.dll', 'libssl-3-x64.dll'):
    dll = conda_bin / filename
    if dll.is_file():
        args.extend(['--add-binary', str(dll) + ';.'])
args.append('main.py')
subprocess.run(args, cwd=root, check=True)
destination = root / 'dist' / 'MemeDrop'
(destination / 'memes').mkdir(exist_ok=True)
(destination / 'README.md').write_bytes((root / 'README.md').read_bytes())
print('Built:', destination / 'MemeDrop.exe')
