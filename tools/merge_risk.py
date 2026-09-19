#!/usr/bin/env python3
"""Rank the files in a change by how much a human should read before it lands.

Advisory only. It never blocks anything: a judgment ranks, a test gates. Every failure
path — no key, no network, a timeout, a bad response — exits 0 and says why.
"""
import argparse, json, os, re, subprocess, sys, time, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACK = json.load(open(os.path.join(HERE, "packs", "merge-risk.json")))
ENDPOINT = os.environ.get("TYPESAFE_BASE_URL", "https://api.typesafe.ai") + "/v1/systemone"
DIFF_CHARS = 6000

def api_key():
    k = os.environ.get("TYPESAFE_API_KEY")
    if k:
        return k
    path = os.path.expanduser("~/.config/typesafe/env.sh")
    try:
        m = re.search(r'^\s*export\s+TYPESAFE_API_KEY=["\']?([^"\'\s]+)', open(path).read(), re.M)
    except OSError:
        return None
    return m.group(1) if m else None

def git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True).stdout

# Risk lives in how a file is USED, and none of that is visible in its own diff. Measured
# 2026-09-19: without these fields every file in a 19-file change scored 0.30-0.62 blast
# radius, including the Hydra merge logic and a 405-line deletion, so the gate never fired.
RISKY = [
    ("deletes files", r"\bremoveItem|\brm -rf|\bunlink\(|\bshutil\.rmtree|FileManager\.default\.removeItem"),
    ("rewrites git history", r"push --force|--force-with-lease|filter-branch|reset --hard"),
    ("touches credentials", r"(?i)\b(secret|api[_-]?key|token|password|keychain|credential)\b"),
    ("touches a database schema", r"(?i)\b(migrat|drop table|alter table|delete from|truncate)\b"),
    ("touches billing", r"(?i)\b(charge|invoice|payment|subscription|refund)\b"),
    ("sends something outward", r"(?i)\b(urlsession|fetch\(|requests\.post|curl |sendmail|smtp)\b"),
    ("changes permissions", r"(?i)\b(chmod|sudo|permission|entitlement|sandbox)\b"),
]

def path_kind(name):
    low = name.lower()
    for token, kind in (("test", "test"), ("mock", "test fixture"), ("fixture", "test fixture"),
                        ("/views/", "UI view"), ("/ui/", "UI view"), ("/models/", "data model"),
                        ("/services/", "service"), ("/providers/", "external integration"),
                        ("/scripts/", "script"), ("/docs/", "documentation")):
        if token in low:
            return kind
    if low.endswith((".md", ".txt")):
        return "documentation"
    if low.endswith((".json", ".toml", ".yml", ".yaml")):
        return "configuration or data"
    return "source file"

def referenced_by(repo, name):
    """How many other files name this one. A file nothing references cannot reach far."""
    base = os.path.basename(name)
    stem = os.path.splitext(base)[0]
    if len(stem) < 4:
        return 0
    out = subprocess.run(["git", "-C", repo, "grep", "-l", "--fixed-strings", stem],
                         capture_output=True, text=True, timeout=20).stdout
    return max(0, len([l for l in out.splitlines() if l.strip() and l.strip() != name]))

def changed_files(repo, rng):
    names = [l for l in git(repo, "diff", "--name-only", rng).splitlines() if l.strip()]
    out = []
    for name in names:
        stat = git(repo, "diff", "--numstat", rng, "--", name).split()
        added, removed = (stat[0], stat[1]) if len(stat) >= 2 else ("?", "?")
        diff = git(repo, "diff", "-U2", rng, "--", name)[:DIFF_CHARS]
        flags = [label for label, pat in RISKY if re.search(pat, diff)]
        try:
            refs = referenced_by(repo, name)
        except Exception:
            refs = -1
        out.append({"file": name, "added": added, "removed": removed, "diff": diff,
                    "kind": path_kind(name), "refs": refs, "risky": flags,
                    "deletion_only": added in ("0", "?") and removed not in ("0", "?")})
    return out

def judge(key, item):
    refs = item["refs"]
    reach = ("unknown" if refs < 0 else
             "nothing else in the repository names this file" if refs == 0 else
             f"{refs} other file(s) in the repository name this file")
    state = {"file_path": item["file"], "diff_summary": item["diff"],
             "lines_added": item["added"], "lines_removed": item["removed"],
             "role": f"{item['kind']}; {reach}",
             "deletion_only": item["deletion_only"],
             "diff_touches": item["risky"] or ["nothing on the irreversible list"]}
    body = json.dumps({"state": state, "model": "jev-latest", "questions": PACK["questions"]}).encode()
    req = urllib.request.Request(ENDPOINT, data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return {**item, "answers": json.load(r)}
        except urllib.error.HTTPError as e:
            if e.code in (429, 529) and attempt < 1:
                time.sleep(1); continue
            return {**item, "error": f"HTTP {e.code}"}
        except Exception as e:
            return {**item, "error": type(e).__name__}
    return {**item, "error": "unreachable"}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("range", nargs="?", default="HEAD~1..HEAD", help="git range, e.g. origin/main..HEAD")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--max-files", type=int, default=25)
    ap.add_argument("--json")
    args = ap.parse_args()

    files = changed_files(args.repo, args.range)
    if not files:
        print("merge-risk: nothing changed in", args.range)
        return 0
    if len(files) > args.max_files:
        print(f"merge-risk: {len(files)} files changed, over the {args.max_files} cap — "
              f"skipping the pass rather than spending {len(files)} requests. "
              f"Raise --max-files to run it anyway.")
        return 0

    key = api_key()
    if not key:
        print("merge-risk: no TYPESAFE_API_KEY, skipping (this never blocks a push)")
        return 0

    print(f"merge-risk: {len(files)} file(s) in {args.range} = {len(files)} request(s)")
    with ThreadPoolExecutor(max_workers=6) as ex:
        out = list(ex.map(lambda f: judge(key, f), files))

    rows, errors, tin, tout = [], 0, 0, 0
    for o in out:
        if "error" in o:
            errors += 1; continue
        a = o["answers"]["answers"]
        tin += o["answers"]["usage"]["input_tokens"]; tout += o["answers"]["usage"]["output_tokens"]
        rows.append({"file": o["file"], "added": o["added"], "removed": o["removed"],
                     "blast": a["blast_radius"]["score"],
                     "irreversible": a["irreversible_path"]["noul"],
                     "behaviour": a["behaviour_change"]["noul"],
                     "route": a["route"]["choice"]})
    gates = PACK["thresholds"]
    rows.sort(key=lambda r: (-r["irreversible"], -r["blast"]))
    print()
    for r in rows:
        mark = "READ" if (r["irreversible"] > gates["irreversible_path"]["gate"]
                          or r["blast"] > gates["blast_radius"]["gate"]) else "    "
        print(f"  {mark}  blast {r['blast']:.2f}  irreversible {r['irreversible']:.2f}  "
              f"+{r['added']}/-{r['removed']}  {r['file']}")
    read = sum(1 for r in rows if r["irreversible"] > gates["irreversible_path"]["gate"]
               or r["blast"] > gates["blast_radius"]["gate"])
    print(f"\n  {read} of {len(rows)} file(s) worth a human read first. "
          f"usage {tin} in / {tout} out." + (f" {errors} call(s) failed." if errors else ""))
    print("  Advisory: this ranks what to read. It does not gate the push; the tests do.")
    if args.json:
        json.dump(rows, open(args.json, "w"), indent=1)
    return 0

if __name__ == "__main__":
    sys.exit(main())
