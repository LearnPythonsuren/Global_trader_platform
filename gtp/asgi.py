"""ASGI entrypoint.

Run locally with ``uvicorn gtp.asgi:app`` (or ``python -m gtp serve``).
Vercel loads this module through ``[tool.vercel] entrypoint`` in pyproject.toml.
"""

from .api.app import create_app

app = create_app()
