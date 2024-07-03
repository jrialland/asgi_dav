import pytest
from async_asgi_testclient import TestClient
from asgi_dav import DAVApp
from fs.memoryfs import MemoryFS

@pytest.mark.asyncio
async def test_proppatch():
    xml = b'<?xml version="1.0" encoding="utf-8" ?><D:propertyupdate xmlns:D="DAV:" xmlns:Z="urn:schemas-microsoft-com:"><D:set><D:prop><Z:Win32FileAttributes>00000020</Z:Win32FileAttributes></D:prop></D:set></D:propertyupdate>'
    fs = MemoryFS()
    fs.makedirs("/yyy")
    fs.writetext("/yyy/xxx", "foo")
    app = DAVApp(fs)
    async with TestClient(app) as client:
        response = await client.open("/yyy/xxx", method="PROPPATCH", data=xml)
        assert response.status_code == 207
