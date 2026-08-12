"""Serialization domain facade for Model JSON and replay."""

from .bridge import install

install("serializer", globals())
