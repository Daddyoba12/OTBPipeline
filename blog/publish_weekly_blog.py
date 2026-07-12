"""
publish_weekly_blog.py
Thursday 8am — the single blog task.

Steps:
  1. generate_daily_blog.py   → picks topic, writes HTML to blog/pending/
  2. post_to_blogger.py       → posts pending HTML to Blogger (blog.com)
  3. Google sitemap ping       → tells Google to crawl the new post immediately

Run: python publish_weekly_blog.py
Schedule: BootHop-Blog — every Thursday 8am
"""

import sys, requests
from pathlib import Path
from datetime import datetime

BASE = Path(__file__).parent
LOG  = BASE / "blog_log.txt"

def log(msg):
    ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")

def ping_google(sitemap_url="https://www.boothop.com/sitemap.xml"):
    """Ping Google to crawl the updated sitemap immediately."""
    try:
        ping_url = f"https://www.google.com/ping?sitemap={sitemap_url}"
        r = requests.get(ping_url, timeout=15)
        if r.ok:
            log(f"  [Google] Sitemap pinged — Google will crawl shortly ({sitemap_url})")
        else:
            log(f"  [Google] Ping returned {r.status_code} — Google will crawl on its own schedule")
    except Exception as e:
        log(f"  [Google] Ping failed: {e} — not critical, Google will crawl naturally")

def main():
    log("=" * 55)
    log("BootHop Weekly Blog — Thursday publish run")

    # Step 1: Generate the blog post
    log("\n[1] Generating blog post...")
    try:
        sys.path.insert(0, str(BASE))
        import generate_daily_blog
        generate_daily_blog.main()
    except Exception as e:
        log(f"  ERROR generating blog: {e}")
        return

    # Step 2: Post to Blogger
    log("\n[2] Posting to Blogger...")
    try:
        import post_to_blogger
        post_to_blogger.main()
    except Exception as e:
        log(f"  ERROR posting to Blogger: {e}")
        return

    # Step 3: Ping Google
    log("\n[3] Pinging Google...")
    ping_google()

    log("\nBlog published successfully.")
    log("=" * 55)

if __name__ == "__main__":
    main()
