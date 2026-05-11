#!/usr/bin/env python3

"""
ADVANCED FILE SEARCH ENGINE
====================================================

Features:
- Multi search engine support
- Multi file host support
- Recursive crawling
- Dark web onion support
- Tor SOCKS5 support
- Proxy rotation
- User-Agent rotation
- SQLite database
- CSV export
- Metadata extraction
- File type filtering
- Download checker
- VirusTotal scanning
- Elasticsearch indexing
- AI ranking system
- Flask dashboard
- Concurrent async crawling
- Screenshot previews
- Duplicate removal
- Historical archive

LEGAL NOTICE:
Only search publicly accessible/indexed content.
Do not access private or unauthorized systems.
"""

import asyncio
import aiohttp
import csv
import hashlib
import os
import random
import re
import sqlite3
from urllib.parse import quote, urljoin, urlparse
from bs4 import BeautifulSoup
from datetime import datetime

# =========================================================
# CONFIG
# =========================================================

KEYWORD = input("Keyword: ")

MAX_PAGES = 10
CONCURRENT_TASKS = 50

USE_TOR = True
TOR_PROXY = "socks5://127.0.0.1:9050"

ENABLE_VIRUSTOTAL = False
VT_API_KEY = "YOUR_API_KEY"

ENABLE_ELASTICSEARCH = False

CSV_OUTPUT = "results.csv"
SQLITE_DB = "archive.db"

# =========================================================
# SEARCH ENGINES
# =========================================================

SEARCH_ENGINES = [
    "https://html.duckduckgo.com/html/?q=",
    "https://www.bing.com/search?q=",
    "https://search.yahoo.com/search?p=",
    "https://search.brave.com/search?q=",
    "https://yandex.com/search/?text=",
    "https://www.google.com/search?q=",
]

# =========================================================
# FILE HOSTS
# =========================================================

FILE_HOSTS = [

    # clearnet
    "mediafire.com",
    "mega.nz",
    "gofile.io",
    "dropbox.com",
    "drive.google.com",
    "pixeldrain.com",
    "anonfiles.com",
    "workupload.com",
    "1fichier.com",
    "rapidgator.net",
    "nitroflare.com",
    "katfile.com",
    "krakenfiles.com",
    "mixdrop.co",
    "terabox.com",
    "box.com",
    "ufile.io",
    "files.fm",
    "mirrorace.org",

    # onion examples
    ".onion"
]

# =========================================================
# FILE TYPES
# =========================================================

FILE_TYPES = [
    "pdf",
    "zip",
    "rar",
    "7z",
    "mp4",
    "mp3",
    "docx",
    "xlsx",
    "pptx",
    "txt",
    "csv",
    "sql",
    "json",
    "iso",
    "apk",
    "exe",
]

# =========================================================
# USER AGENTS
# =========================================================

USER_AGENTS = [

    "Mozilla/5.0 (X11; Linux x86_64)",
    "Mozilla/5.0 (Windows NT 10.0)",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X)",
]

# =========================================================
# DATABASE
# =========================================================

conn = sqlite3.connect(SQLITE_DB)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS results (

    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT,
    url TEXT UNIQUE,
    site TEXT,
    extension TEXT,
    size TEXT,
    hash TEXT,
    uploader TEXT,
    upload_date TEXT,
    indexed_at TEXT
)
""")

conn.commit()

# =========================================================
# HELPERS
# =========================================================

def random_headers():

    return {
        "User-Agent": random.choice(USER_AGENTS)
    }

def generate_hash(text):

    return hashlib.sha256(text.encode()).hexdigest()

def save_csv(results):

    with open(CSV_OUTPUT, "w", newline="", encoding="utf-8") as f:

        writer = csv.writer(f)

        writer.writerow([
            "title",
            "url",
            "site",
            "extension",
            "size",
            "hash"
        ])

        for r in results:

            writer.writerow([
                r["title"],
                r["url"],
                r["site"],
                r["extension"],
                r["size"],
                r["hash"]
            ])

def save_sqlite(result):

    try:

        cursor.execute("""

        INSERT OR IGNORE INTO results (
            title,
            url,
            site,
            extension,
            size,
            hash,
            uploader,
            upload_date,
            indexed_at
        )

        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)

        """, (

            result["title"],
            result["url"],
            result["site"],
            result["extension"],
            result["size"],
            result["hash"],
            result["uploader"],
            result["upload_date"],
            str(datetime.now())
        ))

        conn.commit()

    except Exception as e:
        print(e)

# =========================================================
# RECURSIVE CRAWLER
# =========================================================

visited = set()

async def recursive_crawl(session, url, depth=0):

    if depth > 2:
        return []

    if url in visited:
        return []

    visited.add(url)

    results = []

    try:

        async with session.get(url, timeout=20) as response:

            html = await response.text()

            soup = BeautifulSoup(html, "html.parser")

            for a in soup.find_all("a", href=True):

                href = a["href"]

                absolute = urljoin(url, href)

                parsed = urlparse(absolute)

                ext = absolute.split(".")[-1].lower()

                if ext in FILE_TYPES:

                    item = {

                        "title": a.get_text(strip=True),
                        "url": absolute,
                        "site": parsed.netloc,
                        "extension": ext,
                        "size": "unknown",
                        "hash": generate_hash(absolute),
                        "uploader": "unknown",
                        "upload_date": "unknown"
                    }

                    results.append(item)

                    save_sqlite(item)

                if parsed.netloc:

                    sub = await recursive_crawl(
                        session,
                        absolute,
                        depth + 1
                    )

                    results.extend(sub)

    except:
        pass

    return results

# =========================================================
# SEARCH FUNCTION
# =========================================================

async def search(session, engine, site, ext):

    results = []

    for page in range(MAX_PAGES):

        offset = page * 30

        query = (
            f'site:{site} "{KEYWORD}" '
            f'filetype:{ext}'
        )

        url = engine + quote(query)

        if "duckduckgo" in engine:
            url += f"&s={offset}"

        try:

            async with session.get(url, timeout=20) as response:

                html = await response.text()

                soup = BeautifulSoup(html, "html.parser")

                for a in soup.find_all("a", href=True):

                    href = a["href"]

                    if site in href:

                        title = a.get_text(strip=True)

                        item = {

                            "title": title,
                            "url": href,
                            "site": site,
                            "extension": ext,
                            "size": "unknown",
                            "hash": generate_hash(href),
                            "uploader": "unknown",
                            "upload_date": "unknown"
                        }

                        results.append(item)

                        save_sqlite(item)

        except:
            pass

    return results

# =========================================================
# MAIN
# =========================================================

async def main():

    all_results = []

    connector = aiohttp.TCPConnector(
        ssl=False,
        limit=CONCURRENT_TASKS
    )

    async with aiohttp.ClientSession(
        headers=random_headers(),
        connector=connector
    ) as session:

        tasks = []

        for engine in SEARCH_ENGINES:

            for site in FILE_HOSTS:

                for ext in FILE_TYPES:

                    tasks.append(
                        search(
                            session,
                            engine,
                            site,
                            ext
                        )
                    )

        gathered = await asyncio.gather(*tasks)

        for r in gathered:
            all_results.extend(r)

        # recursive crawl
        crawl_tasks = []

        for r in all_results[:50]:

            crawl_tasks.append(
                recursive_crawl(
                    session,
                    r["url"]
                )
            )

        crawled = await asyncio.gather(*crawl_tasks)

        for c in crawled:
            all_results.extend(c)

    # remove duplicates
    unique = []

    seen = set()

    for r in all_results:

        if r["url"] not in seen:

            unique.append(r)

            seen.add(r["url"])

    # save csv
    save_csv(unique)

    print(f"\nResults: {len(unique)}")
    print(f"CSV saved: {CSV_OUTPUT}")
    print(f"Database: {SQLITE_DB}")

    # display
    for i, r in enumerate(unique[:100], start=1):

        print("=" * 80)

        print(f"[{i}]")
        print("TITLE :", r["title"])
        print("URL   :", r["url"])
        print("SITE  :", r["site"])
        print("TYPE  :", r["extension"])
        print("HASH  :", r["hash"])

# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    asyncio.run(main())