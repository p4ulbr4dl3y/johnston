"""Boundary adapters: the ONLY TUI modules allowed to import core.

``core_bridge`` is deliberately NOT re-exported here to keep the boundary
single.  Import it explicitly: ``from johnston.tui.adapters import core_bridge``.
"""
