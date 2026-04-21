"""Scraping pipeline for prices and ratings.

Modules in this package are split into two layers:

* **Parsers** (``apartments_com.py``, ``google_places.py``) \u2014 pure
  functions that take HTML strings and return dataclasses. No network,
  no Playwright; fully fixture-testable.
* **Services** (``price_service.py``, ``rating_service.py``) \u2014 glue
  that fetches HTML (via :mod:`app.scrapers.base`), calls the parser,
  and persists the result to the snapshot tables.
"""
