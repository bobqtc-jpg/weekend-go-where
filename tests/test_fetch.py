"""Offline tests for the fetch helpers. Every page, name and URL here is made up."""
from refresh.fetch import USER_AGENT, Article, html_to_article, index_links, robots_from_response

PAGE = """<!doctype html>
<html><head><title>Test Weekend Guide (7 to 8 Nov 2026)</title></head>
<body>
<nav><a href="/">Home</a> <a href="/about">About</a></nav>
<article>
<h1>Test Weekend Guide (7 to 8 Nov 2026)</h1>
<p>This made-up guide exists only to test text extraction for the weekend planner.
It lists two fictional events with the details a parent needs before heading out.</p>
<h2>Test Bubble Show</h2>
<p>When: 7 and 8 Nov 2026, 10am to 11am. Where: Test Mall Atrium. Price: Free.
Suitable for ages 2 and up. <a href="https://example.com/book">Register here</a>.</p>
<h2>Test Puppet Workshop</h2>
<p>When: 8 Nov 2026, 2pm. Where: Test Library. Price: SGD15 per child.
Ages 4 to 8. Bring an old sock to turn into a puppet.</p>
</article>
<footer>Copyright Test Site</footer>
</body></html>"""


def test_html_to_article_keeps_text_and_links():
    article = html_to_article(PAGE, "https://example.com/guide/", "test")
    assert article is not None
    assert "Test Bubble Show" in article.text
    assert "https://example.com/book" in article.text
    assert article.title.startswith("Test Weekend Guide")


def test_short_pages_are_ignored():
    assert html_to_article("<html><body><p>Too short.</p></body></html>", "https://example.com/x", "test") is None


def test_article_key_comes_from_the_url_path():
    article = Article("sassymama", "https://www.example.com/play-weekend-planner/", "Title", None, "text")
    assert article.key == "sassymama__play-weekend-planner"


def test_index_links_filters_and_dedupes():
    html = (
        '<html><body><a href="/p/one">1</a><a href="/p/one#top">1 again</a>'
        '<a href="/about">About</a><a href="https://other.example/p/x">x</a></body></html>'
    )
    links = index_links(html, "https://news.example.com/archive", r"^https://news\.example\.com/p/[a-z0-9-]+$")
    assert links == ["https://news.example.com/p/one"]


def test_robots_rules_are_respected():
    rp = robots_from_response(200, "User-agent: *\nDisallow: /private/\n")
    assert rp.can_fetch(USER_AGENT, "https://example.com/events/")
    assert not rp.can_fetch(USER_AGENT, "https://example.com/private/page")


def test_missing_robots_file_allows_everything():
    assert robots_from_response(404, "").can_fetch(USER_AGENT, "https://example.com/anything")


def test_robots_server_error_means_stay_out():
    assert not robots_from_response(503, "").can_fetch(USER_AGENT, "https://example.com/anything")
