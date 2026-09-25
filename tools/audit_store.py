#!/usr/bin/env python3
"""One command for a skill-store reference audit.

Deterministic first: census, Windows paths, present-assertions, resolution. Jev only on
what a script cannot settle, one request per reference, count announced before spending.
"""
import argparse, sys, json, os, re, sys, time, urllib.request, urllib.error
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from spend_log import record as _record_spend

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "tools"))
from skill_refs import collect, deterministic_findings  # noqa: E402
from absence_check import check_absences, check_presence_claims  # noqa: E402

PACK = json.load(open(os.path.join(HERE, "packs", "skill-store-stale-ref.json")))
ENDPOINT = os.environ.get("TYPESAFE_BASE_URL", "https://api.typesafe.ai") + "/v1/systemone"
GATE = PACK["thresholds"]["is_stale"]["gate"]
ASSERTS_CURRENT = re.compile(r'^\s*>?\s*(?:present|installed|lives at|available)\b', re.I)

def _logged(tool, payload):
    try:
        _record_spend(tool, payload.get("model"), len(payload.get("answers") or {}), payload.get("usage"))
    except Exception:
        pass
    return payload


def api_key():
    k = os.environ.get("TYPESAFE_API_KEY")
    if k:
        return k
    path = os.path.expanduser("~/.config/typesafe/env.sh")
    if not os.path.isfile(path):
        sys.exit(f"TYPESAFE_API_KEY unset and no export line in {path}")
    try:
        content = open(path).read()
    except OSError:
        sys.exit(f"TYPESAFE_API_KEY unset and no export line in {path}")
    m = re.search(r'^\s*export\s+TYPESAFE_API_KEY=["\']?([^"\'\s]+)', content, re.M)
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
             "line_asserts_current_state": bool(ASSERTS_CURRENT.match(r["text"])) or " is archived at " in r["text"]}
    body = json.dumps({"state": state, "model": "jev-latest", "questions": PACK["questions"]}).encode()
    req = urllib.request.Request(ENDPOINT, data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return {**r, "answers": _logged("audit_store", json.load(resp))}
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
    ap.add_argument("--force-chance-pack", action="store_true",
                    help="spend on the stale-ref judgment anyway; it measured at chance")
    ap.add_argument("--json", help="write the scored results here")
    args = ap.parse_args()

    refs = collect(args.store)
    paths = [r for r in refs if r["kind"] == "path"]
    counts = Counter(r["status"] for r in paths)
    relatives = [r for r in refs if r["kind"] == "relative"]
    rel_counts = Counter(r["status"] for r in relatives)
    print(f"store            : {args.store}")
    print(f"files with refs  : {len({r['file'] for r in refs})}")
    print(f"path references  : {len(paths)}  {dict(counts)}")
    print(f"relative refs    : {len(relatives)}  {dict(rel_counts)}")
    print(f"url references   : {len({r['ref'] for r in refs if r['kind'] == 'url'})} unique (not judged here)")

    wrong_present = deterministic_findings(refs, args.store)
    windows = [r for r in paths if r["status"] == "windows-path"]
    false_absences, allowlisted_absences = check_absences(args.store)
    # Only the EMPTY verdict is reported here: 'present but missing' is already
    # covered by deterministic_findings above, and two checks reporting one fact
    # under two labels is two numbers that can disagree.
    _pres, _pres_allow = check_presence_claims(args.store)
    false_presences = [r for r in _pres if 'EMPTY' in r['verdict']]
    print(f"\ndeterministic findings, no spend:")
    print(f"  asserted present but absent : {len(wrong_present)}")
    for r in wrong_present:
        print(f"      {r['file']}:{r['line']}  {r['ref']}")
    print(f"  windows paths (previous host): {len(windows)} in {len({r['file'] for r in windows})} files")
    print(f"  asserted absent but exists  : {len(false_absences)}")
    print(f"  claimed usable but 0 bytes  : {len(false_presences)}")
    for r in false_presences:
        print(f"    {r['file']}:{r['line']}  {r['path']}  {r['verdict']}")
    for r in false_absences:
        print(f"      {r['file']}:{r['line']}  {r['path']}")
    if allowlisted_absences:
        print(f"  allowlisted absence claims  : {len(allowlisted_absences)}")
        for r in allowlisted_absences:
            reason_str = f"  ({r['reason']})" if r.get("reason") else ""
            print(f"      {r['file']}:{r['line']}  {r['path']}{reason_str}")

    missing = [r for r in paths if r["status"] == "missing"]
    det_keys = {(r["file"], r["ref"]) for r in wrong_present}
    seen, todo = set(det_keys), []
    for r in missing:
        k = (r["file"], r["ref"])
        if k not in seen:
            seen.add(k); todo.append(r)
    # The skill-store-stale-ref pack was fitted and held out on 36 hand-labelled
    # references on 2026-09-19 and measured AT CHANCE: is_stale holdout 61.1% (Wilson
    # lower 0.386), load_bearing 44.4%, risk_if_wrong 50.0%, tie width 0.00. Every
    # disagreement was the model re-deriving whether a path resolves, which the
    # deterministic checks above already answer exactly and for free. The pass stays
    # reachable behind an explicit flag so the measurement can be repeated, but it is
    # no longer offered as work worth doing.
    print(f"\njudgment pass    : DISABLED - pack measured at chance on a held-out split"
          f" (see packs/skill-store-stale-ref.json). {len(todo)} reference(s) would have"
          f" been sent. The deterministic checks above cover this question.")
    if not args.run:
        return
    if not args.force_chance_pack:
        print("refusing to spend on a chance-level gate; pass --force-chance-pack to override.")
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
