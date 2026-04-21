"""End-to-end smoke suite.

Gated on the ``E2E=1`` environment variable so a normal ``pytest`` run
never touches the live network, ORS quota, or scrape targets. Invoked
from :file:`Makefile` via ``make smoke-e2e``.
"""
