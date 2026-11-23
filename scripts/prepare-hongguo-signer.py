"""Build pinned upstream signer with an explicit private JDK; never install system Java."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT=Path(__file__).resolve().parents[1]
REVISION='32d2a8c6387d4a63fe9262525531dd9d363f9833'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True,help='extracted upstream checkout at the documented revision')
    parser.add_argument('--jdk',type=Path,required=True,help='private Windows x64 JDK 21 directory')
    parser.add_argument('--gradle',type=Path,help='optional private Gradle executable')
    args=parser.parse_args()
    source=args.source.resolve();jdk=args.jdk.resolve()
    output=ROOT/'target/runtimes/hongguo-signer'
    if output.exists():raise ValueError('runtime output already exists; preserve or remove it explicitly')
    if not (source/'signer/gradlew.bat').is_file() or not (jdk/'bin/jlink.exe').is_file():raise ValueError('source or JDK missing')
    environment=os.environ.copy()
    environment.update(JAVA_HOME=str(jdk),GRADLE_USER_HOME=str(ROOT/'target/cache/gradle'))
    subprocess.run([str(args.gradle.resolve() if args.gradle else source/'signer/gradlew.bat'),'--no-daemon','installDist'],cwd=source/'signer',env=environment,check=True)
    dist=source/'signer/build/install/openhongguo-signer'
    output.parent.mkdir(parents=True,exist_ok=True)
    try:
        subprocess.run([str(jdk/'bin/jlink.exe'),'--add-modules',
            'java.base,java.logging,java.management,java.desktop,java.naming,jdk.httpserver,jdk.unsupported,jdk.crypto.ec',
            '--strip-debug','--no-header-files','--no-man-pages','--output',str(output/'java')],check=True)
        shutil.copytree(dist/'lib',output/'lib')
        shutil.copytree(source/'signer',output/'source/signer',ignore=shutil.ignore_patterns('build','.gradle'))
        shutil.copyfile(source/'LICENSE',output/'source/LICENSE')
        shutil.copyfile(jdk/'NOTICE',output/'JAVA-NOTICE')
        (output/'provenance.json').write_text(json.dumps(dict(upstream='https://github.com/beilunyang/openhongguo',revision=REVISION),indent=2)+'\n',encoding='utf-8')
    except BaseException:
        if output.is_dir():shutil.rmtree(output)
        raise
    print(output)


if __name__=='__main__':main()
