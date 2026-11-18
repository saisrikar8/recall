"""Prepare a self-contained macOS backend; no developer paths in the app."""
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / 'build' / 'mac'
RUNTIME = BUILD / 'runtime'
ARCH = 'arm64' if platform.machine() == 'arm64' else 'x64'

def run(*args, **kwargs):
    return subprocess.run([str(x) for x in args], check=True, **kwargs)

def output(*args):
    return subprocess.check_output([str(x) for x in args], text=True).strip()

def bundle_ocr():
    executable = shutil.which('tesseract')
    if not executable:
        raise SystemExit('Install build-time OCR tools first: brew install tesseract')
    dest = RUNTIME / 'ocr'
    (dest / 'bin').mkdir(parents=True)
    (dest / 'lib').mkdir()
    (dest / 'tessdata').mkdir()
    (dest / 'licenses').mkdir()
    shutil.copy2(Path(executable).resolve(), dest / 'bin' / 'tesseract')
    queue = [(Path(executable).resolve(), dest / 'bin' / 'tesseract')]
    copied = {}
    formulas = set()
    for source, target in queue:
        # Rewrite every non-system dependency to a location inside this bundle.
        dependencies = output('otool', '-L', source).splitlines()[1:]
        for line in dependencies:
            dependency = line.strip().split(' (')[0]
            if dependency.startswith(('/usr/lib/', '/System/Library/')):
                continue
            if dependency.startswith(('@rpath/', '@loader_path/')):
                original = (source.parent / dependency.split('/', 1)[1]).resolve()
            elif dependency.startswith('/'):
                original = Path(dependency).resolve()
            else:
                raise RuntimeError(f'Unexpected OCR library reference: {dependency}')
            if not original.is_file():
                raise RuntimeError(f'Missing OCR dependency: {original}')
            if original == source:
                continue  # dylib install ID
            name = original.name
            if name in copied and copied[name] != original:
                raise RuntimeError(f'OCR dependency name collision: {name}')
            if name not in copied:
                copied[name] = original
                library = dest / 'lib' / name
                shutil.copy2(original, library)
                queue.append((original, library))
            reference = ('@executable_path/../lib/' if target.parent.name == 'bin' else '@loader_path/') + name
            run('install_name_tool', '-change', dependency, reference, target, stderr=subprocess.DEVNULL)
        if target.parent.name == 'lib':
            run('install_name_tool', '-id', '@rpath/' + target.name, target, stderr=subprocess.DEVNULL)
        parts = source.parts
        if 'Cellar' in parts:
            prefix = Path(*parts[:parts.index('Cellar') + 3])
            formulas.add(str(prefix))
            license_dir = dest / 'licenses' / prefix.parent.name
            license_dir.mkdir(exist_ok=True)
            for pattern in ('LICENSE*', 'COPYING*', 'NOTICE*', 'share/doc/**/COPYING*', 'share/doc/**/LICENSE*'):
                for file in prefix.glob(pattern):
                    if file.is_file():
                        shutil.copy2(file, license_dir / file.name)
        run('codesign', '--force', '--sign', '-', target, stderr=subprocess.DEVNULL)
    # Tesseract reports its installed language-data location even when it is empty.
    listing = output(executable, '--list-langs').splitlines()[0]
    data_path = Path(listing.split('"')[1])
    for language in ('eng', 'osd'):
        source = data_path / f'{language}.traineddata'
        if not source.is_file():
            raise RuntimeError(f'Missing OCR language data: {source}')
        shutil.copy2(source, dest / 'tessdata' / source.name)
    (dest / 'licenses' / 'sources.json').write_text(json.dumps(sorted(formulas), indent=2))
    run(dest / 'bin' / 'tesseract', '--list-langs', env={**os.environ, 'TESSDATA_PREFIX': str(dest / 'tessdata')})

def main():
    if sys.platform != 'darwin':
        raise SystemExit('Build the Mac app on a Mac. Build each CPU architecture on its matching host.')
    if not shutil.which('uv'):
        raise SystemExit('Install the build-time Python manager first: brew install uv')
    BUILD.mkdir(parents=True, exist_ok=True)
    downloads = ROOT / 'build' / 'mac-python'
    run('uv', 'python', 'install', '3.13.16', '--install-dir', downloads, '--no-bin', '--cache-dir', ROOT / 'build/uv-cache')
    target = 'aarch64' if ARCH == 'arm64' else 'x86_64'
    installations = sorted(downloads.glob(f'cpython-3.13.16-macos-{target}-none'))
    if not installations:
        raise RuntimeError('Could not locate the standalone Python download.')
    if RUNTIME.exists():
        shutil.rmtree(RUNTIME)
    shutil.copytree(installations[-1], RUNTIME / 'python', symlinks=True)
    python = RUNTIME / 'python/bin/python3'
    run('uv', 'pip', 'install', '--python', python, '--break-system-packages', '--cache-dir', ROOT / 'build/uv-cache',
        '-r', ROOT / 'desktop/requirements-mac.lock', ROOT)
    # Keep installers and bytecode with absolute build paths out of the shipped runtime.
    for cache in RUNTIME.rglob('__pycache__'):
        shutil.rmtree(cache)
    bundle_ocr()
    iconset = BUILD / 'Recall.iconset'
    iconset.mkdir(exist_ok=True)
    for size in (16, 32, 128, 256, 512):
        for scale in (1, 2):
            name = f'icon_{size}x{size}' + ('@2x' if scale == 2 else '') + '.png'
            run('sips', '-z', size * scale, size * scale, ROOT / 'desktop/icon.png', '--out', iconset / name, stdout=subprocess.DEVNULL)
    run('iconutil', '-c', 'icns', iconset, '-o', BUILD / 'Recall.icns')
    (RUNTIME / 'build-info.json').write_text(json.dumps({'architecture': ARCH, 'python': output(python, '--version')}, indent=2))
    print(f'Ready: {RUNTIME} ({ARCH})', flush=True)

if __name__ == '__main__':
    main()
