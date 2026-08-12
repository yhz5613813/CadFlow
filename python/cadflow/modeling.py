"""Modeling domain facade; implementations are selected by the backend."""

from .bridge import install

install("operations", globals())
