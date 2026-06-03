"""WebSearch and WebFetch tools — no API key required."""
from __future__ import annotations

import re
from urllib.parse import quote_plus

import httpx

from deepx.tools.base import Tool


class WebSearch(Tool):
    """Search the web using DuckDuckGo (via ddgs, no API key needed)."""

    name = "WebSearch"
    description = "Search the web for current information, documentation, or answers to questions. Use this when you need information that may not be in your training data, or for the latest documentation. Returns a list of search results with titles, URLs, and snippets."
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query.",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results (default: 5, max: 10).",
            },
        },
        "required": ["query"],
    }

    async def execute(self, query: str, max_results: int = 5, **kwargs) -> str:
        if not query or not query.strip():
            return "[WebSearch] query 不能为空"

        max_results = max(1, min(max_results, 10))

        try:
            from ddgs import DDGS

            results = []
            with DDGS() as ddgs:
                for i, r in enumerate(ddgs.text(query, max_results=max_results)):
                    results.append(
                        f"{i + 1}. {r.get('title', '')}\n"
                        f"   {r.get('href', '')}\n"
                        f"   {r.get('body', '')}"
                    )

            if not results:
                return f'[WebSearch] "{query}" 无结果'

            header = f'搜索 "{query}" 找到 {len(results)} 条结果:\n\n'
            return header + "\n\n".join(results)

        except Exception as e:
            return f"[WebSearch] 搜索失败: {e}\n可能是网络问题或 DuckDuckGo 被限频。"


class WebFetch(Tool):
    """Fetch and extract text content from a URL."""

    name = "WebFetch"
    description = "Fetch the content of a URL and extract the text. Use this to get the content of documentation pages, blog posts, or any other web page. Returns the extracted text content."
    parameters = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The URL to fetch.",
            },
            "max_length": {
                "type": "integer",
                "description": "Maximum characters to return. Default 8000.",
            },
        },
        "required": ["url"],
    }

    async def execute(self, url: str, max_length: int = 8000, **kwargs) -> str:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        }

        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
                resp = await client.get(url, headers=headers)
                resp.raise_for_status()
                html = resp.text
        except Exception as e:
            return f"Error fetching URL: {e}"

        # Extract text from HTML
        text = self._html_to_text(html)

        if len(text) > max_length:
            text = text[:max_length] + f"\n\n... [truncated, {len(text) - max_length} more chars]"

        return f"[Fetched: {url}]\n\n{text}"

    def _html_to_text(self, html: str) -> str:
        """Convert HTML to plain text with structure preserved."""
        # Remove script and style blocks
        text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)

        # Remove nav, footer, header
        text = re.sub(r"<nav[^>]*>.*?</nav>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<footer[^>]*>.*?</footer>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<header[^>]*>.*?</header>", "", text, flags=re.DOTALL | re.IGNORECASE)

        # Preserve headings and paragraphs with newlines
        text = re.sub(r"<h[1-6][^>]*>", "\n## ", text, flags=re.IGNORECASE)
        text = re.sub(r"</h[1-6]>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<p[^>]*>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"</p>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<li[^>]*>", "\n- ", text, flags=re.IGNORECASE)

        # Remove all remaining tags
        text = re.sub(r"<[^>]+>", "", text)

        # Decode HTML entities
        text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
        text = text.replace("&quot;", '"').replace("&#39;", "'")
        text = text.replace("&nbsp;", " ")

        # Clean up whitespace
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)

        return text.strip()