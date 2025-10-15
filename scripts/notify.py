
import os, json, urllib.request
HOOK = os.getenv("SLACK_WEBHOOK_URL", "")
if not HOOK:
  print("No SLACK_WEBHOOK_URL set; skipping notification.")
  raise SystemExit(0)

payload = {"text":"New competitor insights ingested. Visit GitHub Pages for details."}
req = urllib.request.Request(HOOK, data=json.dumps(payload).encode('utf-8'), headers={'Content-Type':'application/json'})
with urllib.request.urlopen(req) as resp:
  print("Slack notified:", resp.status)
