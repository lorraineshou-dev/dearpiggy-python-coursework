# Packaging utility only. Run main.py to start the game; see README.txt.
"""Build a self-contained coursework ZIP from an explicit file allowlist.

No configuration secrets, runtime data, original website, or installed packages
are included. Run with Python's standard library: python3 package_submission.py.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import zipfile

ROOT = Path(__file__).resolve().parent
TOP = 'Dear-Piggy-Python'
SOURCE_FILES = (
    'main.py', 'game.py', 'storage.py', 'views.py', 'ai_chat.py',
    'package_submission.py', 'catalogue.json', 'README.txt', 'TEST_RESULTS.txt',
    '.env.example', '.gitignore',
)
ASSET_SUFFIXES = {'.css', '.js', '.png', '.svg', '.jpg', '.jpeg', '.webp',
                  '.m4a', '.woff2', '.ttf', '.txt', '.md'}
TEXT_SUFFIXES = {'.py', '.json', '.txt', '.md', '.css', '.js', '.svg', '.example'}
COURSE_REPOSITORY = 'https://github.com/lorraineshou-dev/dearpiggy-python-coursework'


def ed_readme(commit):
    """Give the marker a version-specific download without a moving branch link."""
    return f'''DEAR PIGGY - ED SUBMISSION
==========================

This README.txt and all Python files must be uploaded to Ed. The full project
exceeds Ed's 2 MB limit because it includes illustrations, fonts, and music.
Those assets and the exact submitted Python code are hosted in this public
GitHub snapshot; no GitHub account is needed to download it.

FULL PROJECT DOWNLOAD (CODE + ALL ASSETS):
{COURSE_REPOSITORY}/archive/{commit}.zip

COMMIT RECORD AND TIMESTAMP:
{COURSE_REPOSITORY}/commit/{commit}

Submitted commit: {commit}
Course deadline: 1 November 2026, 11:59 pm Australia/Sydney (AEDT, UTC+11).
Please assess the snapshot identified above, not a later branch version.
The course requires external submission files to remain unchanged after the
deadline. This commit-specific link fixes the submitted version.

RUNNING THE SUBMISSION

1. Download the full project ZIP above and extract it. Open the extracted
   dearpiggy-python-coursework-<commit> folder containing main.py.
2. With Python 3.9 or newer, run: python3 main.py
   On Windows, run: py -3 main.py
3. Open http://127.0.0.1:4180 in a browser. Keep the terminal running;
   press Ctrl+C to stop. No pip packages or Node.js are required.

main.py is the entry point. Python implements rules, persistence, HTTP routes,
HTML rendering, and optional AI integration. This application uses a browser
GUI, local audio, and local HTTP networking; Ed's terminal cannot display it.
Core features run locally with no internet or API key. Optional OpenAI chat
requires the marker's own key and account; it is not needed for core marking.

The small Ed package contains every Python source file, tests, catalogue.json,
and these instructions. It intentionally omits static/; running the downloaded
full project is the simplest way to keep all necessary files together.

All 51 tests passed on Python 3.9.6 and 3.12.14 on macOS. AI tests use mocks.
Run the tests from the full project: python3 -m unittest discover -s tests -v

Detailed run instructions, GUI/audio/network disclosures, asset licences,
and AI-assistance disclosure follow below.

---------------- DETAILED APPLICATION README ----------------

''' + (ROOT / 'README.txt').read_text(encoding='utf-8')


def build_ed_package(files, commit):
    """Produce an Ed-sized folder and ZIP with all Python files and a pinned URL."""
    output = ROOT / 'dist' / 'Dear-Piggy-Ed-Submission.zip'
    folder = output.parent / 'Dear-Piggy-Ed-Submission'
    folder.mkdir(parents=True, exist_ok=True)
    entries = {path.relative_to(ROOT).as_posix(): path.read_bytes() for path in files
               if 'static' not in path.relative_to(ROOT).parts}
    entries['README.txt'] = ed_readme(commit).encode('utf-8')
    for name, content in entries.items():
        destination = folder / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    if output.stat().st_size >= 2_000_000 or any(len(content) >= 2_000_000 for content in entries.values()):
        raise ValueError('The Ed submission exceeds the 2 MB limit.')
    print(f'Created {output} ({output.stat().st_size:,} bytes, below 2 MB)')
    print(f'Upload README.txt and every .py file from {folder} to Ed.')


def submission_files():
    files = [ROOT / name for name in SOURCE_FILES]
    files += sorted((ROOT / 'tests').glob('test_*.py'))
    files += sorted(path for path in (ROOT / 'static').rglob('*')
                    if path.is_file() and path.suffix.lower() in ASSET_SUFFIXES
                    and not any(part.startswith('.') for part in path.relative_to(ROOT).parts))
    for path in files:
        if not path.is_file() or path.is_symlink() or ROOT not in path.resolve().parents:
            raise ValueError('Missing or unsafe submission file: ' + str(path.relative_to(ROOT)))
        if path.suffix in TEXT_SUFFIXES:
            content = path.read_text(encoding='utf-8')
            if re.search(r'(?:sk-(?:proj-)?|github_pat_|ghp_)[A-Za-z0-9_-]{24,}', content):
                raise ValueError('Possible credential detected in ' + str(path.relative_to(ROOT)))
    return files


def main():
    parser = argparse.ArgumentParser(description='Package the Dear Piggy coursework submission.')
    parser.add_argument('--ed-commit', help='40-character published GitHub commit for an Ed-sized submission.')
    options = parser.parse_args()
    files = submission_files()
    if options.ed_commit:
        if not re.fullmatch(r'[0-9a-f]{40}', options.ed_commit):
            parser.error('--ed-commit must be the full 40-character Git commit ID')
        return build_ed_package(files, options.ed_commit)
    manifest = {path.relative_to(ROOT).as_posix(): {
        'bytes': path.stat().st_size,
        'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
    } for path in files}
    output = ROOT / 'dist' / 'Dear-Piggy-Python-Coursework.zip'
    output.parent.mkdir(exist_ok=True)
    temporary = output.with_suffix('.zip.tmp')
    with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            archive.write(path, TOP + '/' + path.relative_to(ROOT).as_posix())
        archive.writestr(TOP + '/MANIFEST.json', json.dumps(manifest, indent=2) + '\n')
    with zipfile.ZipFile(temporary) as archive:
        bad_file = archive.testzip()
        if bad_file:
            raise ValueError('ZIP verification failed: ' + bad_file)
    temporary.replace(output)
    checksum = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix('.zip.sha256').write_text(checksum + '  ' + output.name + '\n', encoding='ascii')
    print(f'Created {output}')
    print(f'{len(files)} source/asset files + MANIFEST.json; {output.stat().st_size:,} bytes')
    print(f'SHA-256: {checksum}')


if __name__ == '__main__':
    main()
