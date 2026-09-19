#!/usr/bin/env python3
"""One command for a skill-store reference audit.

Deterministic first: census, Windows paths, present-assertions, resolution. Jev only on
what a script cannot settle, one request per reference, count announced before spending.
"""
import argparse, json, os, sys, time, urllib.request, urllib.error
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "tools"))
from skill_refs import collect, deterministic_findings  # noqa: E402

PACK = json.load(open(os.path.join(HERE, "packs", "skill-store-stale-ref.json")))
ENDPOINT = os.environ.get("TYPESAFE_BASE_URL", "https://api.typesafe.ai") + "/v1/systemone"
GATE = PACK["thresholds"]["is_stale"]["gate"]

def api_key():
    import re
    k = os.environ.get("TYPESAFE_API_KEY")
    if k:
        return k
    path = os.path.expanduser("~/.config/typesafe/env.sh")
    m = re.search(r'^\s*export\s+TYPESAFE_API_KEY=["\']?([^"\'\s]+)', open(path).read(), re.M)
    if not m:
        sys.exit(f"TYPESAFE_API_KEY unset and no export line in {path}")
    return m.group(1)

def judge(key, r):
    target = os.path.expanduser(r["ref"])
    parent = os.path.dirname(target)
    state = {"skill_file": r["file"], "reference_text": r["text"], "reference_kind": "path",
             "target_exists": False,
             "target_excerpt": f'{r["ref"]} does not exist. Its parent {parent} '
                               + ("exists." if os.path.isdir(parent) else "does not exist either."),
             "file_declares_archived": r["file_declares_archived"],
             "surrounding_text_says_absent": r["surrounding_text_says_absent"],
             "inside_code_block": r["inside_code_block"],
             "line_asserts_current_state": r["text"].lstrip("> ").lower().startswith(
                 ("present", "installed", "lives at", "available")) or " is archived at " in r["text"]}
    body = json.dumps({"state": state, "model": "jev-latest", "questions": PACK["questions"]}).encode()
    req = urllib.request.Request(ENDPOINT, data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return {**r, "answers": json.load(resp)}
        except urllib.error.HTTPError as e:
            if e.code in (429, 529) and attempt < 2:
                time.sleep(1.5 * (attempt + 1)); continue
            return {**r, "error": f"HTTP {e.code}"}
        except Exception as e:
            if attempt < 2:
                time.sleep(1.5); continue
            return {**r, "error": str(e)}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("store", nargs="?", default=os.path.expanduser("~/.claude/skills"))
    ap.add_argument("--run", action="store_true", help="spend requests; without it, only the plan is printed")
    ap.add_argument("--json", help="write the scored results here")
    args = ap.parse_args()

    refs = collect(args.store)
    paths = [r for r in refs if r["kind"] == "path"]
    counts = Counter(r["status"] for r in paths)
    print(f"store            : {args.store}")
    print(f"files with refs  : {len({r['file'] for r in refs})}")
    print(f"path references  : {len(paths)}  {dict(counts)}")
    print(f"url references   : {len({r['ref'] for r in refs if r['kind'] == 'url'})} unique (not judged here)")

    wrong_present = deterministic_findings(refs, args.store)
    windows = [r for r in paths if r["status"] == "windows-path"]
    print(f"\ndeterministic findings, no spend:")
    print(f"  asserted present but absent : {len(wrong_present)}")
    for r in wrong_present:
        print(f"      {r['file']}:{r['line']}  {r['ref']}")
    print(f"  windows paths (previous host): {len(windows)} in {len({r['file'] for r in windows})} files")

    missing = [r for r in paths if r["status"] == "missing"]
    seen, todo = set(), []
    for r in missing:
        k = (r["file"], r["ref"])
        if k not in seen:
            seen.add(k); todo.append(r)
    print(f"\nneeds judgment   : {len(todo)} references = {len(todo)} requests"
          f"  (gate {GATE}, calibrated 2026-09-19, 15 percent disagreement)")
    if not args.run:
        print("\nre-run with --run to spend those requests.")
        return

    key = api_key()
    with ThreadPoolExecutor(max_workers=6) as ex:
        out = list(ex.map(lambda r: judge(key, r), todo))
    ok = [o for o in out if "answers" in o]
    for o in ok:
        a = o["answers"]["answers"]
        o["stale"] = a["is_stale"]["noul"]; o["load"] = a["load_bearing"]["noul"]
        o["risk"] = a["risk_if_wrong"]["score"]; o["route"] = a["route"]["choice"]
    flagged = sorted([o for o in ok if o["stale"] >= GATE], key=lambda o: -o["risk"])
    tin = sum(o["answers"]["usage"]["input_tokens"] for o in ok)
    tout = sum(o["answers"]["usage"]["output_tokens"] for o in ok)
    print(f"\n{len(ok)}/{len(out)} answered, usage {tin} in / {tout} out")
    print(f"flagged at {GATE}: {len(flagged)}")
    for o in flagged:
        print(f"  risk {o['risk']:.2f} stale {o['stale']:.2f} {o['route']:11s} {o['file']}:{o['line']}  {o['ref']}")
    if args.json:
        json.dump([{k: v for k, v in o.items() if k != "answers"} for o in ok], open(args.json, "w"), indent=1)

if __name__ == "__main__":
    main()
