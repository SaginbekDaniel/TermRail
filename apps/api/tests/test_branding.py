"""Public branding is TermRail everywhere a customer can see it (OpenAPI, PDF, repository files)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pymupdf

from tests.conftest import Actor
from tests.test_api_workflow import full_change_order

REPO = Path(__file__).resolve().parents[3]


async def test_openapi_is_branded_termrail(client) -> None:  # type: ignore[no-untyped-def]
    spec = (await client.get("/openapi.json")).json()
    assert spec["info"]["title"] == "TermRail API"


async def test_exported_pdf_is_branded_termrail(alice: Actor) -> None:
    co, export = await full_change_order(alice)
    pdf = await alice.get(f"/change-orders/{co['id']}/exports/{export['id']}/download")
    doc = pymupdf.open(stream=pdf.content, filetype="pdf")
    text = "".join(pg.get_text() for pg in doc)
    assert "TermRail" in text
    assert doc.metadata["author"] == "TermRail"


def test_repository_has_no_legacy_brand() -> None:
    r = subprocess.run([sys.executable, str(REPO / "scripts" / "verify_brand.py")], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout
