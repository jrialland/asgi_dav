"""
Test that the app can be deployed behind a prefix path.
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient
from fs.memoryfs import MemoryFS
from asgi_dav import DAVApp


def test_subpath():
    memfs = MemoryFS()
    memfs.writetext("/foo", "bar")

    app = FastAPI()
    app.mount("/WEBDAV", DAVApp(memfs))

    client = TestClient(app)
    response = client.get("/WEBDAV/foo")
    assert response.status_code == 200
    assert response.text == "bar"


def test_subpath_collection():
    memfs = MemoryFS()
    memfs.makedir("/foo")
    memfs.writetext("/foo/bar", "baz")

    app = FastAPI()
    app.mount("/WEBDAV", DAVApp(memfs))

    client = TestClient(app)
    response = client.get("/WEBDAV")
    assert response.status_code == 200
    assert "/WEBDAV/foo" in response.text


def test_propfind_collection():
    memfs = MemoryFS()
    memfs.makedir("/foo")
    memfs.writetext("/foo/bar", "baz")

    app = FastAPI()
    app.mount("/WEBDAV", DAVApp(memfs))

    client = TestClient(app)
    response = client.request("PROPFIND", "/WEBDAV/foo", headers={"Depth": "0"})
    assert response.status_code == 207
    assert "<D:href>/WEBDAV/foo</D:href>" in response.text
