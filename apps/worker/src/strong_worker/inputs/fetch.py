"""Job posting intake from a URL (IN-1).

Order of attempts:
1. LinkedIn, or a URL we may not fetch: ask the user to paste the text.
2. Greenhouse, Lever, Ashby and Workday: the board's public JSON API, which also works for
   Workday pages that need JavaScript.
3. Any other page: httpx, then trafilatura to keep the main content.
4. A page with too little text after step 3 is probably rendered by scripts: render it with
   Playwright (when installed), then trafilatura again.
5. Still too little text, or a blocked fetch (401, 403, 429 and similar): ask for a paste.

Every hop, including redirects, is checked against private and local addresses.
"""

from __future__ import annotations

import asyncio
import html
import ipaddress
import logging
import re
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urljoin, urlparse

import httpx
import trafilatura
from lxml import html as lxml_html

from strong_worker.inputs.matching import url_host

log = logging.getLogger(__name__)

MIN_TEXT_CHARS = 400
MIN_BOARD_CHARS = 150
MAX_PAGE_BYTES = 3 * 1024 * 1024
MAX_REDIRECTS = 5
USER_AGENT = "StrongHireBot/0.1 (+job posting import; contact support@stronghire.app)"
BLOCKED_STATUSES = {401, 403, 407, 429, 451, 999}
PASTE_ONLY_HOSTS = ("linkedin.com", "lnkd.in")

Board = Literal["greenhouse", "lever", "ashby", "workday", "generic", "browser"]
PasteReason = Literal[
    "linkedin", "invalid_url", "blocked_address", "blocked", "fetch_failed", "too_short"
]

Resolver = Callable[[str], Awaitable[list[str]]]
Renderer = Callable[[str], Awaitable[str | None]]

_WORKDAY = re.compile(r"^(?P<tenant>[a-z0-9-]+)\.wd\d+\.myworkdayjobs\.com$")
_LOCALE = re.compile(r"^[a-z]{2}-[A-Z]{2}$")
_BLOCK_END = re.compile(r"</(p|div|li|h[1-6]|tr|ul|ol|section)>|<br\s*/?>", re.IGNORECASE)


@dataclass(frozen=True)
class FetchResult:
    text: str | None
    board: Board | None = None
    paste_reason: PasteReason | None = None
    detail: str = ""

    @property
    def needs_paste(self) -> bool:
        return self.text is None


class _BlockedError(Exception):
    def __init__(self, reason: PasteReason, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


async def system_resolver(host: str) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return [str(info[4][0]) for info in infos]


async def playwright_render(url: str) -> str | None:
    """Render a page in headless Chromium. Returns None when Playwright is not installed."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        log.info("Playwright is not installed; cannot render %s", url)
        return None
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch()
            try:
                page = await browser.new_page(user_agent=USER_AGENT)
                await page.goto(url, wait_until="networkidle", timeout=20_000)
                content: str = await page.content()
                return content
            finally:
                await browser.close()
    except Exception as exc:
        log.warning("Playwright render failed for %s: %s", url, exc)
        return None


def is_paste_only(url: str) -> bool:
    host = url_host(url) or ""
    return any(host == h or host.endswith("." + h) for h in PASTE_ONLY_HOSTS)


class PostingFetcher:
    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        resolver: Resolver = system_resolver,
        renderer: Renderer | None = playwright_render,
    ) -> None:
        self.client = client
        self.resolver = resolver
        self.renderer = renderer

    async def fetch(self, url: str) -> FetchResult:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return FetchResult(None, paste_reason="invalid_url", detail="Use an http(s) URL.")
        if is_paste_only(url):
            return FetchResult(
                None, paste_reason="linkedin", detail="LinkedIn does not allow fetching postings."
            )
        try:
            board_text = await self._from_board(url)
            if board_text is not None:
                return board_text
            return await self._from_page(url)
        except _BlockedError as blocked:
            return FetchResult(None, paste_reason=blocked.reason, detail=blocked.detail)

    # --- boards -----------------------------------------------------------------------------

    async def _from_board(self, url: str) -> FetchResult | None:
        host = url_host(url) or ""
        parts = [p for p in urlparse(url).path.split("/") if p]
        result: FetchResult | None = None
        try:
            if host.endswith("greenhouse.io") and len(parts) >= 3 and parts[1] == "jobs":
                result = await self._greenhouse(parts[0], parts[2])
            elif host in {"jobs.lever.co", "jobs.eu.lever.co"} and len(parts) >= 2:
                api = "api.eu.lever.co" if ".eu." in host else "api.lever.co"
                result = await self._lever(api, parts[0], parts[1])
            elif host == "jobs.ashbyhq.com" and len(parts) >= 2:
                result = await self._ashby(parts[0], parts[1])
            elif (workday := _WORKDAY.match(host)) and "job" in parts:
                result = await self._workday(host, workday["tenant"], parts)
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            log.info("board API failed for %s (%s); trying the page", url, exc)
            return None
        if result is not None and len(result.text or "") < MIN_BOARD_CHARS:
            return None
        return result

    async def _greenhouse(self, token: str, job_id: str) -> FetchResult | None:
        data = await self._json(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs/{job_id}")
        if data is None:
            return None
        departments = ", ".join(d.get("name", "") for d in data.get("departments") or [])
        text = _compose(
            title=data.get("title"),
            company=data.get("company_name") or token,
            location=(data.get("location") or {}).get("name"),
            team=departments,
            body=html_to_text(html.unescape(data.get("content") or "")),
        )
        return FetchResult(text, board="greenhouse")

    async def _lever(self, api_host: str, company: str, posting_id: str) -> FetchResult | None:
        data = await self._json(f"https://{api_host}/v0/postings/{company}/{posting_id}")
        if data is None:
            return None
        categories = data.get("categories") or {}
        sections = [data.get("descriptionPlain") or ""]
        for item in data.get("lists") or []:
            sections.append(f"{item.get('text', '')}\n{html_to_text(item.get('content', ''))}")
        sections.append(data.get("additionalPlain") or "")
        text = _compose(
            title=data.get("text"),
            company=company,
            location=categories.get("location"),
            team=categories.get("team"),
            body="\n\n".join(s for s in sections if s),
        )
        return FetchResult(text, board="lever")

    async def _ashby(self, org: str, job_id: str) -> FetchResult | None:
        data = await self._json(f"https://api.ashbyhq.com/posting-api/job-board/{org}")
        if data is None:
            return None
        job = next((j for j in data.get("jobs") or [] if j.get("id") == job_id), None)
        if job is None:
            return None
        body = job.get("descriptionPlain") or html_to_text(job.get("descriptionHtml") or "")
        text = _compose(
            title=job.get("title"),
            company=org,
            location=job.get("location"),
            team=job.get("team") or job.get("department"),
            body=body,
        )
        return FetchResult(text, board="ashby")

    async def _workday(self, host: str, tenant: str, parts: list[str]) -> FetchResult | None:
        if parts and _LOCALE.match(parts[0]):
            parts = parts[1:]
        job_at = parts.index("job")
        if job_at != 1:
            return None
        site, rest = parts[0], "/".join(parts[job_at + 1 :])
        data = await self._json(f"https://{host}/wday/cxs/{tenant}/{site}/job/{rest}")
        if data is None:
            return None
        info = data["jobPostingInfo"]
        text = _compose(
            title=info.get("title"),
            company=(data.get("hiringOrganization") or {}).get("name") or tenant,
            location=info.get("location"),
            team=None,
            body=html_to_text(info.get("jobDescription") or ""),
        )
        return FetchResult(text, board="workday")

    # --- generic pages ----------------------------------------------------------------------

    async def _from_page(self, url: str) -> FetchResult:
        resp = await self._get(url, accept="text/html,application/xhtml+xml")
        if resp is None:
            raise _BlockedError("fetch_failed", "The page did not return a posting.")
        text = extract_main_text(resp.text)
        if len(text) >= MIN_TEXT_CHARS:
            return FetchResult(text, board="generic")

        if self.renderer is not None:
            rendered = await self.renderer(str(resp.url))
            if rendered:
                text = extract_main_text(rendered)
                if len(text) >= MIN_TEXT_CHARS:
                    return FetchResult(text, board="browser")
        return FetchResult(
            None,
            paste_reason="too_short",
            detail="The page shows too little text. It may need a login or scripts.",
        )

    # --- HTTP with address checks -----------------------------------------------------------

    async def _json(self, url: str) -> dict[str, Any] | None:
        resp = await self._get(url, accept="application/json")
        if resp is None:
            return None
        data = resp.json()
        return data if isinstance(data, dict) else None

    async def _get(self, url: str, *, accept: str) -> httpx.Response | None:
        """GET with manual redirects so every hop passes the address check. Returns None for a
        404 or a server error; raises _BlockedError when the site refuses us."""
        for _ in range(MAX_REDIRECTS + 1):
            await self._check_address(url)
            try:
                resp = await self.client.get(
                    url,
                    headers={"User-Agent": USER_AGENT, "Accept": accept},
                    follow_redirects=False,
                )
            except httpx.HTTPError as exc:
                raise _BlockedError("fetch_failed", f"Could not reach the site: {exc}") from exc
            if resp.is_redirect and "location" in resp.headers:
                url = urljoin(url, resp.headers["location"])
                continue
            if resp.status_code in BLOCKED_STATUSES:
                raise _BlockedError(
                    "blocked", f"The site refused the request (HTTP {resp.status_code})."
                )
            if resp.status_code >= 400:
                return None
            if len(resp.content) > MAX_PAGE_BYTES:
                raise _BlockedError("fetch_failed", "The page is too large.")
            return resp
        raise _BlockedError("fetch_failed", "Too many redirects.")

    async def _check_address(self, url: str) -> None:
        parsed = urlparse(url)
        host = parsed.hostname
        if parsed.scheme not in {"http", "https"} or not host:
            raise _BlockedError("invalid_url", f"Not an http(s) URL: {url}")
        try:
            addresses = [host] if _is_ip(host) else await self.resolver(host)
        except OSError as exc:
            raise _BlockedError("fetch_failed", f"Cannot resolve {host}") from exc
        if not addresses or not all(ipaddress.ip_address(a).is_global for a in addresses):
            raise _BlockedError("blocked_address", f"{host} is not a public address.")


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def html_to_text(fragment: str) -> str:
    if not fragment.strip():
        return ""
    marked = _BLOCK_END.sub("\n", fragment)
    marked = re.sub(r"<li[^>]*>", "\n- ", marked, flags=re.IGNORECASE)
    text = lxml_html.fragment_fromstring(marked, create_parent="div").text_content()
    lines = [re.sub(r"[ \t\xa0]+", " ", line).strip() for line in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def extract_main_text(page_html: str) -> str:
    text = trafilatura.extract(
        page_html, include_comments=False, include_tables=True, favor_recall=True
    )
    return (text or "").strip()


def _compose(
    *, title: str | None, company: str | None, location: str | None, team: str | None, body: str
) -> str:
    header = [
        f"{label}: {value}"
        for label, value in (
            ("Title", title),
            ("Company", company),
            ("Location", location),
            ("Team", team),
        )
        if value
    ]
    return "\n".join(header) + "\n\n" + body.strip()
