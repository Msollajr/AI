"""
ingest_urls.py
--------------
Web scraper → Markdown → ChromaDB ingestion pipeline for the UDSM Student Support AI.

Usage:
    python backend/ingest_urls.py                          # scrape all URLs in source-urls.txt
    python backend/ingest_urls.py --force                  # re-scrape + force full re-index
    python backend/ingest_urls.py --url "https://..."      # scrape a single URL
    python backend/ingest_urls.py --skip-vectorize         # scrape only, skip indexing
    python backend/ingest_urls.py --list                   # show all URLs in source-urls.txt

Add links to:
    c:\\Users\\lenny silvanus\\Desktop\\AI\\source-urls.txt
"""

import sys
import os
import re
import time
import hashlib
import argparse
import logging
from pathlib import Path
from urllib.parse import urlparse, urljoin

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── Paths ────────────────────────────────────────────────────────────────────
SCRIPT_DIR   = Path(__file__).parent
ROOT_DIR     = SCRIPT_DIR.parent
URLS_FILE    = ROOT_DIR / "source-urls.txt"
KB_DIR       = ROOT_DIR / "knowledge-base"
SCRAPED_DIR  = ROOT_DIR / "knowledge-base" / "scraped"   # web pages go here
VS_DIR       = SCRIPT_DIR / "vector_store"

# ── HTTP settings ─────────────────────────────────────────────────────────────
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}
REQUEST_TIMEOUT  = 30   # seconds per page
DELAY_BETWEEN    = 1.5  # polite delay between requests (seconds)
MAX_CONTENT_SIZE = 5 * 1024 * 1024   # skip pages > 5 MB


# ─────────────────────────────────────────────────────────────────────────────
# URL file parsing
# ─────────────────────────────────────────────────────────────────────────────

def load_urls(path: Path) -> list[str]:
    """Read URLs from source-urls.txt, ignoring comments and blank lines."""
    if not path.exists():
        logger.error(f"URL file not found: {path}")
        return []
    urls = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            urls.append(line)
    return urls


def url_to_filename(url: str) -> str:
    """Convert a URL to a safe, readable filename for the markdown output."""
    parsed = urlparse(url)
    # Use domain + path, sanitised
    name = parsed.netloc + parsed.path
    name = re.sub(r'[^\w\-/]', '_', name)
    name = re.sub(r'[/_]+', '_', name).strip('_')
    name = name[:80]  # cap length
    return name + ".md"


def url_to_doc_title(url: str) -> str:
    """Generate a human-readable document title from the URL."""
    parsed = urlparse(url)
    parts = [p for p in parsed.path.strip("/").split("/") if p]
    if parts:
        title = parts[-1].replace("-", " ").replace("_", " ").title()
    else:
        title = parsed.netloc.replace("www.", "").replace(".ac.tz", "").replace(".go.tz", "").title()
    return f"{title} ({parsed.netloc})"


# ─────────────────────────────────────────────────────────────────────────────
# Web fetching
# ─────────────────────────────────────────────────────────────────────────────

def fetch_page(url: str, session) -> tuple[str, str]:
    """
    Fetch a URL and return (html_content, final_url).
    Returns ("", url) on failure.
    """
    import requests
    try:
        resp = session.get(
            url,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
            stream=True,
        )
        resp.raise_for_status()

        # Check content type — only process HTML
        ct = resp.headers.get("Content-Type", "")
        if "text/html" not in ct and "application/xhtml" not in ct:
            logger.warning(f"  Skipped (not HTML, content-type={ct})")
            return "", resp.url

        # Check content length
        content_length = int(resp.headers.get("Content-Length", 0))
        if content_length > MAX_CONTENT_SIZE:
            logger.warning(f"  Skipped (too large: {content_length:,} bytes)")
            return "", resp.url

        html = resp.text
        return html, resp.url

    except Exception as e:
        logger.warning(f"  Failed to fetch: {e}")
        return "", url


# ─────────────────────────────────────────────────────────────────────────────
# HTML → Markdown conversion
# ─────────────────────────────────────────────────────────────────────────────

# Tags whose content should be completely discarded
DISCARD_TAGS = {
    "script", "style", "noscript", "iframe", "svg", "path",
    "header", "footer", "nav", "aside", "form", "button",
    "meta", "link", "img", "figure", "figcaption",
}

# Tags to treat as section breaks / headers
HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}


def html_to_markdown(html: str, base_url: str, doc_title: str) -> str:
    """
    Convert an HTML page to clean, structured Markdown.

    Strategy:
    1. Remove boilerplate (nav, header, footer, scripts)
    2. Find the main content area (article, main, #content, etc.)
    3. Convert headings → ##, lists → -, tables → markdown tables
    4. Clean up whitespace
    """
    from bs4 import BeautifulSoup, NavigableString, Tag

    soup = BeautifulSoup(html, "lxml")

    # Remove discard tags entirely
    for tag_name in DISCARD_TAGS:
        for tag in soup.find_all(tag_name):
            tag.decompose()

    # Try to find the main content block
    main = (
        soup.find("article") or
        soup.find("main") or
        soup.find(id=re.compile(r"content|main|body|article", re.I)) or
        soup.find(class_=re.compile(r"content|main|article|entry", re.I)) or
        soup.find("body") or
        soup
    )

    lines = [f"# {doc_title}", f"\nSource: {base_url}\n"]
    _node_to_lines(main, lines)

    # Clean up: remove 3+ consecutive blank lines
    text = "\n".join(lines)
    text = re.sub(r'\n{4,}', '\n\n\n', text)
    text = re.sub(r'[ \t]+\n', '\n', text)  # trailing spaces
    return text.strip()


def _node_to_lines(node, lines: list, depth: int = 0):
    """Recursively walk BeautifulSoup nodes and emit markdown lines."""
    from bs4 import NavigableString, Tag

    if isinstance(node, NavigableString):
        text = str(node).strip()
        if text and text not in ('\n', '\r\n'):
            lines.append(text)
        return

    if not isinstance(node, Tag):
        return

    tag = node.name.lower() if node.name else ""

    # Headings
    if tag in HEADING_TAGS:
        level = int(tag[1])          # h1→1, h2→2 …
        md_level = min(level + 1, 6) # shift down one (# is the doc title)
        text = node.get_text(" ", strip=True)
        if text:
            lines.append(f"\n{'#' * md_level} {text}")
        return

    # Paragraph
    if tag == "p":
        text = node.get_text(" ", strip=True)
        if text:
            lines.append(f"\n{text}")
        return

    # Unordered list
    if tag == "ul":
        for li in node.find_all("li", recursive=False):
            text = li.get_text(" ", strip=True)
            if text:
                lines.append(f"- {text}")
        lines.append("")
        return

    # Ordered list
    if tag == "ol":
        for i, li in enumerate(node.find_all("li", recursive=False), 1):
            text = li.get_text(" ", strip=True)
            if text:
                lines.append(f"{i}. {text}")
        lines.append("")
        return

    # Table
    if tag == "table":
        md_table = _table_to_markdown(node)
        if md_table:
            lines.append(md_table)
        return

    # Blockquote / pre / code
    if tag in ("blockquote", "pre", "code"):
        text = node.get_text(strip=True)
        if text:
            lines.append(f"\n> {text}")
        return

    # Horizontal rule → markdown separator
    if tag == "hr":
        lines.append("\n---")
        return

    # Line break
    if tag == "br":
        lines.append("")
        return

    # Recurse into children for all other tags (div, section, span, td, etc.)
    for child in node.children:
        _node_to_lines(child, lines, depth + 1)


def _table_to_markdown(table_tag) -> str:
    """Convert a <table> element to a markdown table string."""
    rows = table_tag.find_all("tr")
    if not rows:
        return ""

    md_rows = []
    for row in rows:
        cells = row.find_all(["th", "td"])
        cell_texts = [c.get_text(" ", strip=True).replace("|", "\\|") for c in cells]
        md_rows.append(cell_texts)

    if not md_rows:
        return ""

    col_count = max(len(r) for r in md_rows)

    # Pad all rows to same width
    for r in md_rows:
        while len(r) < col_count:
            r.append("")

    # First row as header
    header = md_rows[0]
    separator = ["---"] * col_count
    body = md_rows[1:]

    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(separator) + " |",
    ]
    for row in body:
        lines.append("| " + " | ".join(row) + " |")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Scrape pipeline
# ─────────────────────────────────────────────────────────────────────────────

def scrape_url(url: str, session, out_dir: Path) -> Path | None:
    """
    Fetch a URL, convert to markdown, save to out_dir.
    Returns the output Path on success, None on failure.
    """
    logger.info(f"Scraping: {url}")
    html, final_url = fetch_page(url, session)

    if not html:
        return None

    doc_title = url_to_doc_title(final_url)
    logger.info(f"  Title: {doc_title}")
    logger.info(f"  HTML size: {len(html):,} chars")

    markdown = html_to_markdown(html, final_url, doc_title)
    logger.info(f"  Markdown size: {len(markdown):,} chars")

    if len(markdown.strip()) < 200:
        logger.warning(f"  Skipped — extracted content too short (likely JavaScript-only page)")
        return None

    filename = url_to_filename(url)
    out_path = out_dir / filename
    out_path.write_text(markdown, encoding="utf-8")
    logger.info(f"  Saved → {out_path.relative_to(ROOT_DIR)} ({out_path.stat().st_size:,} bytes)")
    return out_path


# ─────────────────────────────────────────────────────────────────────────────
# Vector store rebuild
# ─────────────────────────────────────────────────────────────────────────────

def rebuild_vector_store(force: bool = False):
    """Rebuild ChromaDB from all markdown files in knowledge-base/ (including scraped/)."""
    logger.info("Rebuilding vector store index...")

    if str(SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR))

    original_dir = os.getcwd()
    os.chdir(str(SCRIPT_DIR))
    try:
        from vector_store import VectorStore
        vs = VectorStore()
        # Pass the parent KB dir; VectorStore.build() scans recursively
        total = vs.build(KB_DIR, force=force)
        logger.info(f"Vector store rebuilt — {total} chunks indexed.")
        return total
    finally:
        os.chdir(original_dir)


# ─────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Scrape UDSM web pages into the knowledge base and vector store."
    )
    parser.add_argument(
        "--url", type=str, default=None,
        help="Scrape a single specific URL instead of reading source-urls.txt"
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Re-scrape all URLs (even if already saved) and force full re-index"
    )
    parser.add_argument(
        "--skip-vectorize", action="store_true",
        help="Only scrape and convert, skip vector store rebuild"
    )
    parser.add_argument(
        "--list", action="store_true",
        help="List all URLs in source-urls.txt and exit"
    )
    args = parser.parse_args()

    # ── List mode ──────────────────────────────────────────────────────────
    if args.list:
        urls = load_urls(URLS_FILE)
        print(f"\nURLs in {URLS_FILE.name} ({len(urls)} total):\n")
        for u in urls:
            md_path = SCRAPED_DIR / url_to_filename(u)
            status = "✅ scraped" if md_path.exists() else "⏳ pending"
            print(f"  {status}  {u}")
        return

    # ── Determine URLs to scrape ───────────────────────────────────────────
    if args.url:
        urls = [args.url]
    else:
        urls = load_urls(URLS_FILE)
        if not urls:
            logger.warning(f"No URLs found in {URLS_FILE}")
            logger.info(f"Add website URLs (one per line) to: {URLS_FILE}")
            return

    # ── Create output directory ────────────────────────────────────────────
    SCRAPED_DIR.mkdir(parents=True, exist_ok=True)

    # ── Import requests ────────────────────────────────────────────────────
    try:
        import requests
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry
    except ImportError:
        logger.error("requests is not installed. Run: pip install requests")
        sys.exit(1)

    # ── Set up session with retry logic ───────────────────────────────────
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    # Disable SSL verification for sites with self-signed/corp certs
    session.verify = False
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    # ── Scrape each URL ────────────────────────────────────────────────────
    logger.info(f"Found {len(urls)} URL(s) to process")
    scraped = []

    for i, url in enumerate(urls, 1):
        out_path = SCRAPED_DIR / url_to_filename(url)

        # Skip already-scraped pages unless --force
        if out_path.exists() and not args.force:
            logger.info(f"[{i}/{len(urls)}] Skipped (already scraped): {url}")
            logger.info(f"  Use --force to re-scrape")
            continue

        logger.info(f"[{i}/{len(urls)}]")
        result = scrape_url(url, session, SCRAPED_DIR)
        if result:
            scraped.append(result)

        # Polite delay between requests
        if i < len(urls):
            time.sleep(DELAY_BETWEEN)

    logger.info(f"\nScraped {len(scraped)} new page(s)")

    # ── Rebuild vector store ───────────────────────────────────────────────
    if scraped and not args.skip_vectorize:
        total = rebuild_vector_store(force=True)
        logger.info(f"\n✅ Done! {total} chunks in vector store, {len(scraped)} new pages added.")
    elif args.skip_vectorize:
        logger.info("\nSkipped vector store rebuild (--skip-vectorize). Run without the flag to index.")
    elif not scraped:
        logger.info("\nNo new pages scraped. Vector store unchanged.")
        logger.info("Tip: use --force to re-scrape pages already saved.")


if __name__ == "__main__":
    main()
