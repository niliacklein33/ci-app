
import hashlib, json, time, feedparser
from bs4 import BeautifulSoup  # reserved for HTML scrapes later
from urllib.parse import urlparse  # reserved
from datetime import datetime, timezone

INSIGHTS_PATH = "public/data/insights.json"

SOURCES = [
  {"type":"rss","name":"Business Wire","url":"https://www.businesswire.com/portal/site/home/news/rss/"},
]

def canonical(u): 
    return (u or "").split("?")[0].strip().rstrip("/")

def classify(text, url):
    tags = []
    comp_map = {"isn":"ISNetworld","isnetworld":"ISNetworld","avetta":"Avetta","kpa":"KPA Flex","vendorpm":"VendorPM"}
    lower = (text or "").lower() + " " + (url or "").lower()
    comp = next((v for k,v in comp_map.items() if k in lower), "Unknown")
    if any(k in lower for k in ["ai","genai","llm","assistant"]): tags.append("AI")
    if "price" in lower or "pricing" in lower: tags.append("Pricing")
    if "bid" in lower or "tender" in lower: tags.append("E-bidding")
    return comp, tags

def impact(tags): 
    s = 0.0
    if "AI" in tags: s += 0.2
    if "Pricing" in tags: s += 0.3
    if "E-bidding" in tags: s += 0.2
    return min(1.0, 0.5 + s) if s else 0.5

def to_id(url, title, dt):
    import hashlib
    h = hashlib.sha1(f"{canonical(url)}|{title}|{dt}".encode()).hexdigest()
    return h[:12]

def load_existing(path):
    try: 
        with open(path) as f:
            data = json.load(f)
            return {i["id"]: i for i in data}, data
    except Exception:
        return {}, []

def rss_items(src):
    d = feedparser.parse(src["url"])
    for e in d.entries:
        title = (e.get("title","") or "").strip()
        summary = (e.get("summary","") or "").strip()
        link = canonical(e.get("link",""))
        if getattr(e, "published_parsed", None):
            import time as _t
            dt_iso = datetime.fromtimestamp(_t.mktime(e.published_parsed), tz=timezone.utc).isoformat()
        else:
            dt_iso = datetime.now(timezone.utc).isoformat()
        comp, tags = classify(f"{title} {summary}", link)
        yield {
          "id": to_id(link, title, dt_iso or ""),
          "competitor": comp,
          "title": title,
          "summary": summary[:400],
          "sourceName": src["name"],
          "sourceUrl": link,
          "date": dt_iso,
          "tags": tags,
          "impact_score": impact(tags),
          "severity": "critical" if impact(tags) >= 0.9 else "watch" if impact(tags) >= 0.7 else "info"
        }

if __name__ == "__main__":
    existing_map, existing_list = load_existing(INSIGHTS_PATH)
    seen_urls = {canonical(v.get("sourceUrl")) for v in existing_list}
    out = list(existing_list)

    for src in SOURCES:
        if src["type"] == "rss":
            for item in rss_items(src):
                if canonical(item["sourceUrl"]) in seen_urls or item["id"] in existing_map:
                    continue
                out.append(item)
                seen_urls.add(canonical(item["sourceUrl"]))

    out.sort(key=lambda x: x.get("date",""), reverse=True)
    with open(INSIGHTS_PATH, "w") as f:
        json.dump(out[:1000], f, indent=2)
    print(f"Wrote {len(out[:1000])} insights to {INSIGHTS_PATH}")
