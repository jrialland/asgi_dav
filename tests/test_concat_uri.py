from asgi_dav import concat_uri

def test_concat_uri():
    assert concat_uri("foo", "bar") == "foo/bar"
    assert concat_uri("foo/", "bar") == "foo/bar"
    assert concat_uri("foo", "/bar") == "foo/bar"
    assert concat_uri("foo/", "/bar") == "foo/bar"
    assert concat_uri("foo", "bar/") == "foo/bar"
    assert concat_uri("foo/", "bar/") == "foo/bar"
    assert concat_uri("foo/", "/bar/") == "foo/bar"
    assert concat_uri("foo", "/bar/") == "foo/bar"
    assert concat_uri("/foo", "bar") == "/foo/bar"
    assert concat_uri("/foo/", "bar") == "/foo/bar"
    assert concat_uri("/foo", "/bar") == "/foo/bar"
    assert concat_uri("", "foo") == "foo"
    assert concat_uri("", "/foo") == "foo"
    assert concat_uri("/", "foo") == "/foo"