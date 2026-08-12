"""Graph-domain compatibility facade."""

from .bridge import install
from .graph import Graph, Node

install("graph", globals())
