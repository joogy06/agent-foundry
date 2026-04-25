"""Fixture: shared redis helper with publish_to_stream wrapper."""


def publish_to_stream(r, stream, data, maxlen=10000):
    return r.xadd(stream, data, maxlen=maxlen)
