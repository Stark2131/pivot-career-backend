"""Optional, polite job-description fetching from a URL.

Rules (by design):
* Only http/https, only public IP addresses (blocks SSRF to localhost/intranet).
* Respects robots.txt; if a site disallows us, we tell the user to paste the text.
* No login, no captcha bypass, no JS rendering, size-capped download.
Many job boards (e.g. LinkedIn) disallow automated access - pasting is the main path.
"""
import asyncio
import ipaddress
import socket
from html.parser import HTMLParser
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

from app.core.config import get_settings
from app.core.errors import UpstreamError, ValidationFailed
from app.utils.pdf import clean_text

USER_AGENT = "CareerPivotCoachBot/1.0 (+user-requested single page fetch)"


class _TextExtractor(HTMLParser):
    _SKIP = {"script", "style", "noscript", "svg", "head", "nav", "footer", "form"}
    _BLOCK = {"p", "div", "li", "br", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section", "article", "ul", "ol"}

    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip_depth += 1
        elif tag in self._BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data):
        if not self._skip_depth:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    return clean_text("".join(parser.parts))


async def _assert_public_host(host: str) -> None:
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValidationFailed("Could not resolve the job posting host.") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise ValidationFailed("URLs pointing to private or local network addresses are not allowed.")


async def fetch_job_text(url: str) -> str:
    settings = get_settings()
    if not settings.url_fetch_enabled:
        raise ValidationFailed("URL fetching is disabled. Please paste the job description text.")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValidationFailed("Only http(s) URLs are supported.")
    await _assert_public_host(parsed.hostname)

    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,text/plain"}
    async with httpx.AsyncClient(timeout=settings.url_fetch_timeout_seconds, follow_redirects=False) as http:
        # robots.txt check
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        try:
            robots = await http.get(robots_url, headers=headers)
            if robots.status_code == 200:
                rp = RobotFileParser()
                rp.parse(robots.text.splitlines())
                if not rp.can_fetch(USER_AGENT, url):
                    raise ValidationFailed(
                        "This site does not allow automated access (robots.txt). Please paste the job description."
                    )
        except httpx.HTTPError:
            pass  # no robots.txt reachable -> proceed with the single requested page

        try:
            async with http.stream("GET", url, headers=headers) as resp:
                if resp.status_code in {301, 302, 303, 307, 308}:
                    raise ValidationFailed("The URL redirects; please provide the final job posting URL or paste the text.")
                if resp.status_code != 200:
                    raise UpstreamError(f"Job posting URL returned HTTP {resp.status_code}. Please paste the text instead.")
                body = bytearray()
                async for chunk in resp.aiter_bytes():
                    body += chunk
                    if len(body) > settings.url_fetch_max_bytes:
                        raise ValidationFailed("Job posting page is too large.")
                content_type = resp.headers.get("content-type", "")
        except httpx.HTTPError as exc:
            raise UpstreamError("Could not fetch the job posting URL. Please paste the text instead.") from exc

    raw = body.decode("utf-8", errors="replace")
    text = html_to_text(raw) if "html" in content_type or "<html" in raw[:500].lower() else clean_text(raw)
    if len(text) < 100:
        raise ValidationFailed(
            "Could not extract enough text from that page (it may require JavaScript or login). Please paste the text."
        )
    return text
