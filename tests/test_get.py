import pytest
from async_asgi_testclient import TestClient
from asgi_dav import DAVApp
from fs.memoryfs import MemoryFS

@pytest.mark.asyncio
async def test_get_404():
    fs = MemoryFS()
    app = DAVApp(fs)
    async with TestClient(app) as client:
        response = await client.get("/foo")
        assert response.status_code == 404
        assert response.text == "Not found"

@pytest.mark.asyncio
async def test_get_file_200():
    fs = MemoryFS()
    fs.writetext("/foo", "foo")
    app = DAVApp(fs)

    async def on_file_downloaded(*args):
        print("file downloaded")

    app.on("file.downloaded", on_file_downloaded)
    
    async with TestClient(app) as client:
        response = await client.get("/foo")
        assert response.status_code == 200
        assert response.text == "foo"

@pytest.mark.asyncio
async def test_get_file_range():
    fs = MemoryFS()
    fs.writetext("/foo", "foobarfoobar")
    app = DAVApp(fs)
    async with TestClient(app) as client:
        response = await client.get("/foo", headers={"Range": "bytes=3-5"})
        assert response.status_code == 206
        assert response.text == "bar"

@pytest.mark.asyncio
async def test_get_dir_listing():
    fs = MemoryFS()
    fs.writetext("/foo", "foo")
    fs.writetext("/bar", "bar")
    app = DAVApp(fs)
    async with TestClient(app) as client:
        response = await client.get("/")
        assert response.status_code == 200
        print(response.text)
