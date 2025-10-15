# scripts/ingest.py
import os, re, json, time, hashlib, feedparser, requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin
from datetime import datetime, timezone
from dateutil import parser as dateparse

INSIGHTS_PATH = "public/data/insights.json"

# ---------------- Config ----------------
COMPETITOR_MAP = {
  "isnetworld": "ISNetworld", "isn": "ISNetworld",
  "avetta": "Avetta",
  "kpa": "KPA Flex", "kpa flex": "KPA Flex",
  "vendorpm": "VendorPM",
}
COMPETITOR_KEYWORDS = list(COMPETITOR_MAP.keys())

SOURCES = [
  # RSS (easy wins)
  {"type": "rss", "name": "Business Wire", "url": "https://www.businesswire.com/portal/site/home/news/rss/"},
  # Competitor blogs/press pages (no RSS → sitemap or HTML)
  {"type": "sitemap", "name": "ISN Newsroom", "url": "https://www.isnetworld.com/sitemap.xml", "match": r"/(news|press|blog)/"},
  {"type": "sitemap", "name": "Avetta", "url": "https://avetta.com/sitemap.xml", "match": r"/(news|press|resources|blog)/"},
  # Add more sitemaps/HTML pages here
]

# Web search (optional). Set SERPAPI_KEY or BING_KEY as a secret in GitHub.
ENABLE_SEARCH = True
SEARCH_QUERIES = [
  "ISNetworld news",
  "Avetta press release",
  "KPA Flex announcement",
  "VendorPM news",
  "contractor management platform pricing",
]
MAX_SEARCH_RESULTS = 8  # per query
# ---------------------------------------


def canonical(u): 
    u = (u or "").strip()
    if not u: return ""
    u = u.split("#")[0].split("?")[0].rstrip("/")
    return u

def to_id(url, title, dt):
    h = hashlib.sha1(f"{canonical(url)}|{title}|{dt}".encode()).hexdigest()
    return h[:12]

def pick_competitor(text, url=""):
    low = f"{text or ''} {url or ''}".lower()
    for k, name in COMPETITOR_MAP.items():
        if k in low:
            return name
    return "Unknown"

def extract_date(text, fallback=None):
    # Try parse any date-like string; fallback to now (UTC)
    if not text:
        return fallback or datetime.now(timezone.utc).isoformat()
    try:
        d = dateparse.parse(text, fuzzy=True)
        if not d.tzinfo: d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc).isoformat()
    except Exception:
        return fallback or datetime.now(timezone.utc).isoformat()

def classify_tags(title, summary, url):
    low = f"{title} {summary} {url}".lower()
    tags = []
    if any(k in low for k in ["ai","genai","llm","assistant","chatbot"]): tags.append("AI")
    if any(k in low for k in ["price","pricing","bundle","license"]): tags.append("Pricing")
    if any(k in low for k in ["bid","tender","rfp","e-bidding","e-bidding"]): tags.append("E-bidding")
    if any(k in low for k in ["integration","api","webhook"]): tags.append("Integration")
    if any(k in low for k in ["analytics","dashboard","insight"]): tags.append("Analytics")
    return tags

def severity_from(tags):
    s = 0.0
    if "Pricing" in tags: s += 0.35
    if "AI" in tags: s += 0.25
    if "E-bidding" in tags: s += 0.2
    if "Integration" in tags: s += 0.1
    if "Analytics" in tags: s += 0.05
    level = "info"
    if s >= 0.75: level = "critical"
    elif s >= 0.45: level = "watch"
    return level, min(1.0, 0.5 + s)

# ---------- Collectors ----------
def collect_rss(src):
    d = feedparser.parse(src["url"])
    for e in d.entries:
        title = (e.get("title","") or "").strip()
        summary = (e.get("summary","") or "").strip()
        link = canonical(e.get("link",""))
        dt = None
        if getattr(e, "published", None): dt = e.published
        elif getattr(e, "updated", None): dt = e.updated
        dt_iso = extract_date(dt)
        comp = pick_competitor(f"{title} {summary}", link)
        tags = classify_tags(title, summary, link)
        sev, score = severity_from(tags)
        yield {
            "id": to_id(link, title, dt_iso),
            "competitor": comp,
            "title": title,
            "summary": summary[:500],
            "sourceName": src["name"],
            "sourceUrl": link,
            "date": dt_iso,
            "tags": tags,
            "impact_score": round(score, 2),
            "severity": sev,
        }

def fetch(url, timeout=12):
    ua = "CI-App/1.0 (+github-actions)"
    r = requests.get(url, headers={"User-Agent": ua}, timeout=timeout)
    r.raise_for_status()
    return r

def collect_sitemap(src):
    # Parse <loc> URLs and filter by regex if provided
    rx = re.compile(src.get("match", "."), re.I)
    try:
        r = fetch(src["url"])
        soup = BeautifulSoup(r.text, "xml")
        urls = [loc.text.strip() for loc in soup.select("url > loc")]
        for loc in urls:
            if not rx.search(loc): 
                continue
            try:
                article = fetch(loc)
                art_soup = BeautifulSoup(article.text, "html.parser")
                title = (art_soup.find("title").get_text() if art_soup.title else loc).strip()
                # Try meta description
                desc = ""
                md = art_soup.find("meta", {"name":"description"})
                if md and md.get("content"): desc = md["content"].strip()
                date_meta = art_soup.find("meta", {"property":"article:published_time"}) or art_soup.find("time")
                dt_text = date_meta.get("content") if date_meta and date_meta.get("content") else (date_meta.get_text().strip() if date_meta else "")
                dt_iso = extract_date(dt_text)
                comp = pick_competitor(f"{title} {desc}", loc)
                tags = classify_tags(title, desc, loc)
                sev, score = severity_from(tags)
                yield {
                    "id": to_id(loc, title, dt_iso),
                    "competitor": comp,
                    "title": title,
                    "summary": (desc or "")[:500],
                    "sourceName": src["name"],
                    "sourceUrl": canonical(loc),
                    "date": dt_iso,
                    "tags": tags,
                    "impact_score": round(score, 2),
                    "severity": sev,
                }
            except Exception:
                continue
    except Exception:
        return

def collect_search():
    # Use SERP API (preferred) or Bing Web Search if keys provided
    out = []
    serp_key = os.getenv("SERPAPI_KEY", "")
    bing_key = os.getenv("BING_KEY", "")

    def push(item):
        out.append(item)

    def do_serp(query):
        url = "https://serpapi.com/search.json"
        params = {"engine":"google", "q":query, "num": MAX_SEARCH_RESULTS, "api_key": serp_key}
        r = requests.get(url, params=params, timeout=18); r.raise_for_status()
        data = r.json()
        for res in (data.get("organic_results") or [])[:MAX_SEARCH_RESULTS]:
            link = canonical(res.get("link",""))
            title = res.get("title","").strip()
            snippet = (res.get("snippet","") or "").strip()
            date_str = res.get("date") or ""
            dt_iso = extract_date(date_str)
            comp = pick_competitor(f"{title} {snippet}", link)
            tags = classify_tags(title, snippet, link)
            sev, score = severity_from(tags)
            push({
              "id": to_id(link, title, dt_iso),
              "competitor": comp,
              "title": title or link,
              "summary": snippet[:500],
              "sourceName": urlparse(link).netloc or "web",
              "sourceUrl": link,
              "date": dt_iso,
              "tags": tags,
              "impact_score": round(score, 2),
              "severity": sev,
            })

    def do_bing(query):
        endpoint = "https://api.bing.microsoft.com/v7.0/search"
        headers = {"Ocp-Apim-Subscription-Key": bing_key}
        params = {"q": query, "count": MAX_SEARCH_RESULTS, "freshness": "Month", "textDecorations": False, "textFormat": "Raw"}
        r = requests.get(endpoint, headers=headers, params=params, timeout=18); r.raise_for_status()
        webp = (r.json().get("webPages") or {}).get("value") or []
        for res in webp[:MAX_SEARCH_RESULTS]:
            link = canonical(res.get("url",""))
            title = (res.get("name","") or "").strip()
            snippet = (res.get("snippet","") or "").strip()
            dt_iso = extract_date(res.get("dateLastCrawled",""))
            comp = pick_competitor(f"{title} {snippet}", link)
            tags = classify_tags(title, snippet, link)
            sev, score = severity_from(tags)
            push({
              "id": to_id(link, title, dt_iso),
              "competitor": comp,
              "title": title or link,
              "summary": snippet[:500],
              "sourceName": urlparse(link).netloc or "web",
              "sourceUrl": link,
              "date": dt_iso,
              "tags": tags,
              "impact_score": round(score, 2),
              "severity": sev,
            })

    if not ENABLE_SEARCH: 
        return out
    for q in SEARCH_QUERIES:
        try:
            if serp_key:
                do_serp(q)
            elif bing_key:
                do_bing(q)
        except Exception:
            continue
    return out

# ------------- Orchestrate -------------
def load_existing(path):
    try:
        with open(path) as f:
            data = json.load(f)
            return {i["id"]: i for i in data}, data
    except Exception:
        return {}, []

def main():
    existing_map, existing_list = load_existing(INSIGHTS_PATH)
    seen_urls = {canonical(v.get("sourceUrl")) for v in existing_list}
    out = list(existing_list)

    # RSS
    for src in [s for s in SOURCES if s["type"]=="rss"]:
        for item in collect_rss(src):
            if item["id"] in existing_map or canonical(item["sourceUrl"]) in seen_urls: 
                continue
            out.append(item); seen_urls.add(canonical(item["sourceUrl"]))

    # Sitemap/HTML
    for src in [s for s in SOURCES if s["type"]=="sitemap"]:
        for item in collect_sitemap(src) or []:
            if item["id"] in existing_map or canonical(item["sourceUrl"]) in seen_urls: 
                continue
            out.append(item); seen_urls.add(canonical(item["sourceUrl"]))

    # Web search
    for item in collect_search():
        if item["id"] in existing_map or canonical(item["sourceUrl"]) in seen_urls:
            continue
        out.append(item); seen_urls.add(canonical(item["sourceUrl"]))

    out.sort(key=lambda x: x.get("date",""), reverse=True)
    with open(INSIGHTS_PATH, "w") as f:
        json.dump(out[:1000], f, indent=2)
    print(f"Wrote {len(out[:1000])} insights to {INSIGHTS_PATH}")

if __name__ == "__main__":
    main()

