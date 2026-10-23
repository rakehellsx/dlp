#!/usr/bin/env python3
"""Compatibility launcher for the C++ dlpcenter server; no Python HTTP API remains."""
import argparse
import os
from pathlib import Path

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host',default=os.environ.get('DLP_HTTP_HOST','127.0.0.1'))
    parser.add_argument('--port',type=int,default=int(os.environ.get('DLP_HTTP_PORT','8091')))
    args=parser.parse_args()
    root=Path(__file__).resolve().parent
    default_binary=root/('dlpcenter/build/Release/dlpcenter.exe' if os.name=='nt' else 'dlpcenter/build/dlpcenter')
    binary=Path(os.environ.get('DLP_BINARY',default_binary)).resolve()
    if not binary.is_file():raise SystemExit('请先构建 C++ 服务：cmake -S dlpcenter -B dlpcenter/build && cmake --build dlpcenter/build -j2')
    os.environ['DLP_HTTP_HOST']=args.host;os.environ['DLP_HTTP_PORT']=str(args.port)
    os.chdir(root);os.execv(binary,[str(binary)])
