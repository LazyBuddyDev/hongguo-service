"""Stage an explicit browser contract fixture; it has no accounts or decoder dependency."""
import argparse
import json
from pathlib import Path
import shutil

ROOT=Path(__file__).resolve().parents[2]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output',type=Path,required=True)
parser.add_argument('--runtime-packages',type=Path,default=ROOT/'target/packages-current')
args=parser.parse_args()
output=args.output.resolve()
if not output.is_relative_to(ROOT/'target') or output.exists():raise ValueError('new fixture directory inside target required')
output.mkdir(parents=True)
shutil.copytree(args.runtime_packages/'python-runtime',output/'python-runtime')
service=output/'hongguo/service';service.mkdir(parents=True)
shutil.copytree(ROOT/'src/lazybuddy_hongguo',service/'lazybuddy_hongguo',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
shutil.copytree(args.runtime_packages/'hongguo/service/packages',service/'packages')
shutil.copyfile(Path(__file__).with_name('browser_fixture.py'),service/'main.py')
manifest=json.loads((ROOT/'module.json').read_text(encoding='utf-8'))
manifest['dependencies']=[row for row in manifest['dependencies'] if row['id']=='python-runtime']
(output/'hongguo/module.json').write_text(json.dumps(manifest,ensure_ascii=False),encoding='utf-8')
print(output)
