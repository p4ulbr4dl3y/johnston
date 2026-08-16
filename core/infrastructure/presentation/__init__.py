"""Presentation-layer rendering helpers.

Pure view helpers that build short, human-readable display labels for rendered
output. This is presentation logic (Textual-escaping, chip labels) and is kept
out of the domain/application layers so business logic stays free of rendering
concerns. Lives in ``core.infrastructure`` so core widgets (which import core)
can share real tool-display logic without reaching into the ``widgets`` UI tree.
"""
