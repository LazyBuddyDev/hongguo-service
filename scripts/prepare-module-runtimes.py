"""Prepare project-private, pinned Python files and Windows cp313 wheels."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import urllib.request
import zipfile
import tomllib

ROOT=Path(__file__).resolve().parents[1]
SDK=Path(__import__('os').environ.get('LAZYBUDDY_SDK_DIR',str(ROOT/'target/native-player-sdk')))
DOWNLOADS=ROOT/'target/release-runtime-downloads'
PYTHON=SDK/'lazybuddy-python'
WHEELS=SDK/'lazybuddy-python-wheels'


def main():
    DOWNLOADS.mkdir(parents=True,exist_ok=True)
    archive=DOWNLOADS/'python-3.13.5-embed-amd64.zip'
    if not (PYTHON/'python.exe').is_file():
        if not archive.is_file():
            urllib.request.urlretrieve('https://www.python.org/ftp/python/3.13.5/'+archive.name,archive)
        if hashlib.sha256(archive.read_bytes()).hexdigest()!='7d2650fd9d1b9d002d4a315d5f354247fd6a44f30517c7ef577b08f57a0fb6d9':
            raise ValueError('Python checksum mismatch')
        PYTHON.mkdir(parents=True,exist_ok=True)
        with zipfile.ZipFile(archive) as source:
            source.extractall(PYTHON)
        archive.unlink()
    subprocess.run([sys.executable,'-m','pip','download','--disable-pip-version-check','--no-cache-dir',
        '--only-binary=:all:','--python-version','3.13','--implementation','cp','--abi','cp313',
        '--platform','win_amd64','--dest',str(WHEELS),*tomllib.loads((ROOT/'pyproject.toml').read_text(encoding='utf-8'))['project']['dependencies']],check=True)
    for wheel in WHEELS.glob('*.whl'):
        distribution,version=wheel.name.split('-')[:2]
        with urllib.request.urlopen(f'https://pypi.org/pypi/{distribution}/{version}/json',timeout=30) as response:
            metadata=json.load(response)
        expected=next(item['digests']['sha256'] for item in metadata['urls'] if item['filename']==wheel.name)
        if hashlib.sha256(wheel.read_bytes()).hexdigest()!=expected:
            raise ValueError('wheel checksum mismatch')
    print('Private Python runtime and Windows cp313 wheels verified.')


if __name__=='__main__':
    main()
