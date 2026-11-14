"""Copy the playback plugin set and its imported SDK DLLs using MSVC DUMPBIN."""
import json
from pathlib import Path
import re
import shutil
import subprocess

# MP4/H.264/H.265/AV1/AAC, Windows hardware decoding, software fallback and PCM tempo.
# AVI/JPEG also support the same-production-pipeline synthetic verification fixtures.
PLUGINS = (
    'coreelements', 'app', 'playback', 'typefindfunctions', 'isomp4', 'videoparsersbad',
    'audioparsers', 'audioconvert', 'audioresample', 'audiofx', 'volume',
    'autodetect', 'wasapi', 'wasapi2', 'd3d11', 'd3d12', 'libav',
    'videoconvertscale', 'soup', 'subparse', 'avi', 'jpeg',
)


def stage(gst, destination, installation):
    compilers = sorted((Path(installation) / 'VC/Tools/MSVC').glob('*/bin/Hostx64/x64/dumpbin.exe'), reverse=True)
    if not compilers:
        raise ValueError('MSVC DUMPBIN is required to resolve runtime imports')
    dumpbin = compilers[0]
    available = {path.name.lower(): path for path in (gst / 'bin').glob('*.dll')}
    roots = [gst / 'lib/gstreamer-1.0' / f'gst{name}.dll' for name in PLUGINS]
    roots.append(gst / 'libexec/gstreamer-1.0/gst-plugin-scanner.exe')
    # The control worker loads this DLL explicitly rather than through a PE import.
    roots.append(gst / 'bin/gstreamer-1.0-0.dll')
    pending = roots.copy()
    included = {}
    while pending:
        path = pending.pop()
        name = path.name.lower()
        if name in included:
            continue
        if not path.is_file():
            raise ValueError('required playback file missing: ' + name)
        included[name] = path
        output = subprocess.check_output([str(dumpbin), '/NOLOGO', '/DEPENDENTS', str(path)], encoding='utf-8', errors='replace')
        for dependency in re.findall(r'^\s+([\w.-]+\.dll)\s*$', output, re.MULTILINE | re.IGNORECASE):
            if dependency.lower() in available:
                pending.append(available[dependency.lower()])
    files = []
    for path in sorted(included.values()):
        relative = path.relative_to(gst)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        files.append(dict(path=relative.as_posix(), bytes=path.stat().st_size))
    (destination / 'playback-files.json').write_text(json.dumps(dict(plugins=list(PLUGINS), files=files), indent=2), encoding='utf-8')
