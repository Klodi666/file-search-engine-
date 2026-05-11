#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
╔═══════════════════════════════════════════════════════════════════════════════╗
║                    ███████╗██╗██╗     ███████╗    ██╗  ██╗██╗   ██╗███╗   ██╗████████╗███████╗██████╗     ║
║                    ██╔════╝██║██║     ██╔════╝    ██║  ██║██║   ██║████╗  ██║╚══██╔══╝██╔════╝██╔══██╗    ║
║                    █████╗  ██║██║     █████╗      ███████║██║   ██║██╔██╗ ██║   ██║   █████╗  ██████╔╝    ║
║                    ██╔══╝  ██║██║     ██╔══╝      ██╔══██║██║   ██║██║╚██╗██║   ██║   ██╔══╝  ██╔══██╗    ║
║                    ██║     ██║███████╗███████╗    ██║  ██║╚██████╔╝██║ ╚████║   ██║   ███████╗██║  ██║    ║
║                    ╚═╝     ╚═╝╚══════╝╚══════╝    ╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═══╝   ╚═╝   ╚══════╝╚═╝  ╚═╝    ║
║                      FILE HUNTER v3.1 | FIXED SEARCH ENGINE PLACEHOLDERS                                      ║
╚═══════════════════════════════════════════════════════════════════════════════════════════════════════════════╝
"""

import asyncio
import aiohttp
import csv
import hashlib
import json
import logging
import random
import re
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from urllib.parse import quote, urljoin, urlparse, parse_qs

from bs4 import BeautifulSoup

# Rich UI (optional)
try:
    from rich.console import Console
    from rich.live import Live
    from rich.table import Table
    from rich.panel import Panel
    from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn
    from rich import box as rbox
    from rich.layout import Layout
    HAS_RICH = True
    console = Console()
except ImportError:
    HAS_RICH = False
    console = None

# Fake user‑agent (optional)
try:
    from fake_useragent import UserAgent
    ua = UserAgent()
    def get_ua():
        return ua.random
except Exception:
    _AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
        "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0"
    ]
    def get_ua():
        return random.choice(_AGENTS)

# =================================================================================================
# CONFIGURATION
# =================================================================================================
TARGET_DOMAINS = [
    "mediafire.com", "mega.nz", "gofile.io", "dropbox.com", "drive.google.com",
    "pixeldrain.com", "anonfiles.com", "workupload.com", "1fichier.com",
    "rapidgator.net", "nitroflare.com", "katfile.com", "krakenfiles.com",
    "mixdrop.co", "terabox.com", "box.com", "ufile.io", "files.fm", "mirrorace.org",
    "send.cm", "upload.ee", "easyupload.io", "bayfiles.com", "solidfiles.com"
]

SEARCH_ENGINES = {
    "google": {
        "url": "https://www.google.com/search?q={query}&start={start}",
        "selector": {"result": "div.g", "url": "a[href]", "title": "h3"},
        "start_param": "start"
    },
    "bing": {
        "url": "https://www.bing.com/search?q={query}&first={first}",
        "selector": {"result": "li.b_algo", "url": "h2 a", "title": "h2 a"},
        "start_param": "first"
    },
    "brave": {
        "url": "https://search.brave.com/search?q={query}&offset={offset}",
        "selector": {"result": "div.snippet", "url": "a.result-header", "title": "span.snippet-title"},
        "start_param": "offset"
    },
    "yahoo": {
        "url": "https://search.yahoo.com/search?p={query}&b={b}",
        "selector": {"result": "div.dd.algo", "url": "h3 a", "title": "h3 a"},
        "start_param": "b"
    },
    "yandex": {
        "url": "https://yandex.com/search/?text={query}&p={page}",
        "selector": {"result": "li.serp-item", "url": "a.link_theme_outer", "title": "h2"},
        "start_param": "page"
    },
    "ddg": {
        "url": "https://html.duckduckgo.com/html/?q={query}&s={s}",
        "selector": {"result": "div.result", "url": "a.result__a", "title": "a.result__a"},
        "start_param": "s"
    }
}

DEFAULT_MAX_PAGES = 3
DEFAULT_DEPTH = 2
DEFAULT_CONCURRENCY = 30
DEFAULT_TIMEOUT = 15
DEFAULT_DELAY = (0.5, 1.5)

OUTPUT_CSV = "results.csv"
OUTPUT_JSON = "results.json"
SQLITE_DB = "file_hunter_cache.db"

# =================================================================================================
# DATABASE SETUP
# =================================================================================================
def init_db():
    conn = sqlite3.connect(SQLITE_DB)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS crawled_urls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT UNIQUE,
            title TEXT,
            file_type TEXT,
            file_size TEXT,
            source_engine TEXT,
            hash TEXT,
            first_seen TEXT,
            last_checked TEXT,
            is_alive INTEGER DEFAULT 1
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_url ON crawled_urls(url)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_hash ON crawled_urls(hash)")
    conn.commit()
    conn.close()

init_db()

def url_hash(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:16]

def normalize_url(url: str, base: str = "") -> str:
    try:
        full = urljoin(base, url)
        parsed = urlparse(full)
        if parsed.scheme not in ("http", "https"):
            return ""
        netloc = parsed.netloc.lower().replace("www.", "")
        if any(netloc == d or netloc.endswith(f".{d}") for d in TARGET_DOMAINS):
            return full.split("?")[0]
        return full
    except Exception:
        return ""

def is_target_domain(url: str) -> bool:
    try:
        netloc = urlparse(url).netloc.lower().replace("www.", "")
        return any(netloc == d or netloc.endswith(f".{d}") for d in TARGET_DOMAINS)
    except:
        return False

def extract_file_type(url: str, title: str = "") -> str:
    path = urlparse(url).path.lower()
    ext_match = re.search(r"\.([a-z0-9]{2,6})(?:[?#]|$)", path)
    if ext_match:
        return ext_match.group(1)
    if title:
        ext_match = re.search(r"\.([a-z0-9]{2,6})(?:\s|$)", title.lower())
        if ext_match:
            return ext_match.group(1)
    return ""

_SIZE_PATTERNS = [
    re.compile(r"([\d,.]+)\s*(GB|GiB)", re.I),
    re.compile(r"([\d,.]+)\s*(MB|MiB)", re.I),
    re.compile(r"([\d,.]+)\s*(KB|KiB)", re.I),
    re.compile(r"([\d,.]+)\s*bytes?", re.I),
]
def parse_size_from_text(text: str) -> str:
    for pattern in _SIZE_PATTERNS:
        m = pattern.search(text)
        if m:
            return f"{m.group(1)} {m.group(2) or 'bytes'}"
    return ""

# Host‑specific metadata extractors
def extract_mediafire(soup):
    meta = {}
    name = soup.select_one("div.filename, .dl-btn-label, .file-info-name")
    if name:
        meta["title"] = name.get_text(strip=True)
    size = soup.select_one("div.file-size, span.file-size, .file-info-size")
    if size:
        meta["file_size"] = size.get_text(strip=True)
    return meta

def extract_krakenfiles(soup):
    meta = {}
    size = soup.select_one(".file-info-size, span[class*='size']")
    if size:
        meta["file_size"] = size.get_text(strip=True)
    name = soup.select_one("h1.filename, .file-title")
    if name:
        meta["title"] = name.get_text(strip=True)
    return meta

HOST_EXTRACTORS = {
    "mediafire.com": extract_mediafire,
    "krakenfiles.com": extract_krakenfiles,
}

async def fetch_metadata(url: str, session: aiohttp.ClientSession, title_hint: str = "") -> dict:
    result = {
        "url": url,
        "title": title_hint,
        "file_type": extract_file_type(url, title_hint),
        "file_size": ""
    }
    try:
        async with session.get(url, timeout=DEFAULT_TIMEOUT, allow_redirects=True) as resp:
            if resp.status != 200:
                return result
            html = await resp.text()
            soup = BeautifulSoup(html, "lxml")
            if not result["title"] and soup.title:
                result["title"] = soup.title.string.strip()
            host = urlparse(url).netloc.lower().replace("www.", "")
            for domain, extractor in HOST_EXTRACTORS.items():
                if host == domain or host.endswith("." + domain):
                    meta = extractor(soup)
                    result.update(meta)
                    break
            if not result["file_size"]:
                result["file_size"] = parse_size_from_text(soup.get_text(" ", strip=True))
    except Exception:
        pass
    return result

# =================================================================================================
# SEARCH ENGINE SCRAPER (FIXED)
# =================================================================================================
async def search_engine(engine: str, query: str, max_pages: int, session: aiohttp.ClientSession, semaphore: asyncio.Semaphore):
    if engine not in SEARCH_ENGINES:
        return []
    conf = SEARCH_ENGINES[engine]
    results = []
    encoded_query = quote(query)
    for page in range(max_pages):
        if engine == "yandex":
            # Yandex uses page number directly
            url = conf["url"].format(query=encoded_query, page=page)
        else:
            start_val = page * 10
            param_name = conf["start_param"]
            # Build URL with correct placeholder
            url = conf["url"].format(query=encoded_query, **{param_name: start_val})
        async with semaphore:
            try:
                async with session.get(url, timeout=DEFAULT_TIMEOUT) as resp:
                    if resp.status != 200:
                        break
                    html = await resp.text()
                    soup = BeautifulSoup(html, "lxml")
                    sel = conf["selector"]
                    page_results = []
                    for block in soup.select(sel["result"]):
                        a_tag = block.select_one(sel["url"])
                        if not a_tag:
                            continue
                        raw_url = a_tag.get("href", "")
                        if "google.com/url" in raw_url:
                            parsed = urlparse(raw_url)
                            qs = parse_qs(parsed.query)
                            raw_url = qs.get("q", [""])[0]
                        if not raw_url.startswith("http") or not is_target_domain(raw_url):
                            continue
                        title_tag = block.select_one(sel["title"])
                        title = title_tag.get_text(strip=True) if title_tag else a_tag.get_text(strip=True)
                        page_results.append((raw_url, title))
                    if not page_results:
                        break
                    results.extend(page_results)
                    await asyncio.sleep(random.uniform(*DEFAULT_DELAY))
            except Exception as e:
                if HAS_RICH:
                    console.print(f"[red]Error with {engine} page {page}: {e}[/red]")
                break
    # deduplicate
    seen = set()
    unique = []
    for url, title in results:
        if url not in seen:
            seen.add(url)
            unique.append((url, title))
    return unique

# =================================================================================================
# RECURSIVE CRAWLER
# =================================================================================================
async def crawl_file_host(start_url: str, depth: int, session: aiohttp.ClientSession, semaphore: asyncio.Semaphore, visited: set):
    discovered = []
    queue = [(start_url, depth)]
    while queue and len(visited) < 500:
        url, d = queue.pop(0)
        if url in visited:
            continue
        visited.add(url)
        async with semaphore:
            try:
                async with session.get(url, timeout=DEFAULT_TIMEOUT) as resp:
                    if resp.status != 200:
                        continue
                    html = await resp.text()
                    soup = BeautifulSoup(html, "lxml")
                    title = soup.title.string.strip() if soup.title else url
                    discovered.append((url, title))
                    if d > 0:
                        for a in soup.find_all("a", href=True):
                            full = normalize_url(a["href"], url)
                            if full and is_target_domain(full) and full not in visited:
                                queue.append((full, d - 1))
                    await asyncio.sleep(random.uniform(*DEFAULT_DELAY))
            except Exception:
                continue
    return discovered

# =================================================================================================
# DASHBOARD (Rich UI)
# =================================================================================================
class HunterDashboard:
    def __init__(self):
        self.results = []
        self.found_urls = set()
        self.keyword_counts = Counter()
        self.start_time = datetime.now()
        if HAS_RICH:
            self.console = Console()
            self.live = None

    def add_result(self, url: str, title: str, file_type: str, file_size: str):
        if url not in self.found_urls:
            self.found_urls.add(url)
            self.results.append({
                "url": url,
                "title": title,
                "file_type": file_type,
                "file_size": file_size
            })
            words = re.findall(r"\w+", title.lower())
            self.keyword_counts.update(words)

    def get_stats(self):
        elapsed = (datetime.now() - self.start_time).total_seconds()
        return {
            "total_urls": len(self.results),
            "elapsed": elapsed,
            "rate": len(self.results) / elapsed if elapsed > 0 else 0,
            "top_keywords": self.keyword_counts.most_common(5)
        }

    def render_table(self):
        if not HAS_RICH:
            return None
        table = Table(title="🔥 LIVE FILE HITS", box=rbox.MINIMAL_DOUBLE_HEAD, style="bold cyan")
        table.add_column("#", style="dim")
        table.add_column("Title", style="magenta", max_width=40)
        table.add_column("Type", style="green")
        table.add_column("Size", style="yellow")
        table.add_column("Domain", style="blue")
        for idx, res in enumerate(self.results[-20:], 1):
            domain = urlparse(res["url"]).netloc[:25]
            table.add_row(str(idx), res["title"][:50], res["file_type"], res["file_size"], domain)
        return table

    def render_panel(self):
        if not HAS_RICH:
            return None
        stats = self.get_stats()
        content = f"[bold green]⚡ HUNTER STATUS[/bold green]\n"
        content += f"📦 Total Files Found: [cyan]{stats['total_urls']}[/cyan]\n"
        content += f"⏱️  Elapsed: [yellow]{stats['elapsed']:.1f}s[/yellow]\n"
        content += f"🚀 Rate: [red]{stats['rate']:.2f} URLs/s[/red]\n"
        content += f"🔥 Top Keywords: [white]{', '.join([f'{k}({v})' for k,v in stats['top_keywords']])}[/white]"
        return Panel(content, title="[bold white]🕵️ FILE HUNTER DASHBOARD[/bold white]", border_style="red")

    def update_live(self):
        if HAS_RICH and self.live:
            layout = Layout()
            layout.split_column(
                Layout(name="header", size=3),
                Layout(name="main"),
                Layout(name="footer", size=3)
            )
            layout["main"].split_row(
                Layout(self.render_panel()),
                Layout(self.render_table())
            )
            self.live.update(layout)

# =================================================================================================
# CORE HUNT FUNCTION
# =================================================================================================
async def run_hunt(query, engines, pages, depth, concurrency, timeout_val, use_tor, proxy_url, max_urls, output_csv, output_json, verbose):
    # Setup logging
    logging.basicConfig(level=logging.INFO if verbose else logging.WARNING)
    if HAS_RICH:
        console.print(Panel(f"[bold cyan]HUNT STARTED[/bold cyan]\nQuery: {query}\nEngines: {engines}\nPages: {pages}\nDepth: {depth}"))

    # Proxy connector
    connector = None
    if use_tor:
        try:
            from aiohttp_socks import ProxyConnector
            connector = ProxyConnector.from_url("socks5://127.0.0.1:9050")
            if HAS_RICH:
                console.print("[yellow]⚠️ TOR PROXY ENABLED (socks5://127.0.0.1:9050)[/yellow]")
        except ImportError:
            logging.warning("aiohttp_socks not installed. Tor disabled. Install: pip install aiohttp_socks")
            connector = aiohttp.TCPConnector(ssl=False, limit=concurrency)
    elif proxy_url:
        try:
            from aiohttp_socks import ProxyConnector
            connector = ProxyConnector.from_url(proxy_url)
        except ImportError:
            connector = aiohttp.TCPConnector(ssl=False, limit=concurrency)
    else:
        connector = aiohttp.TCPConnector(ssl=False, limit=concurrency)

    headers = {"User-Agent": get_ua(), "Accept-Language": "en-US,en;q=0.9", "Accept": "text/html"}
    async with aiohttp.ClientSession(headers=headers, connector=connector, timeout=aiohttp.ClientTimeout(total=timeout_val)) as session:
        semaphore = asyncio.Semaphore(concurrency)
        dashboard = HunterDashboard()

        # Search phase
        engine_list = [e.strip() for e in engines.split(",") if e.strip() in SEARCH_ENGINES]
        if not engine_list:
            print("No valid engines selected.")
            return

        search_tasks = [search_engine(eng, query, pages, session, semaphore) for eng in engine_list]
        all_search_results = await asyncio.gather(*search_tasks)
        raw_links = []
        for res in all_search_results:
            raw_links.extend(res)

        # Deduplicate
        seen = set()
        unique_links = []
        for url, title in raw_links:
            if url not in seen:
                seen.add(url)
                unique_links.append((url, title))

        if HAS_RICH:
            console.print(f"[green]✓ Search complete: {len(unique_links)} unique links found[/green]")
        else:
            print(f"Search complete: {len(unique_links)} links")

        # Metadata extraction
        meta_tasks = [fetch_metadata(url, session, title) for url, title in unique_links[:max_urls]]
        if HAS_RICH:
            with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), transient=True) as prog:
                task = prog.add_task("Extracting metadata...", total=len(meta_tasks))
                metadata_results = []
                for coro in asyncio.as_completed(meta_tasks):
                    res = await coro
                    metadata_results.append(res)
                    prog.update(task, advance=1)
        else:
            metadata_results = await asyncio.gather(*meta_tasks)

        for meta in metadata_results:
            dashboard.add_result(meta["url"], meta["title"], meta["file_type"], meta["file_size"])
            # Insert into DB
            conn = sqlite3.connect(SQLITE_DB)
            cur = conn.cursor()
            cur.execute("INSERT OR IGNORE INTO crawled_urls (url, title, file_type, file_size, hash, first_seen, last_checked) VALUES (?,?,?,?,?,?,?)",
                        (meta["url"], meta["title"], meta["file_type"], meta["file_size"], url_hash(meta["url"]), str(datetime.now()), str(datetime.now())))
            conn.commit()
            conn.close()

        # Recursive crawling
        if depth > 0 and metadata_results:
            if HAS_RICH:
                console.print(f"[cyan]🌀 Recursive crawling (depth={depth}) on first {min(30, len(metadata_results))} hosts...[/cyan]")
            visited_set = set()
            crawl_tasks = []
            for item in metadata_results[:30]:
                crawl_tasks.append(crawl_file_host(item["url"], depth, session, semaphore, visited_set))
            crawled_batches = await asyncio.gather(*crawl_tasks)
            new_links = []
            for batch in crawled_batches:
                new_links.extend(batch)
            # Deduplicate new_links
            unique_new = {}
            for url, title in new_links:
                if url not in unique_new:
                    unique_new[url] = title
            if unique_new:
                if HAS_RICH:
                    console.print(f"[green]✓ Crawled {len(unique_new)} new file links[/green]")
                meta_tasks2 = [fetch_metadata(url, session, title) for url, title in list(unique_new.items())[:max_urls]]
                extra_metadata = await asyncio.gather(*meta_tasks2)
                for meta in extra_metadata:
                    dashboard.add_result(meta["url"], meta["title"], meta["file_type"], meta["file_size"])
                    conn = sqlite3.connect(SQLITE_DB)
                    cur = conn.cursor()
                    cur.execute("INSERT OR IGNORE INTO crawled_urls (url, title, file_type, file_size, hash, first_seen, last_checked) VALUES (?,?,?,?,?,?,?)",
                                (meta["url"], meta["title"], meta["file_type"], meta["file_size"], url_hash(meta["url"]), str(datetime.now()), str(datetime.now())))
                    conn.commit()
                    conn.close()

        # Save results
        with open(output_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["url", "title", "file_type", "file_size"])
            writer.writeheader()
            writer.writerows(dashboard.results)
        with open(output_json, "w", encoding="utf-8") as f:
            json.dump(dashboard.results, f, indent=2, ensure_ascii=False)

        if HAS_RICH:
            console.print(Panel.fit(f"[bold green]✅ HUNT COMPLETE![/bold green]\n📄 CSV: {output_csv}\n🗄️ JSON: {output_json}\n💾 SQLite: {SQLITE_DB}\n🔢 Total Unique Files: {len(dashboard.results)}", border_style="green"))
        else:
            print(f"\nResults saved to {output_csv} and {output_json}\nTotal files: {len(dashboard.results)}")

# =================================================================================================
# MENU SYSTEM
# =================================================================================================
def print_menu():
    print("\n" + "="*60)
    print("       ADVANCED FILE HUNTER - MAIN MENU")
    print("="*60)
    print(" 1. 🔍 Start a new file hunt")
    print(" 2. 📋 Show last hunt results from database")
    print(" 3. 💾 Export database to CSV/JSON")
    print(" 4. 📊 Show database statistics")
    print(" 5. 🧹 Clean database (remove duplicates)")
    print(" 6. 🚪 Exit")
    print("="*60)

def show_last_results(limit=50):
    conn = sqlite3.connect(SQLITE_DB)
    cur = conn.cursor()
    cur.execute("SELECT url, title, file_type, file_size, first_seen FROM crawled_urls ORDER BY id DESC LIMIT ?", (limit,))
    rows = cur.fetchall()
    conn.close()
    if not rows:
        print("No results in database.")
        return
    if HAS_RICH:
        table = Table(title=f"Last {len(rows)} Files")
        table.add_column("URL", style="cyan", max_width=50)
        table.add_column("Title", style="magenta")
        table.add_column("Type", style="green")
        table.add_column("Size", style="yellow")
        table.add_column("Date", style="dim")
        for row in rows:
            table.add_row(row[0][:60], row[1][:40], row[2], row[3], row[4][:19])
        console.print(table)
    else:
        for row in rows:
            print(f"{row[0]} | {row[1]} | {row[2]} | {row[3]} | {row[4]}")

def export_database(csv_path="db_export.csv", json_path="db_export.json"):
    conn = sqlite3.connect(SQLITE_DB)
    cur = conn.cursor()
    cur.execute("SELECT url, title, file_type, file_size, first_seen FROM crawled_urls")
    rows = cur.fetchall()
    conn.close()
    if not rows:
        print("No data to export.")
        return
    data = [{"url": r[0], "title": r[1], "file_type": r[2], "file_size": r[3], "first_seen": r[4]} for r in rows]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["url", "title", "file_type", "file_size", "first_seen"])
        writer.writeheader()
        writer.writerows(data)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"Exported {len(data)} records to {csv_path} and {json_path}")

def show_stats():
    conn = sqlite3.connect(SQLITE_DB)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM crawled_urls")
    total = cur.fetchone()[0]
    cur.execute("SELECT COUNT(DISTINCT file_type) FROM crawled_urls WHERE file_type != ''")
    unique_types = cur.fetchone()[0]
    cur.execute("SELECT file_type, COUNT(*) FROM crawled_urls WHERE file_type != '' GROUP BY file_type ORDER BY COUNT(*) DESC LIMIT 5")
    top_types = cur.fetchall()
    conn.close()
    print(f"\n📊 DATABASE STATISTICS")
    print(f"   Total indexed URLs: {total}")
    print(f"   Unique file types: {unique_types}")
    if top_types:
        print("   Top 5 file types:")
        for ft, cnt in top_types:
            print(f"      {ft}: {cnt}")
    else:
        print("   No file type data yet.")

def clean_duplicates():
    conn = sqlite3.connect(SQLITE_DB)
    cur = conn.cursor()
    cur.execute("DELETE FROM crawled_urls WHERE id NOT IN (SELECT MIN(id) FROM crawled_urls GROUP BY url)")
    removed = cur.rowcount
    conn.commit()
    conn.close()
    print(f"Removed {removed} duplicate entries.")

def run_interactive_hunt():
    print("\n--- NEW FILE HUNT ---")
    query = input("Enter search keywords: ").strip()
    if not query:
        print("Query cannot be empty.")
        return
    engines = input("Engines (comma-separated, default google,bing,brave): ").strip()
    if not engines:
        engines = "google,bing,brave"
    pages = input("Pages per engine (default 3): ").strip()
    pages = int(pages) if pages.isdigit() else DEFAULT_MAX_PAGES
    depth = input("Crawl depth (default 2): ").strip()
    depth = int(depth) if depth.isdigit() else DEFAULT_DEPTH
    use_tor = input("Use Tor? (y/n, default n): ").strip().lower() == 'y'
    proxy = input("Custom proxy URL (optional, e.g. socks5://127.0.0.1:9050): ").strip()
    if not proxy and use_tor:
        proxy = "socks5://127.0.0.1:9050"
    verbose = input("Verbose logging? (y/n, default n): ").strip().lower() == 'y'

    asyncio.run(run_hunt(
        query=query,
        engines=engines,
        pages=pages,
        depth=depth,
        concurrency=DEFAULT_CONCURRENCY,
        timeout_val=DEFAULT_TIMEOUT,
        use_tor=use_tor,
        proxy_url=proxy if proxy else None,
        max_urls=200,
        output_csv=OUTPUT_CSV,
        output_json=OUTPUT_JSON,
        verbose=verbose
    ))

def main():
    if HAS_RICH:
        console.print(Panel("[bold red]ADVANCED FILE HUNTER v3.1[/bold red]\n[dim]Menu‑driven | Tor ready | File crawler[/dim]", expand=False))
    else:
        print("=== ADVANCED FILE HUNTER v3.1 (CLI mode) ===")

    while True:
        print_menu()
        choice = input("Select an option [1-6]: ").strip()
        if choice == '1':
            run_interactive_hunt()
        elif choice == '2':
            show_last_results()
        elif choice == '3':
            export_database()
        elif choice == '4':
            show_stats()
        elif choice == '5':
            clean_duplicates()
        elif choice == '6':
            print("Exiting. Good hunting!")
            break
        else:
            print("Invalid choice, please try again.")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[!] Interrupted by user.")
    except Exception as e:
        print(f"\n[!] Fatal error: {e}")