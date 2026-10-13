#!/usr/bin/env python3
"""Local GUI. Worker jobs survive closing the browser or stopping this server."""
import sys
from pathlib import Path
ROOT=Path(__file__).absolute().parents[1]
sys.path.insert(0,str(ROOT))
from src.web import make_server

if __name__=='__main__':
    server=make_server(ROOT)
    print('TeraFlow migration lab: http://127.0.0.1:18092/',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()
