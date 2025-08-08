import asyncio
import logging
from pathlib import Path
from unittest.mock import patch

from isubrip.cli import console
from isubrip.commands.download import download
from isubrip.logger import logger, setup_loggers
from isubrip.utils import TemporaryDirectory
from tests.tools.mock_loader import MockLoader


async def benchmark() -> None:
    setup_loggers(
        stdout_loglevel=logging.INFO,
        stdout_console=console,
        logfile_output=False,
    )
    url = "https://tv.apple.com/il/movie/interstellar/umc.cmc.1vrwat5k1ucm5k42q97ioqyq3"
    mock_data_path = Path("tests/mock_data/appletv/il/umc.cmc.1vrwat5k1ucm5k42q97ioqyq3")
    mock_loader = MockLoader(mock_data_path, logger=logger)

    with TemporaryDirectory() as temp_dir:
        logger.info(f"Temporary directory created at: {temp_dir}")

        with patch("httpx.AsyncClient.send", side_effect=mock_loader.mock_send_handler):
            await download(url, download_path=temp_dir)


if __name__ == "__main__":
    asyncio.run(benchmark())
