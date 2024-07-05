from asgi_dav import DAVApp
from fs.osfs import OSFS
from argparse import ArgumentParser

import uvicorn

def main():
    parser = ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8000, type=int)
    args = parser.parse_args()

    uvicorn.run(DAVApp(OSFS("."), path_prefix='/WEBDAV'), host=args.host, port=args.port)


main()
