"""Decode a bounded cover in a private process. No network, URLs or files."""
import io,os,pathlib,struct,sys
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[2]/'packages'))

def decode(data):
    if not 0<len(data)<=4*1024*1024:raise ValueError('image_size')
    import pillow_heif
    if data[4:8]==b'ftyp':
        image=pillow_heif.open_heif(data)
        if not all(0<v<=4096 for v in image.size):raise ValueError('image_dimensions')
        image=image.to_pillow()
    else:
        from PIL import Image
        Image.MAX_IMAGE_PIXELS=4096*4096
        image=Image.open(io.BytesIO(data))
    if not all(0<v<=4096 for v in image.size):raise ValueError('image_dimensions')
    image.thumbnail((240,360));image=image.convert('RGBA')
    return struct.pack('>II',*image.size)+image.tobytes()

def main():
    if os.name!='nt':return 1
    import ctypes,msvcrt
    kernel=ctypes.WinDLL('kernel32');kernel.GetFileType.argtypes=[ctypes.c_void_p]
    if any(kernel.GetFileType(msvcrt.get_osfhandle(stream.fileno()))!=3 for stream in (sys.stdin,sys.stdout)):return 1
    try:
        result=decode(sys.stdin.buffer.read(4*1024*1024+1));sys.stdout.buffer.write(result);sys.stdout.buffer.flush();return 0
    except Exception:return 1
if __name__=='__main__':sys.exit(main())
