# scripts/ingest.py
import json, re, time, hashlib, random, feedparser, requests
from urllib.parse import urlparse, quote
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup
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
  "kpa flex": "KPA Flex", "kpa": "KPA Flex",
  "vendorpm": "VendorPM",
}

GOOGLE_NEWS_QUERIES = [
  "ISNetworld",
  "Avetta",
  "KPA Flex",
  "VendorPM",
  "contractor prequalification platform",
  "supplier compliance platform",
]

RSS_SOURCES = [
  {"name":"Business Wire","url":"https://www.businesswire.com/portal/site/home/news/rss/"},
]

# -------- HTTP helpers --------
def sleep_polite():
  time.sleep(SLEEP_BETWEEN_REQUESTS + random.random() * 0.2)

def fetch_text(url):
  for attempt in range(1, MAX_RETRIES + 1):
    try:
      sleep_polite()
      r = requests.get(url, headers={"User-Agent": UA}, timeout=HTTP_TIMEOUT)
      r.raise_for_status()
      return r.text
    except (RemoteDisconnected, ChunkedEncodingError, ReqConnError, RequestException) as e:
      if attempt == MAX_RETRIES:
        print(f"[warn] fetch failed: {url} :: {e}")
        return None
      time.sleep(BACKOFF_BASE * (2 ** (attempt - 1)))
  return None

# -------- Utils --------
def canonical(u: str) -> str:
  if not u: return ""
  u = u.strip().replace("http://", "https://")
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
  if any(k in low for k in ["rfp","tender","bid","e-bidding","procurement"]): tags.append("E-bidding")
  if any(k in low for k in ["integration","api","webhook"]): tags.append("Integration")
  if any(k in low for k in ["analytics","dashboard","insight"]): tags.append("Analytics")
  if any(k in low for k in ["press","announce","launch","release"]): tags.append("Announcement")
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

def parse_dt_feed(entry) -> datetime:
  for attr in ("published_parsed", "updated_parsed"):
    v = getattr(entry, attr, None)
    if v:
      return datetime.fromtimestamp(time.mktime(v), tz=timezone.utc)
  return datetime.now(timezone.utc)

def looks_like_article_by_head(link: str, html: str) -> bool:
  # Quick content-based gate to avoid hub pages when discovered via Google News
  soup = BeautifulSoup(html or "", "html.parser")
  if soup.find("meta", {"property":"article:published_time"}) or soup.find("time", attrs={"datetime": True}):
    return True
  og_type = soup.find("meta", {"property":"og:type"})
  if og_type and og_type.get("content","").strip().lower() == "article":
    return True
  # JSON-LD Article / NewsArticle / BlogPosting
  for s in soup.find_all("script", attrs={"type":"application/ld+json"}):
    try:
      data = json.loads(s.string or "")
      items = data if isinstance(data, list) else [data]
      for it in items:
        t = it.get("@type")
        if isinstance(t, list): t = " ".join([str(x).lower() for x in t])
        t = (t or "").lower()
        if "article" in t or "newsarticle" in t or "blogposting" in t:
          return True
    except Exception:
      continue
  # URL hint: /YYYY/ or /YYYY/MM/… slug
  path = urlparse(link).path.lower()
  if re.search(r"/\d{4}/", path): return True
  if len(path.split("/")) >= 3 and "-" in path.split("/")[-1]: return True
  return False

# -------- Collectors (Google News + Business Wire) --------
def collect_google_news():
  for q in GOOGLE_NEWS_QUERIES:
    url = f"https://news.google.com/rss/search?q={quote(q)}&hl=en-US&gl=US&ceid=US:en"
    xml = fetch_text(url)
    if not xml:
      print(f"[warn] google news fetch failed: {url}")
      continue
    d = feedparser.parse(xml)
    for e in d.entries:
      link = canonical(getattr(e, "link", "") or "")
      title = (e.get("title","") or "").strip()
      summary = (e.get("summary","") or "").strip()
      dt = parse_dt_feed(e)
      if not within_window(dt): continue

      # Fetch the page quickly to ensure it looks like an article (avoid hubs)
      html = fetch_text(link) or ""
      if not looks_like_article_by_head(link, html):
        continue

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

def collect_businesswire():
  for src in RSS_SOURCES:
    xml = fetch_text(src["url"])
    if not xml:
      print(f"[warn] rss fetch failed: {src['name']} :: {src['url']}")
      continue
    d = feedparser.parse(xml)
    for e in d.entries:
      # prefer alternate link if present
      link = ""
      if getattr(e, "links", None):
        alts = [L.get("href") for L in e.links if L.get("href") and L.get("rel") in (None, "alternate")]
        if alts: link = alts[0]
      link = canonical(link or e.get("link",""))
      title = (e.get("title","") or "").strip()
      summary = (e.get("summary","") or "").strip()
      dt = parse_dt_feed(e)
      if not within_window(dt): continue
      # Business Wire items are individual releases; no extra hub check needed.

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
      if item["id"] in existing_map or canonical(item["sourceUrl"]) in seen_urls: continue
      out.append(item); seen_urls.add(canonical(item["sourceUrl"])); new_count += 1
  except Exception as e:
    print(f"[warn] google news collector failed: {e}")

  # Business Wire
  try:
    for item in collect_businesswire():
      if item["id"] in existing_map or canonical(item["sourceUrl"]) in seen_urls: continue
      out.append(item); seen_urls.add(canonical(item["sourceUrl"])); new_count += 1
  except Exception as e:
    print(f"[warn] businesswire collector failed: {e}")

  out.sort(key=lambda x: x.get("date",""), reverse=True)
  with open(INSIGHTS_PATH, "w") as f:
    json.dump(out[:1000], f, indent=2)

  print(f"New items added: {new_count}")
  print(f"Wrote {len(out[:1000])} insights to {INSIGHTS_PATH}")
