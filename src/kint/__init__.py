"""kint: Sibyl Memory that outlives the laptop.

A drop-in MCP server that wraps Sibyl Memory's own server untouched, encrypts
the memory to the user's wallet, keeps it on Base, restores it on any machine
by wallet connect, and verifies every recalled row against the chain before
the agent acts on it.
"""

__version__ = "0.3.0"
