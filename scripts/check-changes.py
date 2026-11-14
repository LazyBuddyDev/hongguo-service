"""Run affected service unit tests; real-account and GUI checks remain explicit."""
import argparse
from pathlib import Path
import subprocess
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]

def select(paths):
    modules=set()
    for name in paths:
        path=Path(name)
        if name.startswith('tests/test_') and path.suffix=='.py':modules.add(path.stem)
        if name.startswith('src/lazybuddy_hongguo/'):
            relative=path.relative_to('src/lazybuddy_hongguo').with_suffix('').as_posix().replace('/','_')
            module='test_'+relative
            if (ROOT/'tests'/f'{module}.py').is_file():modules.add(module)
            if relative in ('media','protocol','backend_progressive'):modules.add('test_browser_playback')
            if relative in ('backend_app_input','backend_input'):modules.add('test_backend_media')
            if relative=='__main__':modules.add('test_protocol')
        if name in ('scripts/check-changes.py','.github/workflows/checks.yml'):modules.add('test_selection')
        if name in ('scripts/toolchain_paths.py','scripts/package-modules.py','scripts/prepare-module-runtimes.py','scripts/build-hongguo-resolver.ps1','scripts/prepare-media-sdk.ps1'):modules.add('test_toolchain_paths')
    return sorted(modules)

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--base');args=parser.parse_args()
    base=args.base
    if not base or set(base)=={'0'}:
        base=subprocess.check_output(['git','merge-base','HEAD','origin/main'],text=True,cwd=ROOT).strip()
        if base==subprocess.check_output(['git','rev-parse','HEAD'],text=True,cwd=ROOT).strip():base='HEAD^'
    paths=subprocess.check_output(['git','diff','--name-only',base,'HEAD'],text=True,cwd=ROOT).splitlines()
    modules=select(paths);print('Affected unit modules: '+', '.join(modules),flush=True)
    sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tests')]
    if modules and not unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromNames(modules)).wasSuccessful():raise SystemExit(1)
    if any(name.startswith('runtimes/media/') for name in paths):subprocess.run([sys.executable,'-B','runtimes/media/test_protocol.py'],cwd=ROOT,check=True)
    if any(name.startswith('search/') for name in paths):subprocess.run(['cargo','test','--locked','--manifest-path','search/Cargo.toml'],cwd=ROOT,check=True)
    if any(name.startswith(('resolver/','vendor/openhongguo/')) for name in paths):subprocess.run(['go','test','./...'],cwd=ROOT/'resolver',check=True)

if __name__=='__main__':main()
