"""IN-1: job posting intake from a URL, with board APIs, generic pages and paste fallback."""

from __future__ import annotations

import html

import httpx

from strong_core.config import get_settings
from strong_worker.inputs.fetch import is_paste_only
from strong_worker.inputs.testing import make_fetcher

POSTING = (
    get_settings().repo_root / "evals/fixtures/inputs/postings/swe-stripe-backend.txt"
).read_text(encoding="utf-8")


def posting_page(text: str = POSTING) -> str:
    paragraphs = "".join(f"<p>{html.escape(line)}</p>" for line in text.splitlines() if line)
    return (
        "<html><head><title>Job</title></head><body><nav>Home | Jobs | About</nav>"
        f"<article><h1>Backend Engineer</h1>{paragraphs}</article>"
        "<footer>Copyright</footer></body></html>"
    )


def no_network(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"unexpected request to {request.url}")


async def test_in1_greenhouse_uses_board_api() -> None:
    fetcher = make_fetcher(
        {
            "boards-api.greenhouse.io/v1/boards/stripe/jobs/123": httpx.Response(
                200,
                json={
                    "title": "Backend Engineer",
                    "company_name": "Stripe",
                    "location": {"name": "Seattle, WA"},
                    "departments": [{"name": "Payments Infrastructure"}],
                    "content": html.escape(
                        "<p>Build services that move money.</p><ul><li>5+ years of backend "
                        "experience</li><li>Java, Ruby or Go</li></ul>" * 3
                    ),
                },
            )
        }
    )
    result = await fetcher.fetch("https://boards.greenhouse.io/stripe/jobs/123")
    assert result.board == "greenhouse"
    assert result.text is not None
    assert "Title: Backend Engineer" in result.text
    assert "Company: Stripe" in result.text
    assert "- Java, Ruby or Go" in result.text
    assert "<li>" not in result.text


async def test_in1_lever_uses_board_api() -> None:
    fetcher = make_fetcher(
        {
            "api.lever.co/v0/postings/acme/abc-123": httpx.Response(
                200,
                json={
                    "text": "Data Engineer",
                    "categories": {"team": "Data", "location": "Remote"},
                    "descriptionPlain": "We build pipelines for 300 customers. " * 4,
                    "lists": [{"text": "Requirements", "content": "<li>SQL</li><li>Airflow</li>"}],
                    "additionalPlain": "Benefits include health insurance.",
                },
            )
        }
    )
    result = await fetcher.fetch("https://jobs.lever.co/acme/abc-123")
    assert result.board == "lever"
    assert result.text is not None
    assert "Title: Data Engineer" in result.text
    assert "Requirements" in result.text and "- Airflow" in result.text


async def test_in1_ashby_uses_board_api() -> None:
    fetcher = make_fetcher(
        {
            "api.ashbyhq.com/posting-api/job-board/openai": httpx.Response(
                200,
                json={
                    "jobs": [
                        {"id": "other", "title": "Recruiter", "descriptionPlain": "x"},
                        {
                            "id": "job-1",
                            "title": "Research Engineer",
                            "team": "Applied",
                            "location": "San Francisco",
                            "descriptionPlain": "Train and ship large models. " * 8,
                        },
                    ]
                },
            )
        }
    )
    result = await fetcher.fetch("https://jobs.ashbyhq.com/openai/job-1")
    assert result.board == "ashby"
    assert result.text is not None and "Title: Research Engineer" in result.text
    assert "Recruiter" not in result.text


async def test_in1_workday_uses_cxs_api() -> None:
    path = "/wday/cxs/nvidia/NVIDIAExternalCareerSite/job/US-CA-Santa-Clara/Senior-Engineer_JR1"
    fetcher = make_fetcher(
        {
            f"nvidia.wd5.myworkdayjobs.com{path}": httpx.Response(
                200,
                json={
                    "jobPostingInfo": {
                        "title": "Senior GPU Software Engineer",
                        "location": "US, CA, Santa Clara",
                        "jobDescription": "<p>Write CUDA kernels for deep learning.</p>" * 6,
                    },
                    "hiringOrganization": {"name": "NVIDIA"},
                },
            )
        }
    )
    url = (
        "https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite/job/"
        "US-CA-Santa-Clara/Senior-Engineer_JR1"
    )
    result = await fetcher.fetch(url)
    assert result.board == "workday"
    assert result.text is not None
    assert "Company: NVIDIA" in result.text and "CUDA kernels" in result.text


async def test_in1_generic_career_page_keeps_main_content() -> None:
    fetcher = make_fetcher(
        {"careers.example.org/jobs/42": httpx.Response(200, html=posting_page())}
    )
    result = await fetcher.fetch("https://careers.example.org/jobs/42")
    assert result.board == "generic"
    assert result.text is not None
    assert "card authorization path" in result.text
    assert "Copyright" not in result.text


async def test_in1_board_api_miss_falls_back_to_the_page() -> None:
    fetcher = make_fetcher(
        {"boards.greenhouse.io/stripe/jobs/999": httpx.Response(200, html=posting_page())}
    )
    result = await fetcher.fetch("https://boards.greenhouse.io/stripe/jobs/999")
    assert result.board == "generic"


async def test_in1_follows_redirects() -> None:
    fetcher = make_fetcher(
        {
            "careers.example.org/j/42": httpx.Response(
                301, headers={"location": "/jobs/42-backend"}
            ),
            "careers.example.org/jobs/42-backend": httpx.Response(200, html=posting_page()),
        }
    )
    result = await fetcher.fetch("https://careers.example.org/j/42")
    assert result.board == "generic"


async def test_in1_script_rendered_page_uses_the_browser() -> None:
    shell = "<html><body><div id='root'></div><script src='/app.js'></script></body></html>"
    fetcher = make_fetcher(
        {"jobs.example.org/p/7": httpx.Response(200, html=shell)}, rendered=posting_page()
    )
    result = await fetcher.fetch("https://jobs.example.org/p/7")
    assert result.board == "browser"
    assert result.text is not None and "Payments" in result.text


async def test_in1_script_page_without_browser_asks_for_paste() -> None:
    shell = "<html><body><div id='root'></div></body></html>"
    fetcher = make_fetcher({"jobs.example.org/p/7": httpx.Response(200, html=shell)})
    result = await fetcher.fetch("https://jobs.example.org/p/7")
    assert result.needs_paste
    assert result.paste_reason == "too_short"


async def test_in1_linkedin_falls_back_to_paste_without_fetching() -> None:
    fetcher = make_fetcher({"www.linkedin.com/jobs/view/123": no_network})
    result = await fetcher.fetch("https://www.linkedin.com/jobs/view/123")
    assert result.needs_paste
    assert result.paste_reason == "linkedin"
    assert is_paste_only("https://lnkd.in/abc")
    assert not is_paste_only("https://careers.linkedin.com.example.org/")


async def test_in1_blocked_fetch_asks_for_paste() -> None:
    fetcher = make_fetcher({"careers.example.org/jobs/1": httpx.Response(403, text="denied")})
    result = await fetcher.fetch("https://careers.example.org/jobs/1")
    assert result.needs_paste
    assert result.paste_reason == "blocked"


async def test_in1_private_addresses_are_never_fetched() -> None:
    async def private(host: str) -> list[str]:
        return ["10.0.0.5"]

    fetcher = make_fetcher({"intranet.example.org/jobs": no_network}, resolver=private)
    result = await fetcher.fetch("https://intranet.example.org/jobs")
    assert result.paste_reason == "blocked_address"

    redirecting = make_fetcher(
        {
            "careers.example.org/jobs/1": httpx.Response(
                302, headers={"location": "http://127.0.0.1:8700/admin"}
            )
        }
    )
    result = await redirecting.fetch("https://careers.example.org/jobs/1")
    assert result.paste_reason == "blocked_address"


async def test_in1_rejects_non_http_urls() -> None:
    result = await make_fetcher({}).fetch("file:///etc/passwd")
    assert result.paste_reason == "invalid_url"
