from __future__ import annotations

from abc import ABC, abstractmethod
import argparse
import asyncio
import hashlib
import inspect
import json
import logging
from pathlib import Path
import shutil
import typing
from typing import TYPE_CHECKING, Any, ClassVar

from isubrip.cli import console
from isubrip.logger import logger, setup_loggers
from isubrip.scrapers.scraper import HLSScraper, PlaylistLoadError, Scraper, ScraperFactory

if TYPE_CHECKING:
    import httpx
    import m3u8

    from isubrip.scrapers.appletv_scraper import AppleTVScraper


setup_loggers(
    stdout_loglevel=logging.DEBUG,
    stdout_console=console,
    logfile_output=False,
)

MOCK_GENERATOR_MAPPING: dict[str, type[MockDataGenerator]] = {}


class MockDataGenerator(ABC):
    """Abstract base class for mock data generators."""
    MOCK_DATA_ROOT: ClassVar[Path] = Path(__file__).parent.parent / "mock_data"

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Automatically register mock data generator subclasses."""
        super().__init_subclass__(**kwargs)

        if not inspect.isabstract(cls):
            type_hints = typing.get_type_hints(cls)
            scraper_class = type_hints.get("scraper")

            if scraper_class and hasattr(scraper_class, "id"):
                MOCK_GENERATOR_MAPPING[scraper_class.id] = cls

            else:
                logger.warning(
                    f"MockDataGenerator subclass '{cls.__name__}' does not have a valid scraper class defined.")

    def __init__(self, scraper: Scraper):
        self.scraper = scraper

    @abstractmethod
    def output_path(self, url: str) -> Path:
        """
        Generate a relative path for the output file, based on the URL.

        Args:
            url: The URL to get the output directory for.

        Returns:
            A relative Path object for the output file.
        """

    async def generate(self, url: str, languages: list[str] | None = None, force: bool = False) -> None:
        """
        Generate mock data for a given URL.

        Args:
            url: The URL to generate mock data for.
            languages: A list of languages to download subtitles for.
            force: If True, delete existing mock data before generating new data.
        """
        output_dir = self.MOCK_DATA_ROOT / self.output_path(url)
        manifest_path = output_dir / "manifest.json"

        if output_dir.is_dir() and manifest_path.is_file():
            if force:
                logger.info(f"Removing existing mock data at: {output_dir}")
                shutil.rmtree(output_dir)
            else:
                logger.error(f"Mock data already exists at: {output_dir}. Use the --force flag to overwrite.")
                return

        output_dir.mkdir(parents=True, exist_ok=True)
        manifest: dict[str, str] = {}

        # Define a hook to save responses
        async def save_response_hook(response: httpx.Response) -> None:
            await response.aread()
            url = str(response.request.url)

            if url in manifest:
                logger.debug(f"URL already processed, skipping: {url}")
                return

            logger.info(f"Intercepted response from: {url}")
            filename = hashlib.sha256(url.encode('utf-8')).hexdigest()
            file_path = output_dir / filename
            file_path.write_bytes(response.content)
            manifest[url] = filename
            logger.debug(f"Saved response to: {file_path}")

        try:
            # Attach the hook to the scraper's HTTP client
            self.scraper._client.event_hooks['response'].append(save_response_hook)  # noqa: SLF001

            logger.info("Fetching media data...")
            scraped_data = await self.scraper.get_data(url=url)

            if not scraped_data or not scraped_data.media_data:
                logger.error(f"Could not retrieve media data for {url}")
                return

            media_item = scraped_data.media_data[0]
            playlist_url = getattr(media_item, 'playlist', None)

            if not playlist_url:
                logger.error(f"No playlist URL found in scraped data for {url}")
                return

            main_playlist_url = playlist_url[0] if isinstance(playlist_url, list) else playlist_url
            logger.info(f"Loading main playlist from: {main_playlist_url}")
            main_playlist: m3u8.M3U8 | None = await self.scraper.load_playlist(url=main_playlist_url)

            if not main_playlist:
                logger.error(f"Could not load main playlist from {main_playlist_url}")
                return

            logger.info(f"Searching for subtitle playlists (Languages: {languages or 'all'})...")
            subtitle_media_items: list[m3u8.Media] = self.scraper.find_matching_subtitles(
                main_playlist, language_filter=languages)

            if not subtitle_media_items:
                logger.warning(f"No matching subtitles found for languages: {languages or 'all'}")
                return

            for sub_media in subtitle_media_items:
                try:
                    logger.info(f"Loading subtitle playlist: {sub_media.absolute_uri}")
                    subtitle_playlist: m3u8.M3U8 | None = await self.scraper.load_playlist(
                        url=sub_media.absolute_uri)
                    if subtitle_playlist and subtitle_playlist.segments:
                        logger.info(f"Downloading {len(subtitle_playlist.segments)} segments...")
                        if isinstance(self.scraper, HLSScraper):
                            await self.scraper.download_segments(subtitle_playlist)

                except PlaylistLoadError as e:
                    logger.error(f"Failed to load subtitle playlist {sub_media.absolute_uri}: {e}")
                except Exception:
                    logger.error(f"Unexpected error processing playlist {sub_media.absolute_uri}", exc_info=True)

        except Exception as e:
            logger.error(f"An error occurred during data generation: {e}", exc_info=True)

        finally:
            if manifest:
                manifest_path = output_dir / "manifest.json"
                manifest_path.write_text(json.dumps(manifest, indent=4, sort_keys=True), encoding="utf-8")
                logger.info(f"Successfully generated {len(manifest)} mock data entries.")
                logger.info(f"Manifest written to: {manifest_path.resolve()}")


class AppleTVMockDataGenerator(MockDataGenerator):
    """A mock data generator for the Apple TV scraper."""
    scraper: AppleTVScraper

    def output_path(self, url: str) -> Path:
        url_regex_match: dict[str, Any] = self.scraper.match_url(url=url, raise_error=True).groupdict()
        media_id: str = url_regex_match["media_id"]
        storefront: str = url_regex_match["country_code"]
        return Path(self.scraper.id) / storefront / media_id


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate mock HTTP response data for iSubRip testing. "
                    "This script runs a scraper against a live URL and saves all "
                    "HTTP responses to be used in offline tests.",
    )
    parser.add_argument(
        "-u", "--url",
        required=True,
        metavar="URL",
        help="The full URL of the media item to fetch data for.",
    )
    parser.add_argument(
        "-l", "--languages",
        nargs="*",
        default=None,
        help="Optional: language code(s) to filter subtitles (e.g., 'en', 'es'). Fetches all if not set.",
    )
    parser.add_argument(
        "-f", "--force",
        action="store_true",
        help="Force regeneration of mock data, deleting any existing data.",
    )
    args = parser.parse_args()

    scraper = ScraperFactory.get_scraper_instance(url=args.url, raise_error=True)

    if not scraper:
        return

    if generator_class := MOCK_GENERATOR_MAPPING.get(scraper.id):
        generator = generator_class(scraper=scraper)

        logger.info(f"Starting mock data generation for URL: {args.url}")
        await generator.generate(url=args.url, languages=args.languages, force=args.force)
        logger.info("Mock data generation process complete.")

    else:
        logger.error(f"No mock data generator found for scraper: {scraper.id}")

    await scraper.async_close()


if __name__ == "__main__":
    asyncio.run(main())
