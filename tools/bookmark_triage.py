#!/usr/bin/env python3
"""Route saved posts, so a week of bookmarks becomes a short list worth opening.

Input is a JSON array of posts; the browser step is deliberately NOT automated,
because the signed-in session lives in a real Chrome profile and an unattended
scrape of a logged-in account is not something a tool should do by itself. Export
the week with the reader of your choice, or paste the array in.

Each post: {"author", "text", "posted_at", "links": [...], "engagement": "..."}

Measured 2026-09-19 on 22 real saved posts labelled by hand: the pack's `route`
answer beats its `durable_technique` score on this corpus - route caught 4 of the
5 posts carrying no technique and wrongly dropped 1 of 17 keepers, while the score
overlapped badly (durable 0.11-0.91 against 0.05-0.31). This tool therefore acts on
route and prints the score only as context.
"""
import argparse, sys, json, os, re, sys, time, urllib.request, urllib.error
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from spend_log import record as _record_spend

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACK = json.load(open(os.path.join(HERE, "packs", "bookmark-triage.json")))
ENDPOINT = os.environ.get("TYPESAFE_BASE_URL", "https://api.typesafe.ai") + "/v1/systemone"
ORDER = ["skill_intake", "vault_note", "read_later", "drop"]

def api_key():
    k = os.environ.get("TYPESAFE_API_KEY")
    if k:
        return k
    path = os.path.expanduser("~/.config/typesafe/env.sh")
    if not os.path.exists(path):
        sys.exit(f"TYPESAFE_API_KEY is unset and {path} does not exist.")
    m = re.search(r'^\s*export\s+TYPESAFE_API_KEY=["\']?([^"\'\s]+)', open(path).read(), re.M)
    if not m:
        sys.exit(f"No TYPESAFE_API_KEY export line in {path}.")
    return m.group(1)

def judge(key, post):
    state = {"author": post.get("author", ""), "text": post.get("text", "")[:4000],
             "links": post.get("links", []), "posted_at": post.get("posted_at", ""),
             "engagement": post.get("engagement", "not captured")}
    body = json.dumps({"state": state, "model": "jev-latest", "questions": PACK["questions"]}).encode()
    req = urllib.request.Request(ENDPOINT, data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                _payload = json.load(r)
                _record_spend("bookmark_triage", _payload.get("model"), len(PACK["questions"]), _payload.get("usage"))
                return _payload
        except urllib.error.HTTPError as e:
            if e.code in (429, 529) and attempt < 2:
                time.sleep(1.5 * (attempt + 1)); continue
            return {"error": f"HTTP {e.code}"}
        except Exception as e:
            if attempt < 2:
                time.sleep(1.5); continue
            return {"error": type(e).__name__}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file", help="JSON array of posts; - reads stdin")
    ap.add_argument("--run", action="store_true", help="spend the requests; without it only the plan is printed")
    ap.add_argument("--json", help="write the routed posts here")
    args = ap.parse_args()

    posts = json.load(sys.stdin if args.file == "-" else open(args.file))
    if not isinstance(posts, list) or not posts:
        sys.exit("expected a non-empty JSON array of posts")
    truncated = sum(1 for p in posts if "Show more" in p.get("text", ""))
    print(f"{len(posts)} post(s) = {len(posts)} request(s)")
    if truncated:
        print(f"WARNING: {truncated} post(s) look truncated ('Show more'). The judgement will be about the preview.")
    if not args.run:
        print("re-run with --run to spend those requests.")
        return 0

    key = api_key()
    with ThreadPoolExecutor(max_workers=6) as ex:
        answers = list(ex.map(lambda p: judge(key, p), posts))

    rows, failed, tin, tout = [], 0, 0, 0
    for post, ans in zip(posts, answers):
        if "error" in ans:
            failed += 1; continue
        a = ans["answers"]
        tin += ans["usage"]["input_tokens"]; tout += ans["usage"]["output_tokens"]
        probs = sorted(a["route"]["probabilities"].values(), reverse=True)
        rows.append({"author": post.get("author", ""), "route": a["route"]["choice"],
                     "tie": probs[0] < 0.5 or (probs[0] - probs[1]) < 0.10,
                     "durable": a["durable_technique"]["noul"], "depth": a["depth"]["score"],
                     "text": post.get("text", "")[:140]})

    for route in ORDER:
        group = [r for r in rows if r["route"] == route]
        if not group:
            continue
        print(f"\n{route} ({len(group)})")
        for r in sorted(group, key=lambda r: -r["depth"]):
            print(f"  {'TIE ' if r['tie'] else '    '}depth {r['depth']:.2f}  {r['author']}: {r['text'][:90]}")
    ties = sum(1 for r in rows if r["tie"])
    print(f"\n{len(rows)} routed, {ties} tie(s) for a human, {failed} call(s) failed. usage {tin} in / {tout} out.")
    print(f"route counts: {dict(Counter(r['route'] for r in rows))}")
    if args.json:
        json.dump(rows, open(args.json, "w"), indent=1)
    return 0

if __name__ == "__main__":
    sys.exit(main())
