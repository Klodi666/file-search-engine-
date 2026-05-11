import re
import time
import random
import logging
import threading
import urllib.parse
from collections import Counter
from urllib.parse import urlparse, urljoin
from datetime import datetime

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup

# Try to import Rich for the UI; fallback to print if not available
try:
    from rich.console import Console
    from rich.live import Live
    from rich.table import Table
    from rich.panel import Panel
    from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn
    from rich import box as rbox
    HAS_RICH = True
except ImportError:
    HAS_RICH = False

# Try to import fake_useragent; fallback to list if not available
try:
    from fake_useragent import UserAgent
    UA = UserAgent()
    def get_user_agent():
        return UA.random
except Exception:
    _AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
        "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
    ]
    def get_user_agent():
        return random.choice(_AGENTS)

# ── CONFIGURATION ─────────────────────────────────────────────────────────────

TARGET_DOMAINS = [
    "mediafire.com", "mega.nz", "gofile.io", "dropbox.com", "drive.google.com",
    "pixeldrain.com", "anonfiles.com", "workupload.com", "1fichier.com",
    "rapidgator.net", "nitroflare.com", "katfile.com", "krakenfiles.com",
    "mixdrop.co", "terabox.com", "box.com", "ufile.io", "files.fm", "mirrorace.org",
]

SEARCH_ENGINES = {
    "google": "https://www.google.com/search?q={query}&start={start}",
    "bing":   "https://www.bing.com/search?q={query}&first={start}",
    "brave":  "https://search.brave.com/search?q={query}&offset={start}",
    "yahoo":  "https://search.yahoo.com/search?p={query}&b={start}",
    "yandex": "https://yandex.com/search/?text={query}&p={page}",
}

ENGINE_SELECTORS = {
    "google": {"result": "div.g", "url": "a[href]", "title": "h3"},
    "bing":   {"result": "li.b_algo", "url": "h2 a", "title": "h2 a"},
    "brave":  {"result": "div.snippet", "url": "a.result-header", "title": "span.snippet-title"},
    "yahoo":  {"result": "div.dd.algo", "url": "h3 a", "title": "h3 a"},
    "yandex": {"result": "li.serp-item", "url": "a.link_theme_outer", "title": "h2"},
}

DEFAULT_MAX_WORKERS = 20
DEFAULT_MAX_PAGES = 5
DEFAULT_TIMEOUT = 12
DEFAULT_DELAY_RANGE = (1.0, 3.0)
DEFAULT_OUTPUT_FILE = "results.csv"
DEFAULT_CRAWL_DEPTH = 2
MAX_RECURSIVE_URLS = 200

# ── UTILITIES ────────────────────────────────────────────────────────────────

def build_session(retries: int = 3) -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=retries,
        backoff_factor=1.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "HEAD"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://",  adapter)
    session.headers.update({
        "User-Agent": get_user_agent(),
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    })
    return session

def fetch(url: str, session: requests.Session = None, timeout: int = DEFAULT_TIMEOUT) -> requests.Response | None:
    s = session or build_session()
    try:
        resp = s.get(url, timeout=timeout, allow_redirects=True)
        resp.raise_for_status()
        return resp
    except Exception:
        return None

def polite_delay():
    time.sleep(random.uniform(*DEFAULT_DELAY_RANGE))

def is_target_domain(url: str) -> bool:
    try:
        host = urlparse(url).netloc.lower().lstrip("www.")
        return any(host == d or host.endswith("." + d) for d in TARGET_DOMAINS)
    except Exception:
        return False

def normalize_url(url: str, base: str = "") -> str:
    try:
        full = urljoin(base, url)
        p = urlparse(full)
        if p.scheme not in ("http", "https"):
            return ""
        return full.split("?")[0] if p.netloc in TARGET_DOMAINS else full
    except Exception:
        return ""

def detect_file_type(url: str, title: str = "") -> str:
    path = urlparse(url).path.lower()
    ext_match = re.search(r"\.([a-z0-9]{2,6})(?:[?#]|$)", path)
    if ext_match: return ext_match.group(1)
    ext_match = re.search(r"\.([a-z0-9]{2,6})(?:\s|$)", title.lower())
    if ext_match: return ext_match.group(1)
    return ""

_SIZE_PATTERNS = [
    re.compile(r"([\d,.]+)\s*(GB|GiB)", re.I),
    re.compile(r"([\d,.]+)\s*(MB|MiB)", re.I),
    re.compile(r"([\d,.]+)\s*(KB|KiB)", re.I),
    re.compile(r"([\d,.]+)\s*bytes?",   re.I),
]

def parse_size_from_text(text: str) -> str:
    for pattern in _SIZE_PATTERNS:
        m = pattern.search(text)
        if m: return f"{m.group(1)} {m.group(2) or 'bytes'}"
    return ""

# ── METADATA EXTRACTION ───────────────────────────────────────────────────────

def _extract_mediafire(soup):
    meta = {}
    name_tag = soup.select_one("div.filename, .dl-btn-label")
    if name_tag: meta["title"] = name_tag.get_text(strip=True)
    size_tag = soup.select_one("div.file-size, span.file-size")
    if size_tag: meta["file_size"] = size_tag.get_text(strip=True)
    return meta

def _extract_krakenfiles(soup):
    meta = {}
    size_tag = soup.select_one(".file-info-size, span[class*='size']")
    if size_tag: meta["file_size"] = size_tag.get_text(strip=True)
    name_tag = soup.select_one("h1.filename, .file-title")
    if name_tag: meta["title"] = name_tag.get_text(strip=True)
    return meta

_PLATFORM_EXTRACTORS = {
    "mediafire.com": _extract_mediafire,
    "krakenfiles.com": _extract_krakenfiles,
    # Add others as needed
}

def extract_metadata(url: str, seed_title: str = "", session=None) -> dict:
    record = {"url": url, "title": seed_title, "file_type": detect_file_type(url, seed_title), "file_size": ""}
    s = session or build_session()
    resp = fetch(url, session=s)
    if not resp: return record
    soup = BeautifulSoup(resp.text, "lxml")
    if not record["title"] and soup.title: record["title"] = soup.title.string.strip()
    host = urlparse(url).netloc.lower().lstrip("www.")
    extractor_fn = next((fn for dom, fn in _PLATFORM_EXTRACTORS.items() if host == dom or host.endswith("."+dom)), None)
    if extractor_fn: record.update(extractor_fn(soup))
    if not record["file_size"]: record["file_size"] = parse_size_from_text(soup.get_text(" ", strip=True))
    return record

# ── SEARCH ENGINE LOGIC ───────────────────────────────────────────────────────

def search_engine(engine: str, query: str, max_pages: int = 5, session=None) -> list[tuple[str, str]]:
    if engine not in SEARCH_ENGINES: return []
    s = session or build_session()
    found = []
    encoded = urllib.parse.quote_plus(query)
    for page in range(max_pages):
        res_per_page = 10
        p_map = {"google": {"start": page*10}, "bing": {"start": page*10+1}, "brave": {"start": page*10}, "yahoo": {"start": page*10+1}, "yandex": {"page": page}}
        params = p_map.get(engine, {"start": page*10})
        url = SEARCH_ENGINES[engine].format(query=encoded, **params)
        resp = fetch(url, session=s)
        if not resp: break
        
        soup = BeautifulSoup(resp.text, "lxml")
        sel = ENGINE_SELECTORS.get(engine, {})
        page_results = []
        for block in soup.select(sel.get("result", "div")):
            a_tag = block.select_one(sel.get("url", "a[href]"))
            if not a_tag: continue
            raw_url = a_tag.get("href", "")
            if "google.com/url" in raw_url:
                raw_url = urllib.parse.parse_qs(urllib.parse.urlparse(raw_url).query).get("q", [""])[0]
            if not raw_url.startswith("http") or not is_target_domain(raw_url): continue
            t_tag = block.select_one(sel.get("title", "h3"))
            title = t_tag.get_text(strip=True) if t_tag else a_tag.get_text(strip=True)
            page_results.append((raw_url, title))
        
        if not page_results: break
        found.extend(page_results)
        polite_delay()
    return list(dict.fromkeys(found)) # Simple unique preserve order

# ── CRAWLER LOGIC ─────────────────────────────────────────────────────────────

def crawl_url(start_url: str, depth: int = DEFAULT_CRAWL_DEPTH, session=None) -> list[tuple[str, str]]:
    visited, found, queue = set(), [], [(start_url, depth)]
    s = session or build_session()
    while queue and len(visited) < MAX_RECURSIVE_URLS:
        url, d = queue.pop(0)
        if url in visited: continue
        visited.add(url)
        resp = fetch(url, session=s)
        if not resp: continue
        soup = BeautifulSoup(resp.text, "lxml")
        title = soup.title.string.strip() if soup.title else url
        found.append((url, title))
        if d > 0:
            for a in soup.find_all("a", href=True):
                full = normalize_url(a["href"], url)
                if full and is_target_domain(full) and full not in visited:
                    queue.append((full, d - 1))
        polite_delay()
    return found

# ── MAIN EXECUTION ────────────────────────────────────────────────────────────

def main():
    if HAS_RICH:
        console = Console()
        console.print(Panel("[bold green]FILE HUNTER v2.0[/bold green]\n[dim]Single-Script Edition[/dim]", expand=False))
    else:
        print("--- FILE HUNTER v2.0 ---")

    query = input("Enter search keywords: ")
    if not query: return

    # Search
    target_engine = "google"
    if HAS_RICH: console.print(f"[*] Searching {target_engine} for: [bold cyan]{query}[/bold cyan]...")
    
    results = search_engine(target_engine, query, max_pages=2)
    
    if not results:
        print("No results found.")
        return

    # Process and Extract
    final_data = []
    if HAS_RICH:
        with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), BarColumn(), TimeElapsedColumn()) as progress:
            task = progress.add_task("Extracting metadata...", total=len(results))
            for url, title in results:
                meta = extract_metadata(url, title)
                final_data.append(meta)
                progress.advance(task)
    else:
        for url, title in results:
            print(f"Extracting: {url}")
            final_data.append(extract_metadata(url, title))

    # Display Results
    if HAS_RICH:
        table = Table(title="Search Results", box=rbox.MINIMAL_DOUBLE_HEAD)
        table.add_column("Title", style="magenta", no_wrap=True)
        table.add_column("Type", style="cyan")
        table.add_column("Size", style="green")
        table.add_column("Domain", style="dim")
        
        for item in final_data:
            domain = urlparse(item['url']).netloc
            table.add_row(item['title'][:50], item['file_type'], item['file_size'], domain)
        console.print(table)
    else:
        for item in final_data:
            print(f"{item['title']} | {item['file_type']} | {item['file_size']} | {item['url']}")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nExiting...")