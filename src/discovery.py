"""Filesystem discovery and directory classification, independent of indexing."""
from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
import sys


@dataclass(frozen=True)
class DirectoryDecision:
    skip: bool
    reason: str | None = None
    rule: str | None = None


def classify_directory(path: Path) -> DirectoryDecision:
    """Inspect names and immediate markers, never recursively scan contents."""
    names = {
        '.git': ('Git internals', 'vcs.git'),
        '.hg': ('Mercurial internals', 'vcs.hg'),
        '.svn': ('Subversion internals', 'vcs.svn'),
        '.bzr': ('Bazaar internals', 'vcs.bzr'),
        '__pycache__': ('Python bytecode cache', 'cache.python'),
        '.pytest_cache': ('Pytest cache', 'cache.pytest'),
        '.mypy_cache': ('Mypy cache', 'cache.mypy'),
        '.ruff_cache': ('Ruff cache', 'cache.ruff'),
        '.hypothesis': ('Hypothesis test data cache', 'cache.hypothesis'),
        '.tox': ('Tox environments', 'python.tox'),
        '.nox': ('Nox environments', 'python.nox'),
        '.idea': ('IDE metadata', 'ide.idea'),
    }
    if path.name in names:
        reason, rule = names[path.name]
        return DirectoryDecision(True, reason, rule)
    if (path / 'pyvenv.cfg').is_file():
        return DirectoryDecision(True, 'Python virtual environment', 'python.venv')
    if (path / 'conda-meta/history').is_file():
        return DirectoryDecision(True, 'Conda environment', 'python.conda')
    if path.name in {'.venv', 'venv'} and (
            (path / 'bin/python').exists() or (path / 'Scripts/python.exe').is_file()):
        return DirectoryDecision(True, 'Python environment layout', 'python.environment-layout')

    # Package metadata detects arbitrarily named installs such as .grader.
    # Require two valid distributions AND package code, not suffixes alone.
    distributions = 0
    package_code = False
    node_package = False
    with os.scandir(path) as entries:
        for entry in entries:
            child = path / entry.name
            if entry.is_dir(follow_symlinks=False):
                if entry.name.endswith('.dist-info'):
                    if (child / 'METADATA').is_file() and (child / 'RECORD').is_file():
                        distributions += 1
                elif (child / '__init__.py').is_file():
                    package_code = True
                if path.name == 'node_modules' and (child / 'package.json').is_file():
                    node_package = True
            elif entry.is_file(follow_symlinks=False) and entry.name.endswith('.py'):
                package_code = True
            if distributions >= 2 and package_code:
                return DirectoryDecision(True, 'Installed Python dependencies', 'python.installed-packages')
            if node_package:
                return DirectoryDecision(True, 'Installed Node dependencies', 'node.dependencies')
    if path.name == 'node_modules' and (path / '.package-lock.json').is_file():
        return DirectoryDecision(True, 'Installed Node dependencies', 'node.dependencies')

    parent = path.parent
    frameworks = {
        '.next': ('Next.js output', 'node.next', ('next.config.js', 'next.config.mjs', 'next.config.ts')),
        '.nuxt': ('Nuxt output', 'node.nuxt', ('nuxt.config.js', 'nuxt.config.ts')),
        '.svelte-kit': ('SvelteKit output', 'node.sveltekit', ('svelte.config.js', 'svelte.config.ts')),
    }
    if path.name in frameworks:
        reason, rule, markers = frameworks[path.name]
        if (parent / 'package.json').is_file() and any((parent / marker).is_file() for marker in markers):
            return DirectoryDecision(True, reason, rule)
    if path.name == 'build' and (parent / 'gleam.toml').is_file():
        return DirectoryDecision(True, 'Gleam build output and dependencies', 'build.gleam')
    if path.name == 'target' and (parent / 'Cargo.toml').is_file() and (path / '.rustc_info.json').is_file():
        return DirectoryDecision(True, 'Rust build output', 'build.rust')
    if path.name == 'obj' and (path / 'project.assets.json').is_file() and (
            any(parent.glob('*.csproj')) or any(parent.glob('*.fsproj'))):
        return DirectoryDecision(True, '.NET intermediate output', 'build.dotnet')
    if path.name == '.gradle' and any((parent / marker).is_file() for marker in (
            'build.gradle', 'build.gradle.kts', 'settings.gradle', 'settings.gradle.kts')):
        return DirectoryDecision(True, 'Gradle project cache', 'cache.gradle')
    if path.name == 'cache' and parent.name == '.angular' and (parent.parent / 'angular.json').is_file():
        return DirectoryDecision(True, 'Angular cache', 'cache.angular')
    if path.suffix == '.app' and (path / 'Contents/Info.plist').is_file() and (path / 'Contents/MacOS').is_dir():
        return DirectoryDecision(True, 'macOS application bundle', 'bundle.macos-app')
    return DirectoryDecision(skip=False)


def use_git_ignore(file_path: str):
    try:
        result = subprocess.run(
            ["git", "-C", str(file_path), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False

def is_git_ignored(file_path: str | Path) -> bool:
    path = Path(file_path).resolve()
    working_directory = path if path.is_dir() else path.parent
    result = subprocess.run(
        ['git', '-C', str(working_directory), 'check-ignore', '-q', '--', str(path)],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    raise ValueError(f'Git ignore check failed for {path}: {result.stderr.strip()}')


def discover_files(file_or_dir: str, exclude: list[str] | None = None, *,
                   supported_suffixes: frozenset[str] | None = None) -> list[str]:
    """Complete filtered discovery before permitting index mutations."""
    path = Path(file_or_dir).resolve()
    if not path.exists():
        raise FileNotFoundError(f"File/directory not found: {path}")
    single_file = path.is_file()
    suffixes = supported_suffixes if supported_suffixes is not None else frozenset({'.py'})
    if single_file and path.suffix.lower() not in suffixes:
        if supported_suffixes is None:
            raise ValueError('Please provide a Python file or directory')
        raise ValueError(f'Unsupported file type: {path.suffix}')
    if not single_file and not path.is_dir():
        raise ValueError(f'Not a file or directory: {path}')

    excluded = {Path(p).expanduser().resolve() for p in exclude or []}
    git_available = use_git_ignore(path.parent if single_file else path)

    def is_excluded(candidate):
        resolved = candidate.resolve()
        return any(resolved.is_relative_to(item) for item in excluded)

    def keep_directory(candidate):
        decision = classify_directory(candidate)
        if decision.skip:
            print(f'Skipping {candidate}: {decision.reason} [{decision.rule}]', file=sys.stderr)
        return not decision.skip

    if is_excluded(path) or (not single_file and not keep_directory(path)):
        return []
    if git_available and is_git_ignored(path):
        return []
    if single_file:
        return [str(path)]

    def fail_on_error(error):
        raise error

    paths = []
    for root, dirs, files in os.walk(path, onerror=fail_on_error):
        parent = Path(root)
        dirs[:] = [name for name in dirs
                   if not (parent / name).is_symlink()
                   and not is_excluded(parent / name)
                   and keep_directory(parent / name)
                   and not (git_available and is_git_ignored(parent / name))]
        paths.extend(str(parent / name) for name in files
                     if (parent / name).suffix.lower() in suffixes
                     and not is_excluded(parent / name)
                     and not (git_available and is_git_ignored(parent / name)))
    return sorted(paths)


