"""Build only from committed, allowlisted source and checksum-pinned official files."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ALLOWLIST = ['studio', 'blivedm', 'favicon.ico', 'LICENSE', 'README-STUDIO.md',
             'studio_main.py', 'packaging']
PRIVATE = {'user-data', '.git', '.venv', '.qa', '__pycache__', 'credentials.json', 'studio.json'}


def sha256(path):
    with Path(path).open('rb') as file:
        return hashlib.file_digest(file, 'sha256').hexdigest()


def run(*args, **kwargs):
    subprocess.run([str(value) for value in args], check=True, **kwargs)


def download(entry, destination):
    run('curl.exe', '--fail', '--location', '--silent', '--show-error', '--retry', '3',
        '--max-time', '240', '--output', destination, entry['url'])
    if sha256(destination) != entry['sha256']:
        raise RuntimeError('Official runtime checksum mismatch: ' + destination.name)


def archive(source, destination):
    files = sorted(path for path in source.rglob('*') if path.is_file())
    for path in files:
        relative = path.relative_to(source)
        if PRIVATE.intersection(part.lower() for part in relative.parts) or path.suffix.lower() in ('.log', '.pyc', '.pyo'):
            raise RuntimeError('Private or generated data in package: ' + str(relative))
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as output:
        for path in files:
            output.write(path, source.name + '/' + path.relative_to(source).as_posix())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--version', required=True)
    parser.add_argument('--output', default=str(ROOT / 'dist'))
    options = parser.parse_args()
    if not re.fullmatch(r'[a-zA-Z0-9._-]+', options.version):
        raise ValueError('Invalid release version')
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    output = Path(options.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    name = f'DD-Monitor-Studio-{options.version}-windows-x64'
    destination = output / (name + '.zip')
    if destination.exists():
        raise FileExistsError('Refusing to overwrite an existing release')
    with tempfile.TemporaryDirectory(prefix='dd-studio-build-') as temp:
        work = Path(temp)
        package = work / name
        package.mkdir()
        source_zip = work / 'source.zip'
        run('git', 'archive', '--format=zip', '--output=' + str(source_zip), commit, *ALLOWLIST, cwd=ROOT)
        with zipfile.ZipFile(source_zip) as source:
            source.extractall(package)
        config = json.loads((package / 'packaging/windows-runtime.json').read_text('utf-8'))
        python_archive, vlc_archive = work / 'python.zip', work / 'vlc.zip'
        download(config['python'], python_archive)
        download(config['vlc'], vlc_archive)
        python = package / 'python'
        python.mkdir()
        with zipfile.ZipFile(python_archive) as source:
            source.extractall(python)
        (python / 'python313._pth').write_text('python313.zip\n.\nLib/site-packages\n..\n', encoding='ascii')
        runtime = package / 'runtime'
        runtime.mkdir()
        with zipfile.ZipFile(vlc_archive) as source:
            source.extractall(runtime)
        (runtime / ('vlc-' + config['vlc']['version'])).rename(runtime / 'vlc')
        lock = package / 'packaging/requirements-windows.lock'
        run(sys.executable, '-m', 'pip', 'install', '--isolated', '--index-url', 'https://pypi.org/simple',
            '--disable-pip-version-check', '--only-binary=:all:', '--require-hashes', '--no-compile',
            '--platform', 'win_amd64', '--python-version', '3.13', '--implementation', 'cp', '--abi', 'cp313',
            '--target', python / 'Lib/site-packages', '-r', lock)
        # Some official wheels contain bytecode built by their publisher for
        # older Python versions. Keep their source, not those stale caches.
        for path in python.rglob('*'):
            if path.is_file() and path.suffix.lower() in ('.pyc', '.pyo'):
                if not path.resolve().is_relative_to(package.resolve()):
                    raise RuntimeError('Cache path escaped the build directory')
                path.unlink()
        (package / 'portable-mode').write_text('Do not import accounts from neighboring installations.\n', encoding='utf-8')
        launcher = '@echo off\r\ncd /d "%~dp0"\r\nstart "DD Monitor Studio" "%~dp0python\\pythonw.exe" -I -B "%~dp0studio_main.py"\r\n'
        (package / '启动 DD Monitor.cmd').write_bytes(launcher.encode('ascii'))
        diagnostic = '@echo off\r\ncd /d "%~dp0"\r\n"%~dp0python\\python.exe" -I -B "%~dp0studio_main.py"\r\npause\r\n'
        (package / '诊断启动.cmd').write_bytes(diagnostic.encode('ascii'))
        shutil.copyfile(package / 'packaging/README-PORTABLE.txt', package / '使用说明.txt')
        source = {'version': options.version, 'commit': commit,
                  'repository': 'https://github.com/EricaNoir/DD_Monitor',
                  'upstream': 'https://github.com/zhimingshenjun/DD_Monitor',
                  'runtime': config, 'dependencies': 'packaging/requirements-windows.lock'}
        (package / 'SOURCE.json').write_text(json.dumps(source, indent=2) + '\n', encoding='utf-8')
        run(python / 'python.exe', '-I', '-B', package / 'packaging/verify_portable.py', cwd=package)
        manifest = []
        for path in sorted(package.rglob('*')):
            if path.is_file():
                manifest.append(sha256(path) + '  ' + path.relative_to(package).as_posix())
        (package / 'MANIFEST.sha256').write_text('\n'.join(manifest) + '\n', encoding='utf-8')
        archive(package, destination)
        # Verify the shipped archive after extraction, not just the build directory.
        extracted = work / 'extract-test'
        with zipfile.ZipFile(destination) as source:
            source.extractall(extracted)
        checked = extracted / name
        for line in (checked / 'MANIFEST.sha256').read_text('utf-8').splitlines():
            digest, relative = line.split('  ', 1)
            assert sha256(checked / relative) == digest, relative
        run(checked / 'python/python.exe', '-I', '-B', checked / 'packaging/verify_portable.py', cwd=checked)
    digest = sha256(destination)
    destination.with_suffix('.zip.sha256').write_text(digest + '  ' + destination.name + '\n', encoding='ascii')
    print(json.dumps({'archive': str(destination), 'sha256': digest, 'commit': commit}, indent=2))


if __name__ == '__main__':
    main()
