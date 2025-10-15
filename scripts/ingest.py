# scripts/ingest.py
import os, re, json, time, hashlib, feedparser, requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse
from datetime import datetime, timezone, timedelta

INSIGHTS_PATH = "public/data/insights.json"

# ---- Configuration ----
WINDOW_DAYS = 120  # look-back window
CUTOFF = datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS)

COMPETITOR_MAP = {
  "isnetworld": "ISNetworld", "isn": "ISNetworld",
  "avetta": "Avetta",
  "kpa flex": "KPA Flex", "kpa": "KPA Flex",
  "vendorpm": "VendorPM",
}

SOURCES = [
  # Business Wire (global feed). We'll filter by competitor keywords below.
  {"type":"rss","name":"Business Wire","url":"https://www.businesswire.com/portal/site/home/news/rss/"},
  # Add competitor-specific press/blog sources here. If they have sitemaps, list them:
  # {"type":"sitemap","name":"ISN Site", "url":"https://www.isnetworld.com/sitemap.xml", "match": r"/(news|press|blog)/"},
  # {"type":"sitemap","name":"Avetta", "url":"https://avetta.com/sitemap.xml", "match": r"/(news|press|blog|resources)/"},
]
# ------------------------

def canonical(u: str) -> str:
  u = (u or "").strip()
  if not u: return ""
  u = u.split("#")[0].rstrip("/")
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

def within_window(dt: datetime) -> bool:
  return dt >= CUTOFF

def parse_dt_guess(*candidates) -> datetime:
  for c in candidates:
    if not c: continue
    try:
      # feedparser provides *parsed tuples; turn them into aware datetimes
      if hasattr(c, "tm_year"):  # time.struct_time
        return datetime.fromtimestamp(time.mktime(c), tz=timezone.utc)
    except Exception:
      pass
  # fallback now
  return datetime.now(timezone.utc)

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

def load_existing(path):
  try:
    with open(path) as f:
      data = json.load(f)
      return {i["id"]: i for i in data}, data
  except Exception:
    return {}, []

# ---- Collectors ----
def collect_rss(src):
  d = feedparser.parse(src["url"])
  for e in d.entries:
    # Prefer the "alternate" link; fallback to e.link
    link = ""
    if getattr(e, "links", None):
      alt = [L.get("href") for L in e.links if L.get("rel") in (None, "alternate") and L.get("href")]
      if alt: link = alt[0]
    link = canonical(link or e.get("link",""))

    title = (e.get("title","") or "").strip()
    summary = (e.get("summary","") or "").strip()
    dt = parse_dt_guess(getattr(e, "published_parsed", None), getattr(e, "updated_parsed", None))
    if not within_window(dt): 
      continue

    # keep only entries that look related to our competitors or space
    comp = pick_competitor(f"{title} {summary}", link)
    if comp == "Unknown" and not any(kw in (title+summary).lower() for kw in ["contractor", "safety", "compliance", "supply chain", "prequalification", "risk"]):
      continue

    tags = classify_tags(title, summary, link)
    sev, score = severity_from(tags)
    yield {
      "id": to_id(link, title, dt.isoformat()),
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

def fetch(url, timeout=15):
  r = requests.get(url, headers={"User-Agent":"CI-App/1.0 (+github-actions)"}, timeout=timeout)
  r.raise_for_status()
  return r

def collect_sitemap(src):
  rx = re.compile(src.get("match", "."), re.I)
  try:
    soup = BeautifulSoup(fetch(src["url"]).text, "xml")
  except Exception:
    return
  urls = [loc.text.strip() for loc in soup.select("url > loc")]
  for loc in urls:
    if not rx.search(loc):
      continue
    try:
      html = fetch(loc).text
      dom = BeautifulSoup(html, "html.parser")
      title = (dom.title.get_text().strip() if dom.title else loc)
      # meta description, if present
      desc = ""
      md = dom.find("meta", {"name":"description"})
      if md and md.get("content"): desc = md["content"].strip()
      # common publish date hints
      meta_dt = dom.find("meta", {"property":"article:published_time"}) or dom.find("time")
      dt_str = (meta_dt.get("content") or meta_dt.get_text().strip()) if meta_dt else None
      dt = parse_dt_guess()  # default now
      try:
        if dt_str:
          # very light parser: keep UTC naive okay
          dt = datetime.fromisoformat(dt_str.replace("Z","+00:00"))
      except Exception:
        pass
      if not within_window(dt): 
        continue
      comp = pick_competitor(f"{title} {desc}", loc)
      tags = classify_tags(title, desc, loc)
      sev, score = severity_from(tags)
      yield {
        "id": to_id(loc, title, dt.isoformat()),
        "competitor": comp,
        "title": title,
        "summary": desc[:500],
        "sourceName": src["name"],
        "sourceUrl": canonical(loc),
        "date": dt.isoformat(),
        "tags": tags,
        "impact_score": round(score, 2),
        "severity": sev,
      }
    except Exception:
      continue

# ---- Orchestrate ----
if __name__ == "__main__":
  existing_map, existing_list = load_existing(INSIGHTS_PATH)
  seen_urls = {canonical(v.get("sourceUrl")) for v in existing_list}
  out = list(existing_list)

  for src in SOURCES:
    try:
      if src["type"] == "rss":
        for item in collect_rss(src):
          if item["id"] in existing_map or canonical(item["sourceUrl"]) in seen_urls: 
            continue
          out.append(item); seen_urls.add(canonical(item["sourceUrl"]))
      elif src["type"] == "sitemap":
        for item in collect_sitemap(src) or []:
          if item["id"] in existing_map or canonical(item["sourceUrl"]) in seen_urls: 
            continue
          out.append(item); seen_urls.add(canonical(item["sourceUrl"]))
    except Exception:
      # keep crawling other sources even if one fails
      continue

  # newest first, keep up to 1000
  out.sort(key=lambda x: x.get("date",""), reverse=True)
  with open(INSIGHTS_PATH, "w") as f:
    json.dump(out[:1000], f, indent=2)
  print(f"Wrote {len(out[:1000])} insights to {INSIGHTS_PATH}")


