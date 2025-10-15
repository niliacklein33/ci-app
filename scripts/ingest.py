# scripts/ingest.py
import os, re, json, time, hashlib, feedparser, requests, random
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin, quote
from datetime import datetime, timezone, timedelta
from http.client import RemoteDisconnected
from requests.exceptions import RequestException, ChunkedEncodingError, ConnectionError as ReqConnError

INSIGHTS_PATH = "public/data/insights.json"

# ---- Config ----
WINDOW_DAYS = 365
CUTOFF = datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS)

HTTP_TIMEOUT = 18
SLEEP_BETWEEN_REQUESTS = 0.4      # politeness delay
MAX_RETRIES = 4
BACKOFF_BASE = 0.8                 # seconds, exponential backoff

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
  # Listing pages
  {"type":"listing","name":"ISN Blog","url":"https://www.isnetworld.com/en/blog", "allow_path": r"/en/blog"},
  {"type":"listing","name":"KPA Press","url":"https://kpa.io/press/","allow_path": r"/press"},
  {"type":"listing","name":"KPA Resources","url":"https://kpa.io/workplace-compliance-news-resources/","allow_path": r"/workplace-compliance-news-resources"},
  {"type":"listing","name":"Avetta News","url":"https://www.avetta.com/resources/company-news","allow_path": r"/resources/company-news"},
  {"type":"listing","name":"VendorPM Blog","url":"https://www.vendorpm.com/blog","allow_path": r"/blog"},
]

# ---- HTTP helpers ----
UA = "CI-App/1.0 (+github-actions; contact: ci-bot@noreply)"

def sleep_polite():
  time.sleep(SLEEP_BETWEEN_REQUESTS + random.random() * 0.2)

def fetch_text(url, expect_xml=False):
  """GET with retries, exponential backoff, custom UA. Returns response.text or None."""
  for attempt in range(1, MAX_RETRIES + 1):
    try:
      sleep_polite()
      r = requests.get(url, headers={"User-Agent": UA}, timeout=HTTP_TIMEOUT)
      r.raise_for_status()
      # Some hosts close abruptly on first attempt; verify minimal content
      if expect_xml and "<rss" not in r.text[:2000] and "<feed" not in r.text[:2000]:
        # Not strictly required, but helps detect gate pages
        pass
      return r.text
    except (RemoteDisconnected, ChunkedEncodingError, ReqConnError, RequestException) as e:
      if attempt == MAX_RETRIES:
        print(f"[warn] fetch failed after retries: {url} :: {e}")
        return None
      backoff = BACKOFF_BASE * (2 ** (attempt - 1))
      time.sleep(backoff)
  return None

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

def extract_article_meta(html):
  soup = BeautifulSoup(html, "html.parser")
  title = (soup.find("meta", property="og:title") or {}).get("content") or (soup.title.string if soup.title else "") or ""
  desc = (soup.find("meta", property="og:description") or {}).get("content") or (soup.find("meta", attrs={"name":"description"}) or {}).get("content") or ""
  dt = None
  for sel, attr in (('meta[property="article:published_time"]',"content"),
                    ('meta[name="pubdate"]',"content"),
                    ('time[datetime]',"datetime")):
    el = soup.select_one(sel)
    if el and el.get(attr):
      v = el.get(attr)
      try:
        if v.endswith("Z"): v = v.replace("Z","+00:00")
        dt = datetime.fromisoformat(v)
        if not dt.tzinfo: dt = dt.replace(tzinfo=timezone.utc)
        break
      except Exception:
        pass
  if not dt:
    dt = datetime.now(timezone.utc)
  return title.strip(), desc.strip(), dt

# ---- Collectors ----
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
        "id": to_id(link, title, dt.isoformat()),
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

def collect_listing(src, max_links=35):
  html = fetch_text(src["url"])
  if not html:
    print(f"[warn] listing fetch failed: {src['name']} :: {src['url']}")
    return
  base = f'{urlparse(src["url"]).scheme}://{urlparse(src["url"]).netloc}'
  soup = BeautifulSoup(html, "html.parser")
  allow_rx = re.compile(src.get("allow_path", ""), re.I) if src.get("allow_path") else None

  # Collect candidate links
  candidates = []
  for a in soup.find_all("a", href=True):
    href = a.get("href")
    if href.startswith("/"): href = urljoin(base, href)
    if not href.startswith(base): continue
    path = urlparse(href).path
    if allow_rx and not allow_rx.search(path): continue
    candidates.append(canonical(href))

  # Dedup & cap
  seen = set()
  links = []
  for h in candidates:
    if h not in seen:
      seen.add(h)
      links.append(h)
    if len(links) >= max_links: break

  for link in links:
    art = fetch_text(link)
    if not art:
      print(f"[warn] article fetch failed: {link}")
      continue
    title, desc, dt = extract_article_meta(art)
    if not within_window(dt): continue
    comp = pick_competitor(f"{title} {desc}", link)
    tags = classify_tags(title, desc, link)
    sev, score = severity_from(tags)
    yield {
      "id": to_id(link, title or link, dt.isoformat()),
      "competitor": comp,
      "title": (title or link)[:300],
      "summary": (desc or "")[:500],
      "sourceName": urlparse(link).netloc,
      "sourceUrl": canonical(link),
      "date": dt.isoformat(),
      "tags": tags,
      "impact_score": round(score, 2),
      "severity": sev,
    }

# ---- Orchestrate ----
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
      if item["id"] in existing_map or canonical(item["sourceUrl"]) in seen_urls: continue
      out.append(item); seen_urls.add(canonical(item["sourceUrl"])); new_count += 1
  except Exception as e:
    print(f"[warn] google news collector failed: {e}")

  # RSS (Business Wire)
  for src in [s for s in SOURCES if s["type"]=="rss"]:
    try:
      for item in collect_rss(src):
        if item["id"] in existing_map or canonical(item["sourceUrl"]) in seen_urls: continue
        out.append(item); seen_urls.add(canonical(item["sourceUrl"])); new_count += 1
    except Exception as e:
      print(f"[warn] rss collector failed: {src['name']} :: {e}")

  # Listing pages
  for src in [s for s in SOURCES if s["type"]=="listing"]:
    try:
      for item in collect_listing(src):
        if item["id"] in existing_map or canonical(item["sourceUrl"]) in seen_urls: continue
        out.append(item); seen_urls.add(canonical(item["sourceUrl"])); new_count += 1
    except Exception as e:
      print(f"[warn] listing collector failed: {src['name']} :: {e}")

  out.sort(key=lambda x: x.get("date",""), reverse=True)
  with open(INSIGHTS_PATH, "w") as f:
    json.dump(out[:1000], f, indent=2)

  print(f"New items added: {new_count}")
  print(f"Wrote {len(out[:1000])} insights to {INSIGHTS_PATH}")

