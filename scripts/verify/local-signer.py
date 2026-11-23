"""Verify packaged Windows signing with fictional device data, never contact upstream."""
import argparse
import json
import os
from pathlib import Path
import sys
import time
import urllib.error
import urllib.request

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
from lazybuddy_hongguo.signer import LocalSigner


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    os.environ.pop('LAZYBUDDY_HONGGUO_SIGNER_URL',None)
    os.environ['LAZYBUDDY_DEPENDENCY_HONGGUO_SIGNER_DIR']=str(args.runtime.resolve())
    signer=LocalSigner();started=time.monotonic()
    report={}
    try:
        environment=signer.environment()
        process=signer.process
        workspace=Path(signer.workspace.name)
        report['startup_seconds']=round(time.monotonic()-started,2)
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        payload=json.dumps(dict(url='https://api5-normal-sinfonlineb.fqnovel.com/reading/bookapi/video_tab/multi_video_model/v1/?aid=6383&device_platform=android&device_id=1234567890123456789&iid=1234567890123456790&_rticket='+str(int(time.time()*1000)))).encode()
        address=environment['LAZYBUDDY_HONGGUO_SIGNER_URL']+'/feature-hash'
        try:
            opener.open(urllib.request.Request(address,data=payload,headers={'Content-Type':'application/json'}),timeout=10)
            raise AssertionError('unsigned local access accepted')
        except urllib.error.HTTPError as error:
            if error.code!=401:raise
            report['token_required']=True
        headers={'Content-Type':'application/json','X-Signer-Token':environment['LAZYBUDDY_HONGGUO_SIGNER_TOKEN']}
        with opener.open(urllib.request.Request(address,data=payload,headers=headers),timeout=15) as response:
            result=json.loads(response.read(65537))
        names=['X-Gorgon','X-Helios','X-Medusa','X-Khronos','X-Argus','X-Ladon']
        report['signature_headers_present']={name:bool(result.get('headers',{}).get(name)) for name in names}
        if not all(report['signature_headers_present'].values()):raise AssertionError('missing signature headers')
    finally:
        signer.close()
    report['process_reaped']=process.poll() is not None
    report['workspace_removed']=not workspace.exists()
    if not report['process_reaped'] or not report['workspace_removed']:raise AssertionError('runtime not reclaimed')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report))


if __name__=='__main__':main()
