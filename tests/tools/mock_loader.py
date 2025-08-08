from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import httpx


class MockLoader:
    """
    An asynchronous mock loader for HTTP requests, designed to load mock data from a specified directory.
    """
    def __init__(self, mock_data_dir: Path | str, logger: logging.Logger | None = None):
        self.mock_data_dir = Path(mock_data_dir)
        self.logger = logger or logging.getLogger(__name__)
        self._manifest: dict[str, Path] = {}
        self.logger.info(f"Mock data initialized with using the data on: {self.mock_data_dir}")

        manifest_paths = list(self.mock_data_dir.rglob("manifest.json"))

        if not manifest_paths:
            raise FileNotFoundError(f"No manifest file was found in {self.mock_data_dir}.")

        for manifest_path in manifest_paths:
            self.logger.info(f"Loading manifest from {manifest_path}...")

            try:
                manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    
                for url, filename in manifest_data.items():
                    self._manifest[url] = manifest_path.parent / filename

                self.logger.info(f"Manifest {manifest_path} loaded successfully.")

            except json.JSONDecodeError:
                self.logger.exception(f"Failed to decode manifest file: {manifest_path}")

            except Exception:
                self.logger.exception(f"Failed to load manifest file: {manifest_path}", exc_info=True)

        if not self._manifest:
            raise ValueError("No valid mock data found in any manifest files.")

        self.logger.info(f"Loaded {len(self._manifest)} mock data entries from {len(manifest_paths)} manifests.")

    async def mock_send_handler(self, request: httpx.Request, *args: Any, **kwargs: Any) -> httpx.Response:  # noqa: ARG002
        """An async handler to be used as a side_effect for a patched httpx.AsyncClient.send."""
        url_str = str(request.url)

        if url_str not in self._manifest:
            raise KeyError(f"Mock data not found for URL: {url_str}")

        response_path = self._manifest[url_str]
        response_content = response_path.read_bytes()

        return httpx.Response(
            status_code=200,
            content=response_content,
            request=request,
        )
