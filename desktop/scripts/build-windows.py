"""Bundle Windows x64 Python, CPU model dependencies, OCR and VC runtime DLLs."""
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / 'build/windows'
RUNTIME = BUILD / 'runtime'

def run(*args, **kwargs):
    return subprocess.run([str(arg) for arg in args], check=True, **kwargs)

def bundle_ocr():
    source = Path(os.environ.get('RECALL_TESSERACT_DIR', r'C:\Program Files\Tesseract-OCR'))
    if not (source / 'tesseract.exe').is_file():
        raise RuntimeError('Install Tesseract first, or set RECALL_TESSERACT_DIR to its installation directory.')
    # Preserve sibling DLLs, license notices and English language data together.
    target = RUNTIME / 'ocr'
    shutil.copytree(source, target, ignore=shutil.ignore_patterns('uninstall*', 'Uninstall*'))
    for language in ('eng', 'osd'):
        if not (target / 'tessdata' / f'{language}.traineddata').is_file():
            raise RuntimeError(f'Missing Tesseract language: {language}')
    run(target / 'tesseract.exe', '--list-langs', env={**os.environ, 'TESSDATA_PREFIX': str(target / 'tessdata')})

def bundle_vc_runtime():
    # Use the redistributable CRT supplied by Visual Studio, not Windows system DLLs.
    directory = Path(os.environ.get('ProgramFiles', r'C:\Program Files')) / 'Microsoft Visual Studio'
    candidates = sorted(directory.glob('2022/*/VC/Redist/MSVC/*/x64/Microsoft.VC143.CRT'))
    if not candidates:
        raise RuntimeError('Visual Studio 2022 x64 VC++ redistributable files are required to package Torch.')
    dlls = list(candidates[-1].glob('*.dll'))
    if not dlls:
        raise RuntimeError('No VC++ redistributable DLLs found.')
    for file in dlls:
        for dest in (RUNTIME / 'python', RUNTIME / 'ocr'):
            shutil.copy2(file, dest / file.name)
    notices = RUNTIME / 'licenses'
    notices.mkdir(exist_ok=True)
    for file in candidates[-1].parents[2].glob('**/redist*.txt'):
        shutil.copy2(file, notices / file.name)

def main():
    if sys.platform != 'win32' or platform.machine().lower() not in ('amd64', 'x86_64'):
        raise SystemExit('Run this build on Windows x64 (or use the Build Windows GitHub Action).')
    if not shutil.which('uv'):
        raise SystemExit('Install uv before building.')
    downloads = ROOT / 'build/windows-python'
    run('uv', 'python', 'install', '3.13.16', '--install-dir', downloads, '--no-bin', '--no-registry', '--cache-dir', ROOT / 'build/uv-cache')
    source = downloads / 'cpython-3.13.16-windows-x86_64-none'
    if not (source / 'python.exe').is_file():
        raise RuntimeError(f'Expected standalone Python at {source}')
    if RUNTIME.exists():
        shutil.rmtree(RUNTIME)
    shutil.copytree(source, RUNTIME / 'python', symlinks=False)
    python = RUNTIME / 'python/python.exe'
    run('uv', 'pip', 'install', '--python', python, '--break-system-packages', '--torch-backend', 'cpu',
        '--cache-dir', ROOT / 'build/uv-cache', '-r', ROOT / 'desktop/requirements-windows.lock', ROOT)
    for cache in RUNTIME.rglob('__pycache__'):
        shutil.rmtree(cache)
    bundle_ocr()
    bundle_vc_runtime()
    (RUNTIME / 'build-info.json').write_text(json.dumps({'architecture': 'x64', 'python': '3.13.16', 'torch': 'cpu'}, indent=2))
    run(python, '-I', '-B', '-c', 'import torch, torchvision, pymupdf, tree_sitter_language_pack; print("Bundled Windows dependencies ready")')

if __name__ == '__main__':
    main()
