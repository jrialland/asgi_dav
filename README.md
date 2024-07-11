# Overview

This project is a minimalistic ASGI module that implements a WebDAV server. The focus is on simplicity rather than completeness, making it an easy-to-use solution for basic WebDAV needs.

# Features

Simplicity over Completeness: Designed to be straightforward and easy to use.

Basic WebDAV Functionality: Supports essential WebDAV operations.

Tested with Windows 11 Client: Ensured compatibility with the built-in WebDAV client in Windows 11.

# Limitations

No Resource Locking: This server does not support resource locking (yet)

# Dependencies
ASGI: The server is implemented as an ASGI module.
fs Module: Utilizes the [pyfilesystem2](https://github.com/PyFilesystem/pyfilesystem2) module for filesystem access.

# Installation
```shell
pip install git+https://github.com/jrialland/asgi_dav@main
```

# Usage (uvicorn)
```python
from asgi_dav import DAVApp
from fs.osfs import OSFS
import uvicorn

uvicorn.run(DAVApp(OSFS(".")))
```

# Usage (fastapi)


```python
from fastapi import FastAPI
from asgi_dav import DAVApp
from fs.memoryfs import MemoryFS # use an in-RAM filesystem for the example

app = FastAPI()

# Mount the DAVApp as a sub-application in FastAPI.
app.mount("/dav", DAVApp(MemoryFS()))

```

# Events

your program can be notified of filesystem changes : 

```python
from asgi_dav.events import FileUploadEvent

async def print_uploaded_file(evt:FileUploadEvent):
    print(f"File Uploaded : {evt.path}")

davApp = DAVApp(MemoryFS()))

davApp.on('file.uploaded', print_uploaded_file)

#[...]

```

# License

This project is licensed under the MIT License.
