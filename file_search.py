import asyncio
import aiohttp
import csv
import re
import time
from urllib.parse import urlparse, urljoin
from collections import Counter, defaultdict
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor

from rich.console import Console
from rich.table import Table
from rich.live import Live

console = Console()

# -----------------------------
# CONFIG
# -----------------------------

FILE_HOSTS = [
    "mediafire.com", "mega.nz", "gofile.io", "dropbox.com",
    "drive.google.com", "pixeldrain.com", "workupload.com",
    "1fichier.com", "rapidgator.net", "nitroflare.com",
    "katfile.com", "krakenfiles.com", "mixdrop.co",
    "terabox.com", "box.com", "ufile.io", "files.fm",
    "mirrorace.org"
]

FILE_EXTENSIONS = ["pdf", "zip", "mp4", "rar", "7z", "docx", "iso"]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
}

# -----------------------------
# UTILITIES
# -----------------------------

def extract_file_type(url):
    match = re.search(r"\.([a-zA-Z0-9]+)(?:\?|$)", url)
    return match.group(1).lower() if match else ""

def is_valid_file(url, filters):
    if not filters:
        return True
    ext = extract_file_type(url)
    return ext in filters

def get_domain(url):
    return urlparse(url).netloc.lower()

def is_target_site(url):
    domain = get_domain(url)
    return any(host in domain for host in FILE_HOSTS)

def parse_size(text):
    if not text:
        return ""
    match = re.search(r"(\d+(\.\d+)?)\s?(MB|GB|KB)", text.upper())
    return match.group(0) if match else ""

# -----------------------------
# SEARCH PROVIDER (PLUGGABLE)
# -----------------------------
# Replace this with:
# - Bing API
# - Brave API
# - SerpAPI
# - Yandex API wrapper

async def mock_search(query):
    """Simulated search results (replace with real API)."""
    return [
        f"https://mediafire.com/file/example_{i}.zip" for i in range(5)
    ]

# -----------------------------
# CRAWLER
# -----------------------------

class Crawler:
    def __init__(self, concurrency=20, depth=2, filters=None):
        self.semaphore = asyncio.Semaphore(concurrency)
        self.depth = depth
        self.filters = filters or []
        self.results = []
        self.visited = set()
        self.keyword_counter = Counter()

    async def fetch(self, session, url):
        async with self.semaphore:
            try:
                async with session.get(url, timeout=10) as resp:
                    if "text/html" in resp.headers.get("Content-Type", ""):
                        return await resp.text()
            except:
                return None

    async def extract_links(self, html, base_url):
        soup = BeautifulSoup(html, "html.parser")
        links = []

        for a in soup.find_all("a", href=True):
            full_url = urljoin(base_url, a["href"])
            links.append(full_url)

        return links

    def extract_title(self, html):
        soup = BeautifulSoup(html, "html.parser")
        return soup.title.text.strip() if soup.title else ""

    async def crawl(self, session, url, depth=0):
        if url in self.visited or depth > self.depth:
            return

        self.visited.add(url)

        html = await self.fetch(session, url)
        if not html:
            return

        title = self.extract_title(html)
        file_type = extract_file_type(url)

        if is_valid_file(url, self.filters):
            self.results.append({
                "url": url,
                "title": title,
                "file_type": file_type,
                "file_size": ""
            })

        words = re.findall(r"\w+", title.lower())
        self.keyword_counter.update(words)

        links = await self.extract_links(html, url)

        tasks = []
        for link in links:
            if is_target_site(link):
                tasks.append(self.crawl(session, link, depth + 1))

        await asyncio.gather(*tasks)

# -----------------------------
# SEARCH ENGINE WRAPPER
# -----------------------------

async def search_and_crawl(query, crawler):
    results = await mock_search(query)

    async with aiohttp.ClientSession(headers=HEADERS) as session:
        tasks = [crawler.crawl(session, url, 0) for url in results]
        await asyncio.gather(*tasks)

# -----------------------------
# CSV EXPORT
# -----------------------------

def save_csv(data, filename="results.csv"):
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["url", "title", "file_type", "file_size"])
        writer.writeheader()
        writer.writerows(data)

# -----------------------------
# LIVE UI
# -----------------------------

def live_ui(crawler):
    table = Table(title="Live File Search Engine")

    table.add_column("URL", overflow="fold")
    table.add_column("Title")
    table.add_column("Type")

    for r in crawler.results[-10:]:
        table.add_row(r["url"], r["title"], r["file_type"])

    return table

# -----------------------------
# MAIN
# -----------------------------

async def main():
    query = input("Search query: ")
    filters = input("File filters (comma separated, e.g. pdf,zip): ").split(",")
    filters = [f.strip() for f in filters if f.strip()]

    crawler = Crawler(concurrency=50, depth=2, filters=filters)

    with Live(console=console, refresh_per_second=2) as live:
        task = asyncio.create_task(search_and_crawl(query, crawler))

        while not task.done():
            live.update(live_ui(crawler))
            await asyncio.sleep(0.5)

        await task

    save_csv(crawler.results)

    console.print("\n[green]Done! Results saved to results.csv[/green]")

    console.print("\nTop Keywords:")
    for word, count in crawler.keyword_counter.most_common(10):
        console.print(f"{word}: {count}")

if __name__ == "__main__":
    asyncio.run(main())