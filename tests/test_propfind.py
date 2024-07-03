import pytest
from async_asgi_testclient import TestClient
from asgi_dav import DAVApp
from fs.memoryfs import MemoryFS

@pytest.mark.asyncio
async def test_propfind_404():
    fs = MemoryFS()
    app = DAVApp(fs)
    async with TestClient(app) as client:
        response = await client.open("/foo", method="PROPFIND")
        assert response.status_code == 404
        assert response.text == "Not found"

@pytest.mark.asyncio
async def test_propfind_file_200():
    fs = MemoryFS()
    fs.writetext("/foo", "foo")
    app = DAVApp(fs)
    async with TestClient(app) as client:
        response = await client.open("/foo", method="PROPFIND", headers={"Depth": "0"})
        assert response.status_code == 207

@pytest.mark.asyncio
async def test_propfind_folder_207():
    fs = MemoryFS()
    fs.makedir("/foo")
    fs.writetext("/foo/bar", "bar")
    fs.writetext("/foo/baz", "baz")
    app = DAVApp(fs)
    async with TestClient(app) as client:
        response = await client.open("/foo", method="PROPFIND", headers={"Depth": "1"})
        assert response.status_code == 207

@pytest.mark.asyncio
async def test_propfind_folder_depth_infinity():
    fs = MemoryFS()
    fs.makedir("/foo")
    fs.writetext("/foo/bar", "bar")
    fs.writetext("/foo/baz", "baz")
    fs.makedir("/foo/qux")
    fs.writetext("/foo/qux/quux", "quux")
    fs.writetext("/foo/qux/corge", "corge")
    app = DAVApp(fs)
    async with TestClient(app) as client:
        response = await client.open("/foo", method="PROPFIND", headers={"Depth": "infinity"})
        assert response.status_code == 207