#!/usr/bin/env python3
"""Score delegation briefs before they are dispatched.

Reads a Hydra-style JSON array of {task, prompt, name?, project?} on stdin or from a
file, asks Jev the head-brief-quality pack once per brief, and applies the pack's
thresholds in code. Advisory by design: it prints a verdict and exits 0 unless --strict.
"""
import argparse, json, os, re, sys, time, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACK_PATH = os.path.join(HERE, "packs", "head-brief-quality.json")
ENDPOINT = os.environ.get("TYPESAFE_BASE_URL", "https://api.typesafe.ai") + "/v1/systemone"
FILE_RE = re.compile(r'(?:[\w./-]*/)?[\w.-]+\.(?:py|js|mjs|ts|tsx|swift|json|md|sh|toml|yml|yaml)\b')
# A brief mentions many files and writes few. Overlap is only meaningful for the files an
# agent is told to CREATE or EDIT, so only those count: measured 2026-09-19, counting every
# mention put file_overlap at 0.83-0.97 for eleven briefs that shared no write target at all.
EDIT_VERB = re.compile(
    r'\b(creat\w*|edit\w*|writ\w*|modif\w*|patch\w*|rewrit\w*|add to|append to|replace in|touch)\b',
    re.I)
EDIT_WINDOW = 220

def api_key():
    k = os.environ.get("TYPESAFE_API_KEY")
    if k:
        return k
    path = os.path.expanduser("~/.config/typesafe/env.sh")
    m = re.search(r'^\s*export\s+TYPESAFE_API_KEY=["\']?([^"\'\s]+)', open(path).read(), re.M)
    if not m:
        sys.exit(f"TYPESAFE_API_KEY is unset and no export line was found in {path}")
    return m.group(1)

def files_in(text):
    """Every file path the brief mentions."""
    return sorted({m.group(0) for m in FILE_RE.finditer(text)})

NEGATION = re.compile(r"\b(do not|don't|never|without|avoid|rather than|instead of|not)\b\s*$", re.I)
NEAR_NEGATION = re.compile(r"\b(do not|don't|never|without|avoid|rather than|instead of|leave alone|not)\b", re.I)

def write_targets(text):
    """Only the files the brief tells the agent to create or edit.

    A prohibition reads like an instruction to the naive version of this: "Do not touch
    package.json" put package.json in four briefs' write sets on 2026-09-19, which then
    looked like four agents colliding on one file.
    """
    spans = []
    for m in EDIT_VERB.finditer(text):
        before = text[max(0, m.start() - 24):m.start()]
        if NEGATION.search(before):
            continue
        spans.append(m.end())
    out = set()
    for m in FILE_RE.finditer(text):
        if not any(0 <= m.start() - e <= EDIT_WINDOW for e in spans):
            continue
        # A legitimate verb earlier in the paragraph reaches across the sentence that
        # forbids a file ("Create X. Do not touch Y"), so the text right before the
        # filename decides.
        if NEAR_NEGATION.search(text[max(0, m.start() - 70):m.start()]):
            continue
        out.add(m.group(0))
    return sorted(out)

def ask(key, pack, brief, sibling_files):
    state = {
        "task_title": brief.get("task", ""),
        "brief_text": brief["prompt"][:12000],
        "files_named": write_targets(brief["prompt"]),
        "sibling_files": sibling_files,
    }
    body = json.dumps({"state": state, "model": "jev-latest", "questions": pack["questions"]}).encode()
    req = urllib.request.Request(ENDPOINT, data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (429, 529) and attempt < 2:
                time.sleep(1.5 * (attempt + 1)); continue
            return {"error": f"HTTP {e.code}: {e.read()[:200].decode(errors='replace')}"}
        except Exception as e:
            if attempt < 2:
                time.sleep(1.5); continue
            return {"error": str(e)}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file", nargs="?", help="JSON array of briefs; omit to read stdin")
    ap.add_argument("--strict", action="store_true", help="exit 1 when any brief fails a gate")
    ap.add_argument("--json", action="store_true", help="emit the scored briefs as JSON")
    args = ap.parse_args()

    briefs = json.load(open(args.file) if args.file else sys.stdin)
    if not isinstance(briefs, list) or not briefs:
        sys.exit("expected a non-empty JSON array of briefs")
    pack = json.load(open(PACK_PATH))
    key = api_key()
    per_brief_files = [write_targets(b["prompt"]) for b in briefs]

    siblings_of = {}

    def one(i):
        siblings = sorted({f for j, fs in enumerate(per_brief_files) if j != i for f in fs})
        siblings_of[id(briefs[i])] = siblings
        return ask(key, pack, briefs[i], siblings)

    with ThreadPoolExecutor(max_workers=6) as ex:
        answers = list(ex.map(one, range(len(briefs))))

    gates = pack["thresholds"]
    rows, failed, tokens = [], 0, [0, 0]
    for brief, ans, files in zip(briefs, answers, per_brief_files):
        if "error" in ans:
            rows.append((brief, None, ["call failed: " + ans["error"]], files)); continue
        a = ans["answers"]
        tokens[0] += ans["usage"]["input_tokens"]; tokens[1] += ans["usage"]["output_tokens"]
        notes = []
        sc = a["self_contained"]["score"]
        if sc < gates["self_contained"]["gate"]:
            notes.append(f"self-contained {sc:.2f} < {gates['self_contained']['gate']}")
        if a["ambiguous"]["noul"] > gates["ambiguous"]["gate"]:
            notes.append(f"ambiguous {a['ambiguous']['noul']:.2f}")
        # Overlap is a set intersection, so code decides it and the model's answer is
        # ignored: with only basenames in the state the judgment reads SKILL.md in two
        # different directories as the same file (measured 2026-09-19, 0.44-0.93 on
        # eleven briefs whose real intersection was empty).
        shared = sorted(set(files) & set(siblings_of[id(brief)]))
        if shared:
            notes.append("shares write targets with another brief: " + ", ".join(shared))
        if a["names_exact_files"]["noul"] < 0.5:
            notes.append(f"names no exact files {a['names_exact_files']['noul']:.2f}")
        if a["has_acceptance"]["noul"] < 0.5:
            notes.append(f"no acceptance criteria {a['has_acceptance']['noul']:.2f}")
        if a["sizing"]["choice"] != "one_agent":
            notes.append(f"sizing says {a['sizing']['choice']} (p={max(a['sizing']['probabilities'].values()):.2f})")
        failed += bool(notes)
        rows.append((brief, a, notes, files))

    if args.json:
        print(json.dumps([{"task": b.get("task"), "notes": n, "answers": a} for b, a, n, _ in rows], indent=2))
    else:
        for brief, a, notes, files in rows:
            name = brief.get("name") or brief.get("task", "?")
            head = f"{'PASS' if not notes else 'HOLD'}  {name[:34]:34s}"
            if a:
                head += f" self-contained {a['self_contained']['score']:.2f}  files {len(files)}"
            print(head)
            for n in notes:
                print(f"        - {n}")
        print(f"\n{len(rows)} briefs, {failed} held, usage {tokens[0]} in / {tokens[1]} out")
    if args.strict and failed:
        sys.exit(1)

if __name__ == "__main__":
    main()
