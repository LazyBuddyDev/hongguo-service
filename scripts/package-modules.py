"""Stage optional packages without copying SDK headers, credentials or host binaries."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import os
import sys
import tomllib
import zipfile
from package_support import notices
from media_runtime_files import stage as stage_media_files

ROOT=Path(__file__).resolve().parents[1]
SDK=Path(os.environ.get('LAZYBUDDY_SDK_DIR',str(ROOT/'target/native-player-sdk')))


def copy_files(source,destination,pattern):
    destination.mkdir(parents=True,exist_ok=True)
    for path in source.glob(pattern):
        if path.is_file(): shutil.copyfile(path,destination/path.name)


def stage(identifier,destination,profile):
    destination.mkdir(parents=True,exist_ok=False)
    shutil.copyfile(ROOT/'module.json' if identifier=='hongguo' else ROOT/'contracts'/identifier/'module.json',destination/'module.json')
    if identifier=='python-runtime':
        if not (SDK/'lazybuddy-python/python.exe').is_file():raise ValueError('prepare private Python runtime first')
        shutil.copytree(SDK/'lazybuddy-python',destination/'bin')
    elif identifier=='hongguo':
        service=destination/'service'
        shutil.copytree(ROOT/'src/lazybuddy_hongguo',service/'lazybuddy_hongguo',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        shutil.copyfile(ROOT/'main.py',service/'main.py')
        runtime=service/'lazybuddy_hongguo/runtime'
        runtime.mkdir()
        for source in [ROOT/'target/hongguo-app-resolver.exe',ROOT/'search/target'/profile/'lazybuddy-hongguo-search.exe']:
            shutil.copyfile(source,runtime/source.name)
        wheels=list((SDK/'lazybuddy-python-wheels').glob('*.whl'))
        if len(wheels)!=5:raise ValueError('prepare the five pinned Python dependency wheels first')
        packages=service/'packages'
        subprocess.run([sys.executable,'-m','pip','install','--quiet','--disable-pip-version-check','--no-cache-dir',
            '--no-compile','--no-index','--no-deps','--only-binary=:all:','--python-version','3.13',
            '--implementation','cp','--abi','cp313','--platform','win_amd64','--target',str(packages),
            '--find-links',str(SDK/'lazybuddy-python-wheels'),
            *tomllib.loads((ROOT/'pyproject.toml').read_text(encoding='utf-8'))['project']['dependencies']],check=True)
        shutil.copyfile(ROOT/'vendor/openhongguo/LICENSE',destination/'openhongguo-LICENSE')
        shutil.copyfile(ROOT/'vendor/openhongguo/BRIEFDOCK.md',destination/'openhongguo-NOTICE.md')
        shutil.copyfile(SDK/'go/LICENSE',destination/'Go-LICENSE')
    elif identifier=='media-runtime':
        (destination/'service').mkdir()
        shutil.copyfile(ROOT/'runtimes/media/lazybuddy_media.py',destination/'service/lazybuddy_media.py')
        gst=SDK/'PFiles64/gstreamer/1.0/msvc_x86_64'
        if not (gst/'bin/gstreamer-1.0-0.dll').is_file():raise ValueError('prepare verified GStreamer runtime first')
        vswhere=Path(os.environ['ProgramFiles(x86)'])/'Microsoft Visual Studio/Installer/vswhere.exe'
        installation=subprocess.check_output([str(vswhere),'-latest','-products','*','-property','installationPath'],text=True).strip()
        stage_media_files(gst,destination/'runtime',installation)
        redistributable=sorted((Path(installation)/'VC/Redist/MSVC').glob('*/x64/Microsoft.VC*.CRT'),reverse=True)
        if not redistributable:raise ValueError('MSVC runtime redistribution files missing')
        copy_files(redistributable[0],destination/'runtime/bin','*.dll')
        for directory in ['etc','share/licenses']:
            shutil.copytree(gst/directory,destination/'runtime'/directory)
    if (ROOT/'LICENSE').is_file():
        shutil.copyfile(ROOT/'LICENSE',destination/'LICENSE')
    else:
        (destination/'NOTICE.txt').write_text('Development package. Project license is not yet confirmed; do not publish.\n',encoding='utf-8')
    if identifier=='hongguo':
        notices(destination/'licenses', ROOT/'search/Cargo.toml', ('lazybuddy-hongguo-search',))
        shutil.copyfile(ROOT/'README.md',destination/'README.md')
    manifest=json.loads((destination/'module.json').read_text(encoding='utf-8'))
    if not (destination/manifest['entrypoint']).is_file():raise ValueError('package entrypoint missing')
    return manifest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--modules',default='hongguo,python-runtime')
    parser.add_argument('--profile',choices=['debug','release'],default='release')
    parser.add_argument('--output',type=Path,default=ROOT/'target/packages')
    parser.add_argument('--base-url',default='https://example.invalid/lazybuddy')
    args=parser.parse_args()
    output=args.output.resolve()
    if not output.is_relative_to(ROOT/'target') or output.exists():raise ValueError('new output directory inside target required')
    output.mkdir(parents=True)
    catalog=[]
    for identifier in args.modules.split(','):
        if identifier not in ('hongguo','python-runtime','media-runtime'):raise ValueError('unknown module')
        directory=output/identifier
        manifest=stage(identifier,directory,args.profile)
        archive=output/f'{identifier}-{manifest["version"]}-windows-x86_64.zip'
        with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as package:
            for path in sorted(directory.rglob('*')):
                if path.is_file():package.write(path,path.relative_to(directory).as_posix())
        with archive.open('rb') as source:digest=hashlib.file_digest(source,'sha256').hexdigest()
        catalog.append(dict(id=identifier,name=manifest['name'],kind=manifest.get('kind','feature'),version=manifest['version'],target=manifest['target'],url=args.base_url.rstrip('/')+'/'+archive.name,
            sha256=digest,bytes=archive.stat().st_size,dependencies=manifest['dependencies']))
    (output/'catalog.json').write_text(json.dumps(dict(schema=1,packages=catalog),ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(output=str(output),packages=[dict(id=entry['id'],bytes=entry['bytes']) for entry in catalog])))


if __name__=='__main__':
    main()
