#!/usr/bin/env python3
"""
melo - Mail Extractor Locator
Crawl one or more websites and extract every email address found.

Usage examples:
    python3 melo.py https://example.com
    python3 melo.py https://example.com -d 2 -o emails.txt
    python3 melo.py example.com another.com --json out.json
"""

import argparse
import json
import re
import sys
import time
from collections import deque
from urllib.parse import urljoin, urlparse

try:
    import requests
except ImportError:
    sys.exit("melo requires 'requests'. Install with:  pip install requests")

# ----------------------------------------------------------------------------
# Colors
# ----------------------------------------------------------------------------
YELLOW = "\033[93m"
GREEN = "\033[92m"
CYAN = "\033[96m"
RED = "\033[91m"
DIM = "\033[2m"
RESET = "\033[0m"

BANNER = r"""
 __  __ _____ _     ___
|  \/  | ____| |   / _ \
| |\/| |  _| | |  | | | |
| |  | | |___| |__| |_| |
|_|  |_|_____|_____\___/
"""


def print_banner():
    print(YELLOW + BANNER + RESET)
    print(YELLOW + "        Mail Extractor Locator" + RESET)
    print(DIM + "        find every email on a website\n" + RESET)


# ----------------------------------------------------------------------------
# Email extraction
# ----------------------------------------------------------------------------
# Matches standard emails plus common obfuscations ([at], (dot), " at ", etc.)
EMAIL_RE = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
)

MAILTO_RE = re.compile(r'mailto:([^"\'?>\s]+)', re.IGNORECASE)

# Filter out junk that looks like an email but usually isn't a contact.
JUNK_EXT = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp",
            ".css", ".js", ".ico", ".woff", ".woff2", ".ttf")


def deobfuscate(text):
    """Turn common human-readable obfuscations back into real emails."""
    t = text
    replacements = [
        (r"\s*\[\s*at\s*\]\s*", "@"),
        (r"\s*\(\s*at\s*\)\s*", "@"),
        (r"\s+at\s+", "@"),
        (r"\s*\[\s*dot\s*\]\s*", "."),
        (r"\s*\(\s*dot\s*\)\s*", "."),
        (r"\s+dot\s+", "."),
    ]
    for pat, rep in replacements:
        t = re.sub(pat, rep, t, flags=re.IGNORECASE)
    return t


def extract_emails(text):
    found = set()
    for m in MAILTO_RE.findall(text):
        found.add(m.strip().lower())
    combined = text + "\n" + deobfuscate(text)
    for m in EMAIL_RE.findall(combined):
        e = m.strip().lower().rstrip(".")
        if e.endswith(JUNK_EXT):
            continue
        found.add(e)
    return found


# ----------------------------------------------------------------------------
# Link discovery for crawling
# ----------------------------------------------------------------------------
LINK_RE = re.compile(r'href\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)


def same_domain(base, url):
    return urlparse(base).netloc == urlparse(url).netloc


def find_links(base_url, html):
    links = set()
    for href in LINK_RE.findall(html):
        if href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        full = urljoin(base_url, href)
        if full.startswith(("http://", "https://")):
            links.add(full.split("#")[0])
    return links


# ----------------------------------------------------------------------------
# Crawler
# ----------------------------------------------------------------------------
class Melo:
    def __init__(self, depth=1, timeout=10, delay=0.0, max_pages=100,
                 user_agent=None, verbose=True):
        self.depth = depth
        self.timeout = timeout
        self.delay = delay
        self.max_pages = max_pages
        self.verbose = verbose
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": user_agent or
            "Mozilla/5.0 (compatible; melo/1.0; +email-finder)"
        })
        self.emails = {}          # email -> set(source urls)
        self.visited = set()

    def log(self, msg, color=""):
        if self.verbose:
            print(f"{color}{msg}{RESET}")

    def fetch(self, url, quiet_conn_error=False):
        try:
            r = self.session.get(url, timeout=self.timeout, allow_redirects=True)
            ctype = r.headers.get("Content-Type", "")
            if "html" not in ctype and "text" not in ctype and ctype:
                return None
            return r.text
        except requests.exceptions.ConnectionError as e:
            if not quiet_conn_error:
                self.log(f"  ! {url}  ({e.__class__.__name__})", RED)
            return None
        except requests.RequestException as e:
            self.log(f"  ! {url}  ({e.__class__.__name__})", RED)
            return None

    def fetch_start(self, start_url):
        """Fetch the seed URL, returning (working_url, html).

        When the user gives a scheme-less host we default to https:// but
        transparently fall back to http:// if the site refuses the TLS
        connection, so an http-only host doesn't die with a ConnectionError.
        """
        if "://" in start_url:
            return start_url, self.fetch(start_url)

        https_url = "https://" + start_url
        html = self.fetch(https_url, quiet_conn_error=True)
        if html is not None:
            return https_url, html

        http_url = "http://" + start_url
        html = self.fetch(http_url)
        if html is not None:
            self.log(f"  ~ falling back to http:// for {start_url}", DIM)
            return http_url, html

        # Both failed: report against the https attempt for a clear message.
        self.log(f"  ! {https_url}  (ConnectionError)", RED)
        return https_url, None

    def record(self, emails, source):
        for e in emails:
            self.emails.setdefault(e, set()).add(source)

    def crawl(self, start_url):
        # Resolve the seed URL's scheme (https:// with http:// fallback) up
        # front so the working scheme propagates to every discovered link.
        start_url, start_html = self.fetch_start(start_url)
        queue = deque([(start_url, 0, start_html)])
        seen = {start_url}

        while queue and len(self.visited) < self.max_pages:
            url, level, prefetched = queue.popleft()
            if url in self.visited:
                continue
            self.visited.add(url)

            self.log(f"[{len(self.visited):>3}] scanning  {url}", CYAN)
            html = prefetched if prefetched is not None else self.fetch(url)
            if html is None:
                continue

            emails = extract_emails(html)
            if emails:
                self.record(emails, url)
                for e in sorted(emails):
                    self.log(f"      + {e}", GREEN)

            if level < self.depth:
                for link in find_links(url, html):
                    if link not in seen and same_domain(start_url, link):
                        seen.add(link)
                        queue.append((link, level + 1, None))

            if self.delay:
                time.sleep(self.delay)

    def run(self, urls):
        for u in urls:
            self.crawl(u)
        return self.emails


# ----------------------------------------------------------------------------
# Output
# ----------------------------------------------------------------------------
def report(emails, txt_out=None, json_out=None):
    print()
    if not emails:
        print(RED + "No email addresses found." + RESET)
        return

    print(YELLOW + f"Found {len(emails)} unique email address(es):" + RESET)
    for e in sorted(emails):
        print(f"  {GREEN}{e}{RESET}  {DIM}({len(emails[e])} page(s)){RESET}")

    if txt_out:
        with open(txt_out, "w") as f:
            f.write("\n".join(sorted(emails)) + "\n")
        print(DIM + f"\nSaved plain list -> {txt_out}" + RESET)

    if json_out:
        data = {e: sorted(src) for e, src in emails.items()}
        with open(json_out, "w") as f:
            json.dump(data, f, indent=2)
        print(DIM + f"Saved JSON (with sources) -> {json_out}" + RESET)


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        prog="melo",
        description="melo - crawl websites and extract email addresses.",
    )
    parser.add_argument("urls", nargs="+", help="one or more website URLs")
    parser.add_argument("-d", "--depth", type=int, default=1,
                        help="crawl depth (default: 1)")
    parser.add_argument("-m", "--max-pages", type=int, default=100,
                        help="max pages to visit per run (default: 100)")
    parser.add_argument("-t", "--timeout", type=int, default=10,
                        help="request timeout in seconds (default: 10)")
    parser.add_argument("--delay", type=float, default=0.0,
                        help="delay between requests in seconds (be polite)")
    parser.add_argument("-o", "--output", help="save plain email list to file")
    parser.add_argument("--json", dest="json_out",
                        help="save emails + source pages to a JSON file")
    parser.add_argument("-q", "--quiet", action="store_true",
                        help="suppress per-page progress output")
    parser.add_argument("--no-banner", action="store_true",
                        help="do not print the MELO banner")
    args = parser.parse_args()

    if not args.no_banner:
        print_banner()

    melo = Melo(
        depth=args.depth,
        timeout=args.timeout,
        delay=args.delay,
        max_pages=args.max_pages,
        verbose=not args.quiet,
    )

    try:
        emails = melo.run(args.urls)
    except KeyboardInterrupt:
        print(RED + "\nInterrupted. Reporting what was found so far..." + RESET)
        emails = melo.emails

    report(emails, txt_out=args.output, json_out=args.json_out)


if __name__ == "__main__":
    main()
