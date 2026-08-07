from __future__ import annotations

import asyncio
import re
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from isubrip.logger import logger
from isubrip.scrapers.scraper import HLSScraper, ScraperError, ScraperFactory
from isubrip.subtitle_formats.webvtt import WebVTTSubtitles

if TYPE_CHECKING:
    from collections.abc import Hashable

    import m3u8
    from m3u8.model import Media

    from isubrip.data_structures import Movie, ScrapedMediaResponse


REDIRECT_MAX_RETRIES = 5
REDIRECT_SLEEP_TIME = 2
APPLE_SUBTITLE_CDN_HOST_REGEX = re.compile(
    r"vod-(?:ap|fa|ak)-(?P<family>amt|aoc)\.tv\.apple\.com",
    flags=re.IGNORECASE,
)
APPLE_SUBTITLE_GROUP_ID_REGEX = re.compile(
    r"subtitles_(?:(?:ap|fa|ak)|vod-(?:ap|fa|ak)-(?P<family>amt|aoc)\.tv\.apple\.com)",
    flags=re.IGNORECASE,
)
APPLE_SUBTITLE_RENDITION_ATTRIBUTES = (
    "type",
    "language",
    "name",
    "default",
    "autoselect",
    "forced",
    "assoc_language",
    "instream_id",
    "characteristics",
    "channels",
    "stable_rendition_id",
)


class ItunesScraper(HLSScraper):
    """An iTunes movie data scraper."""
    id = "itunes"
    name = "iTunes"
    abbreviation = "iT"
    url_regex = re.compile(r"(?i)(?P<base_url>https?://itunes\.apple\.com/(?:(?P<country_code>[a-z]{2})/)?(?P<media_type>movie|tv-show|tv-season|show)/(?:(?P<media_name>[\w\-%]+)/)?(?P<media_id>id\d{9,10}))(?:\?(?P<url_params>.*))?")
    subtitles_class = WebVTTSubtitles
    is_movie_scraper = True
    uses_scrapers = ["appletv"]

    _subtitles_filters = {
        HLSScraper.M3U8Attribute.GROUP_ID.value: [
            "subtitles_ap",
            "subtitles_fa",
            "subtitles_ak",
            "subtitles_vod-ap-amt.tv.apple.com",
            "subtitles_vod-fa-amt.tv.apple.com",
            "subtitles_vod-ak-amt.tv.apple.com",
            "subtitles_vod-ap-aoc.tv.apple.com",
            "subtitles_vod-fa-aoc.tv.apple.com",
            "subtitles_vod-ak-aoc.tv.apple.com",
        ],
        **HLSScraper._subtitles_filters,  # noqa: SLF001
    }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._appletv_scraper = ScraperFactory.get_scraper_instance(
            scraper_id="appletv",
            raise_error=True,
        )

    def _get_subtitle_media_group_key(self, subtitles_media: Media) -> Hashable:
        subtitle_url = subtitles_media.uri
        group_id_match = APPLE_SUBTITLE_GROUP_ID_REGEX.fullmatch(subtitles_media.group_id or "")

        if not subtitle_url or not group_id_match:
            return super()._get_subtitle_media_group_key(subtitles_media=subtitles_media)

        url_parts = urlsplit(subtitle_url)
        host_match = APPLE_SUBTITLE_CDN_HOST_REGEX.fullmatch(url_parts.hostname or "")

        if host_match:
            cdn_family = host_match.group("family").casefold()
            canonical_url = url_parts._replace(netloc=f"vod-apple-{cdn_family}.tv.apple.com").geturl()

        else:
            cdn_family = (group_id_match.group("family") or "generic").casefold()
            canonical_url = subtitle_url

        rendition_attributes = tuple(
            getattr(subtitles_media, attribute_name, None)
            for attribute_name in APPLE_SUBTITLE_RENDITION_ATTRIBUTES
        )
        return cdn_family, canonical_url, rendition_attributes

    async def get_data(self, url: str) -> ScrapedMediaResponse[Movie]:
        """
        Scrape iTunes to find info about a movie, and it's M3U8 main_playlist.

        Args:
            url (str): An iTunes store movie URL.

        Raises:
            InvalidURL: `itunes_url` is not a valid iTunes store movie URL.
            PageLoadError: HTML page did not load properly.
            HTTPError: HTTP request failed.

        Returns:
            Movie: A Movie (NamedTuple) object with movie's name, and an M3U8 object of the main_playlist
            if the main_playlist is found. None otherwise.
        """
        regex_match = self.match_url(url, raise_error=True)
        url_data = regex_match.groupdict()
        country_code: str = url_data["country_code"]
        media_id: str = url_data["media_id"]
        appletv_redirect_finding_url = f"https://tv.apple.com/{country_code}/movie/{media_id}"

        logger.debug("Attempting to fetch redirect location from: " + appletv_redirect_finding_url)

        retries = 0
        while True:
            response = await self._client.get(url=appletv_redirect_finding_url, follow_redirects=False)
            if response.status_code != 301 and retries < REDIRECT_MAX_RETRIES:
                retries += 1
                logger.debug(f"AppleTV redirect URL not found (Response code: {response.status_code}),"
                               f" retrying... ({retries}/{REDIRECT_MAX_RETRIES})")
                await asyncio.sleep(REDIRECT_SLEEP_TIME)
                continue
            break

        redirect_location = response.headers.get("Location")

        if response.status_code != 301 or not redirect_location:
            raise ScraperError(f"AppleTV redirect URL not found (Response code: {response.status_code}).")

        # Add 'https:' if redirect_location starts with '//'
        if redirect_location.startswith('//'):
            redirect_location = "https:" + redirect_location

        logger.debug(f"Redirect URL: {redirect_location}")

        if not self._appletv_scraper.match_url(redirect_location):
            raise ScraperError("Redirect URL is not a valid AppleTV URL.")

        return await self._appletv_scraper.get_data(url=redirect_location)

    @staticmethod
    def parse_language_name(media_data: Media) -> str | None:
        name: str | None = media_data.name

        if name:
            return name.replace(' (forced)', '').strip()

        return None
