"""Build a small Windows launcher with the product icon; no Python EXE patching."""
from pathlib import Path
import os
import subprocess
import sys


def build(root):
    root = Path(root).resolve()
    compiler = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    subprocess.run([str(compiler), '/nologo', '/target:winexe', '/optimize+', '/codepage:65001',
                    '/reference:System.Windows.Forms.dll', '/win32icon:' + str(root / 'favicon.ico'),
                    '/out:' + str(root / 'DD Monitor Studio.exe'), str(root / 'packaging/Launcher.cs')], check=True)


if __name__ == '__main__':
    build(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1])
