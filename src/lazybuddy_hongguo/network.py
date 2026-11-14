"""Keep child Go/Rust helpers on the Python service's selected proxy route."""
import os
import urllib.request

def configure_helpers():
    for scheme,address in urllib.request.getproxies().items():
        if scheme in ('http','https','all','no'):
            os.environ.setdefault(scheme.upper()+'_PROXY',address)
