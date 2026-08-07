from __future__ import annotations

import asyncio
import json
from pathlib import Path
import subprocess
import sys

import httpx2

from tests.tools.mock_loader import MockLoader, normalize_mock_url, redact_sensitive_content


def test_mock_loader_matches_authenticated_requests_without_persisting_dsid(tmp_path: Path) -> None:
    account_dsid = "1234567890"
    authenticated_url = f"https://play.itunes.apple.com/playlist.m3u8?cc=US&dsid={account_dsid}"
    normalized_url = normalize_mock_url(url=authenticated_url)
    response_content = b"#EXTM3U\n"
    response_path = tmp_path / "response"
    response_path.write_bytes(response_content)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({normalized_url: response_path.name}), encoding="utf-8")

    loader = MockLoader(mock_data_dir=tmp_path)
    response = asyncio.run(loader.mock_send_handler(httpx2.Request("GET", authenticated_url)))

    assert response.content == response_content
    assert account_dsid not in manifest_path.read_text(encoding="utf-8")
    assert normalized_url.endswith("dsid=REDACTED")


def test_mock_fixture_content_redacts_configured_dsid() -> None:
    account_dsid = "1234567890"
    content = f'{{"dsid":"{account_dsid}"}}'.encode()

    redacted_content = redact_sensitive_content(content=content, sensitive_values=[account_dsid])

    assert account_dsid.encode() not in redacted_content
    assert b"REDACTED" in redacted_content


def test_mock_generator_help_smoke() -> None:
    script_path = Path(__file__).parent / "tools" / "generate_mock_data.py"
    result = subprocess.run(  # noqa: S603
        [sys.executable, str(script_path), "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "--dsid DSID" in result.stdout
