from asgi_dav.utils import to_rfc_1123, get_parent_href
import datetime

def test_to_rfc_1123():
    dt = datetime.datetime(2021, 1, 1, 0, 0, 0)
    to_rfc_1123(dt)

def test_to_rfc_1123_epoch():
    dt = datetime.datetime.min
    to_rfc_1123(dt)

def test_parent_href():
    assert get_parent_href("/a/b/c") == "/a/b/"
    assert get_parent_href("/a/b/c/") == "/a/b/"
    assert get_parent_href("/a/") == "/"
    assert get_parent_href("/") == "/"