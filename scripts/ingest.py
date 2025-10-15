# scripts/ingest.py
import json, re, time, hashlib, random, feedparser, requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin, quote
from datetime import datetime, timezone, timedelta
from http.client import RemoteDisconnected
from requests.exceptions import RequestException, ChunkedEncodingError, ConnectionError as ReqConnError

INSIGHTS_PATH = "public/data/insights.json"

# -------- Config --------
WINDOW_DAYS = 365
CUTOFF = datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS)

HTTP_TIMEOUT = 18
SLEEP_BETWEEN_REQUESTS = 0.4
MAX_RETRIES = 4
BACKOFF_BASE = 0.8

UA = "CI-App/1.0 (+github-actions; contact: ci-bot@noreply)"

COMPETITOR_MAP = {
  "isnetworld": "ISNetworld", "isn": "ISNetworld",
  "avetta": "Avetta",
  "kpa flex": "KPA Flex", "kpa": "KPA Flex", "kpa.io": "KPA Flex",
  "vendorpm": "VendorPM",
}

GOOGLE_NEWS_QUERIES = [
  "ISNetworld",
  "Avetta",
  "KPA Flex",
  "VendorPM",
  "contractor prequalification platform",
]

SOURCES = [
  # RSS
  {"type":"rss","name":"Business Wire","url":"https://www.businesswire.com/portal/site/home/news/rss/"},

  # ISN
  {"type":"listing","name":"ISN Blog",
   "url":"https://www.isnetworld.com/en/blog",
   "allow_path": r"^/en/blog",
   "article_path": r"^/en/blog/.+"
  },

  # KPA — Press only
  {"type":"listing","name":"KPA Press",
   "url":"https://kpa.io/press/",
   "allow_path": r"^/press",
   "article_path": r"^/press/.+"
  },

  # Avetta
  {"type":"listing","name":"Avetta News",
   "url":"https://www.avetta.com/resources/company-news",
   "allow_path": r"^/resources/company-news",
   "article_path": r"^/resources/company-news/.+"
  },

  # VendorPM — only News category
  {"type":"listing","name":"VendorPM Blog",
   "url":"https://www.vendorpm.com/blog",
   "allow_path": r"^/blog",
   "article_path": r"^/blog/.+",
   "require_news_category": True
  },
]
# ------------------------

# -------- HTTP helpers --------
def sleep_polite():
  time.sleep(SLEEP_BETWEEN_REQUESTS + random.random() * 0.2)

def fetch_text(url, expect_xml=False):
  """GET with retries/backoff. Returns response.text or None."""
  for attempt in range(1, MAX_RETRIES + 1):
    try:
      sleep_polite()
      r = requests.get(url, headers={"User-Agent": UA}, timeout=HTTP_TIMEOUT)
      r.raise_for_status()
      return r.text
    except (RemoteDisconnected, ChunkedEncodingError, ReqConnError, RequestException) as e:
      if attempt == MAX_RETRIES:
        print(f"[warn] fetch failed after retries: {url} :: {e}")
        return None
      time.sleep(BACKOFF_BASE * (2 ** (attempt - 1)))
  return None

# -------- Utils --------
def canonical(u: str) -> str:
  u = (u or "").strip()
  if not u: return ""
  u = u.replace("http://", "https://")
  u = u.split("#")[0].split("?")[0].rstrip("/")
  return u

def to_id(url, title, dt_iso):
  h = hashlib.sha1(f"{canonical(url)}|{title}|{dt_iso}".encode()).hexdigest()
  return h[:12]

def pick_competitor(text, url=""):
  low = f"{text or ''} {url or ''}".lower()
  for k, name in COMPETITOR_MAP.items():
    if k in low:
      return name
  return "Unknown"

def classify_tags(title, summary, url):
  low = f"{title} {summary} {url}".lower()
  tags = []
  if any(k in low for k in ["ai","genai","llm","assistant","chatbot"]): tags.append("AI")
  if any(k in low for k in ["price","pricing","bundle","license"]): tags.append("Pricing")
  if any(k in low for k in ["bid","tender","rfp","e-bidding","e-bidding"]): tags.append("E-bidding")
  if any(k in low for k in ["integration","api","webhook"]): tags.append("Integration")
  if any(k in low for k in ["analytics","dashboard","insight"]): tags.append("Analytics")
  if any(k in low for k in ["press","news","announce","launch","release"]): tags.append("Announcement")
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

def within_window(dt: datetime) -> bool:
  return dt >= CUTOFF

def parse_dt_guess(entry) -> datetime:
  for attr in ("published_parsed", "updated_parsed"):
    v = getattr(entry, attr, None)
    if v:
      return datetime.fromtimestamp(time.mktime(v), tz=timezone.utc)
  return datetime.now(timezone.utc)

def path_ok(path: str, rx: re.Pattern|None) -> bool:
  return bool(rx.search(path)) if rx else True

def looks_like_article(link: str, soup: BeautifulSoup) -> bool:
  og_type = soup.find("meta", {"property":"og:type"})
  if og_type and og_type.get("content","").lower() == "article":
    return True
  if soup.find("meta", {"property":"article:published_time"}) or soup.find("time"):
    return True
  path = urlparse(link).path.rstrip("/")
  if re.search(r"/\d{4}/\d{1,2}/\d{1,2}/", path):  # /YYYY/MM/DD/
    return True
  if re.search(r"/\d{4}/", path):                # /YYYY/
    return True
  slug = path.split("/")[-1]
  if "-" in slug and len(slug) >= 6:
    return True
  return False

def text_contains_news(s):
  return "news" in (s or "").strip().lower()

def vendorpm_is_news_article(soup: BeautifulSoup) -> bool:
  for sel in [".blog-category-label", ".blog-category", ".category", "[class*=category]"]:
    for el in soup.select(sel):
      if text_contains_news(el.get_text()):
        return True
  for css, attr in [
    ('meta[property="article:section"]', "content"),
    ('meta[name="section"]', "content"),
    ('meta[name="category"]', "content"),
    ('meta[property="article:tag"]', "content"),
  ]:
    el = soup.select_one(css)
    if el and text_contains_news(el.get(attr, "")):
      return True
  return False

# -------- Collectors --------
def collect_google_news():
  for q in GOOGLE_NEWS_QUERIES:
    url = f"https://news.google.com/rss/search?q={quote(q)}&hl=en-US&gl=US&ceid=US:en"
    xml = fetch_text(url, expect_xml=True)
    if not xml:
      print(f"[warn] google news fetch failed: {url}")
      continue
    d = feedparser.parse(xml)
    for e in d.entries:
      link = canonical(getattr(e, "link", "") or "")
      title = (e.get("title","") or "").strip()
      summary = (e.get("summary","") or "").strip()
      dt = parse_dt_guess(e)
      if not within_window(dt): continue
      comp = pick_competitor(f"{title} {summary}", link)
      tags = classify_tags(title, summary, link)
      sev, score = severity_from(tags)
      yield {
        "id": to_id(link, title or link, dt.isoformat()),
        "competitor": comp,
        "title": title or link,
        "summary": summary[:500],
        "sourceName": urlparse(link).netloc or "Google News",
        "sourceUrl": link,
        "date": dt.isoformat(),
        "tags": tags,
        "impact_score": round(score, 2),
        "severity": sev,
      }

def collect_rss(src):
  xml = fetch_text(src["url"], expect_xml=True)
  if not xml:
    print(f"[warn] rss fetch failed: {src['name']} :: {src['url']}")
    return
  d = feedparser.parse(xml)
  for e in d.entries:
    link = ""
    if getattr(e, "links", None):
      alts = [L.get("href") for L in e.links if L.get("href") and L.get("rel") in (None, "alternate")]
      if alts: link = alts[0]
    link = canonical(link or e.get("link",""))
    title = (e.get("title","") or "").strip()
    summary = (e.get("summary","") or "").strip()
    dt = parse_dt_guess(e)
    if not within_window(dt): continue
    comp = pick_competitor(f"{title} {summary}", link)
    tags = classify_tags(title, summary, link)
    sev, score = severity_from(tags)
    yield {
      "id": to_id(link, title or link, dt.isoformat()),
      "competitor": comp,
      "title": title or link,
      "summary": summary[:500],
      "sourceName": src["name"],
      "sourceUrl": link,
      "date": dt.isoformat(),
      "tags": tags,
      "impact_score": round(score, 2),
      "severity": sev,
    }

def collect_listing(src, max_links=40):
  html = fetch_text(src["url"])
  if not html:
    print(f"[warn] listing fetch failed: {src['name']} :: {src['url']}")
    return

  base = f'{urlparse(src["url"]).scheme}://{urlparse(src["url"]).netloc}'
  soup = BeautifulSoup(html, "html.parser")

  allow_rx = re.compile(src.get("allow_path", ""), re.I) if src.get("allow_path") else None
  article_rx = re.compile(src.get("article_path", ""), re.I) if src.get("article_path") else None
  listing_path = urlparse(src["url"]).path.rstrip("/")

  # 1) gather candidate links on the listing page
  candidates = []
  for a in soup.find_all("a", href=True):
    href = a.get("href")
    if href.startswith("/"):
      href = urljoin(base, href)
    if not href.startswith(base):
      continue

    path = urlparse(href).path.rstrip("/")
    if allow_rx and not path_ok(path, allow_rx):
      continue
    if path == listing_path:
      continue
    if article_rx and not path_ok(path, article_rx):
      continue

    candidates.append(canonical(href))

  # de-dupe & cap
  seen = set()
  links = []
  for h in candidates:
    if h not in seen:
      seen.add(h)
      links.append(h)
    if len(links) >= max_links:
      break

  # 2) fetch each article and keep only pages that look like an article
  for link in links:
    art_html = fetch_text(link)
    if not art_html:
      print(f"[warn] article fetch failed: {link}")
      continue

    art_soup = BeautifulSoup(art_html, "html.parser")
    if not looks_like_article(link, art_soup):
      continue

    if src.get("require_news_category"):
      netloc = urlparse(link).netloc
      if "vendorpm.com" in netloc and not vendorpm_is_news_article(art_soup):
        continue

    title = (art_soup.find("meta", {"property":"og:title"}) or {}).get("content") \
            or (art_soup.title.string if art_soup.title else "") \
            or link
    desc = (art_soup.find("meta", {"property":"og:description"}) or {}).get("content") \
           or (art_soup.find("meta", attrs={"name":"description"}) or {}).get("content") \
           or ""

    # date
    dt = None
    for sel, attr in (('meta[property="article:published_time"]',"content"),
                      ('meta[name="pubdate"]',"content"),
                      ('time[datetime]',"datetime")):
      el = art_soup.select_one(sel)
      if el and el.get(attr):
        v = el.get(attr)
        try:
          if v.endswith("Z"): v = v.replace("Z","+00:00")
          dt = datetime.fromisoformat(v)
          if not dt.tzinfo:
            dt = dt.replace(tzinfo=timezone.utc)
          break
        except Exception:
          pass
    if not dt:
      dt = datetime.now(timezone.utc)

    if not within_window(dt):
      continue

    comp = pick_competitor(f"{title} {desc}", link)
    tags = classify_tags(title, desc, link)
    sev, score = severity_from(tags)

    yield {
      "id": to_id(link, title[:300], dt.isoformat()),
      "competitor": comp,
      "title": title[:300],
      "summary": desc[:500],
      "sourceName": urlparse(link).netloc,
      "sourceUrl": canonical(link),
      "date": dt.isoformat(),
      "tags": tags,
      "impact_score": round(score, 2),
      "severity": sev,
    }

# -------- Orchestrate --------
def load_existing(path):
  try:
    with open(path) as f:
      data = json.load(f)
      return {i["id"]: i for i in data}, data
  except Exception:
    return {}, []

if __name__ == "__main__":
  existing_map, existing_list = load_existing(INSIGHTS_PATH)
  seen_urls = {canonical(v.get("sourceUrl")) for v in existing_list}
  out = list(existing_list)
  new_count = 0

  # Google News
  try:
    for item in collect_google_news():
      if item["id"] in existing_map or canonical(item["sourceUrl"]) in seen_urls:
        continue
      out.append(item); seen_urls.add(canonical(item["sourceUrl"])); new_count += 1
  except Exception as e:
    print(f"[warn] google news collector failed: {e}")

  # RSS (Business Wire)
  for src in [s for s in SOURCES if s["type"]=="rss"]:
    try:
      for item in collect_rss(src):
        if item["id"] in existing_map or canonical(item["sourceUrl"]) in seen_urls:
          continue
        out.append(item); seen_urls.add(canonical(item["sourceUrl"])); new_count += 1
    except Exception as e:
      print(f"[warn] rss collector failed: {src['name']} :: {e}")

  # Listing pages
  for src in [s for s in SOURCES if s["type"]=="listing"]:
    try:
      for item in collect_listing(src):
        if item["id"] in existing_map or canonical(item["sourceUrl"]) in seen_urls:
          continue
        out.append(item); seen_urls.add(canonical(item["sourceUrl"])); new_count += 1
    except Exception as e:
      print(f"[warn] listing collector failed: {src['name']} :: {e}")

  out.sort(key=lambda x: x.get("date",""), reverse=True)
  with open(INSIGHTS_PATH, "w") as f:
    json.dump(out[:1000], f, indent=2)

  print(f"New items added: {new_count}")
  print(f"Wrote {len(out[:1000])} insights to {INSIGHTS_PATH}")

