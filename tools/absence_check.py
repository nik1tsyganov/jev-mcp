#!/usr/bin/env python3
"""Check a skill store for false absence claims.

Deterministic check: finds lines asserting a path is absent or does not exist on this Mac,
resolves any named paths (~/ or /Users/), and verifies whether the target actually exists on disk.
Follows the house style of skill_refs.py (stdlib only, no API calls, fast local walk).
"""
import argparse
import json
import os
import re
import sys

# Paths in backticks starting with ~/ or /Users/
PATH_TICK = re.compile(r'`((?:~/|/Users/)[^`\n]+)`')

# Real absence assertions collected from store review:
# 'not present on this Mac', 'absent on this Mac', 'do not exist here',
# 'does not exist on this Mac', 'is likewise not present', 'NOT RUN / absent',
# along with host-relative and local phrasing variants.
ABSENCE_PAT = re.compile(
    r"(not present on this mac|not present on this host|not present here|not present|"
    r"absent on this mac|absent on this host|absent here|\bis absent\b|\bare absent\b|"
    r"does not exist on this mac|does not exist here|does not exist|"
    r"do not exist on this mac|do not exist here|do not exist|"
    r"is likewise not present|likewise not present|not run\s*/\s*absent|"
    r"not installed on this mac)",
    re.IGNORECASE
)

# Contrast markers:
# What it suppresses:
#   Splits a line at contrast boundaries (semicolons, ' but ', ' however', ' instead', etc.)
#   so that paths mentioned AFTER the contrast marker as available alternatives, Mac-native
#   equivalents, or relocation targets (e.g. "X is not present; the Mac equivalent is Y",
#   "X does not exist on this Mac; instead use Y", "X was retired; moved to Y") are treated
#   as replacements rather than false absence claims.
# What it might miss (blind spot):
#   1. Compound absence claims across clauses joined by a contrast marker (e.g. "X is absent;
#      Y is likewise not present") will fail to check path Y because Y sits after the marker.
#   2. Sentences written with inverted syntax ("Instead of X, Y is not present") will confuse
#      the replacement position with the absent position.
#   3. If the absence assertion itself appears after the contrast marker ("X is present, but Y is
#      absent"), paths before the marker are NOT being claimed absent and are guarded from being
#      flagged by verifying that the pre-marker chunk contains an absence assertion.
CONTRAST_PAT = re.compile(
    r"(;| but | however| instead| the Mac | lives in | lives at | is at | moved to | archived at )",
    re.IGNORECASE
)

# Historical markers:
# What it suppresses:
#   Skips lines documenting past migrations, previous-host status notes, August 2026 pre-rename
#   records, and references to retired repository snapshots ('previous host' / 'previous-host',
#   'ARCHIVED', '2026-08', 'was renamed', 'pre-rename', 'magi-kit', 'skills-retired').
#   These lines describe historical state or prior environments rather than making binding
#   claims about the live macOS system state today.
# What it might miss (blind spot):
#   Any line that mixes historical context with a genuine current false absence claim
#   (for example, a line mentioning previous-host migration or ~/src/magi-kit that also falsely
#   asserts a current macOS file is absent) will be suppressed by this filter.
HISTORICAL_PAT = re.compile(
    r"(previous[- ]host|ARCHIVED|2026-08|was renamed|pre-rename|magi-kit|skills-retired)",
    re.IGNORECASE
)

# Sentence boundary delimiter:
# What it suppresses:
#   Suppresses cross-sentence conflation on multi-sentence lines. When an author places an
#   informative sentence mentioning existing files (e.g. "Engineering ledger ~/.claude/... exists")
#   on the same line as a separate absence sentence (e.g. "Not present: Synara..."), evaluating
#   sentences independently ensures paths from the presence sentence are not attributed to the
#   absence sentence.
# What it might miss (blind spot):
#   Sentences with complex parentheticals or abbreviations containing periods (e.g. "i.e. ")
#   could be split prematurely, potentially detaching a path from its governing absence predicate.
SENTENCE_SPLIT = re.compile(r"(?<=[\.\?!])(?:\*\*|\*|_|`|\")?\s+")


def load_allowlist(allowlist_path=None):
    """Load tools/absence_check.allow if present.

    What it suppresses:
      Suppresses exit-code failure on specific path findings that have been reviewed by a human
      and deemed acceptable exceptions, associating each with an explicit documented reason.
    What it might miss (blind spot):
      A path allowlisted for one legitimate benign mention could reappear elsewhere as a real
      defect without failing gate checks. To avoid becoming a silent blindfold, allowlisted
      hits are always reported under a visible section in the tool output.
    """
    allowlist = {}
    candidates = []
    if allowlist_path:
        candidates.append(allowlist_path)
    here = os.path.dirname(os.path.abspath(__file__))
    candidates.append(os.path.join(here, "absence_check.allow"))
    candidates.append(os.path.join(here, "..", "tools", "absence_check.allow"))
    candidates.append("tools/absence_check.allow")

    for path in candidates:
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        parts = line.split("\t", 1)
                        p = parts[0].strip()
                        reason = parts[1].strip() if len(parts) > 1 else ""
                        allowlist[p] = reason
                        allowlist[os.path.expanduser(p)] = reason
                break
            except OSError:
                pass
    return allowlist


# The mirror error, and the one that is easy to introduce while fixing the first:
# text that asserts a file is THERE, and concludes the procedure depending on it now
# runs, when the file is present at zero bytes. Correcting "absent" to "available" on
# an empty log replaces one false statement with another. Present is not usable.
PRESENCE_PAT = re.compile(
    r"\b(EXISTS|is present|now present|present as of|is available|now runs|"
    r"can now run|unblocked|no longer blocked)\b", re.I)

# `exists` appears inside negations more often than as an assertion: "no hook exists
# at all", "Neither exists in the repo". A negated sentence is not a presence claim.
NEGATOR_PAT = re.compile(r"\b(no|not|neither|never|nothing|without|absent|lacks)\b", re.I)

# An availability claim that already says the file is empty is honest, not a finding.
EMPTY_CAVEAT_PAT = re.compile(
    r"\b(empty|0 bytes|zero bytes|no rows|unpopulated|NOT RUN|still blocked|"
    r"nothing to read)\b", re.I)


def check_presence_claims(store_root, allowlist_file=None):
    """Find availability claims whose named path is missing, or present but empty.

    Works sentence by sentence, not line by line, for two reasons found by running it:
    "no PostToolUse hook exists at all" and "Neither exists in ..." both contain the
    word `exists` inside a NEGATION, and a line often asserts presence in one sentence
    while naming an absent path in another. Attribution therefore stays inside the
    sentence that makes the claim.

    Blind spots, stated: a claim split across two sentences is not caught, and a path
    named only outside the asserting sentence is not blamed. Both are deliberate.
    """
    store_root = os.path.expanduser(store_root)
    allowlist = load_allowlist(allowlist_file)
    findings, allowlisted, seen = [], [], set()

    for root, dirs, files in os.walk(store_root):
        dirs[:] = [d for d in dirs if d not in ("node_modules", ".git")]
        for fname in sorted(files):
            if not fname.endswith((".md", ".json", ".js")):
                continue
            fpath = os.path.join(root, fname)
            rel = os.path.relpath(fpath, store_root)
            try:
                lines = open(fpath, errors="ignore").read().splitlines()
            except OSError:
                continue
            for line_no, line in enumerate(lines, 1):
                if HISTORICAL_PAT.search(line):
                    continue
                for sentence in SENTENCE_SPLIT.split(line):
                    if not PRESENCE_PAT.search(sentence):
                        continue
                    if NEGATOR_PAT.search(sentence):
                        continue
                    # Test the caveat against PROSE only: a path such as
                    # `empty-ledger.jsonl` must not be able to excuse a claim
                    # about itself by supplying the word `empty`.
                    prose = PATH_TICK.sub(' ', sentence) if hasattr(PATH_TICK, 'sub') else sentence
                    discloses_empty = bool(EMPTY_CAVEAT_PAT.search(prose))
                    for raw_p in PATH_TICK.findall(sentence):
                        # A backticked string may be a COMMAND, not a path:
                        # `~/.local/bin/codex doctor` is the binary plus an
                        # argument. Take the first token and test that.
                        clean_p = raw_p.split()[0].rstrip(".,;:) ") if raw_p.split() else ""
                        if not clean_p:
                            continue
                        resolved = os.path.expanduser(clean_p)
                        verdict = None
                        if not os.path.exists(resolved):
                            verdict = "claimed present but MISSING"
                        elif os.path.isfile(resolved) and os.path.getsize(resolved) == 0 \
                                and not discloses_empty:
                            verdict = "claimed present but EMPTY (0 bytes)"
                        if not verdict:
                            continue
                        key = (rel, line_no, clean_p)
                        if key in seen:
                            continue
                        seen.add(key)
                        reason = allowlist.get(clean_p) or allowlist.get(resolved)
                        f = {"file": rel, "line": line_no, "path": clean_p,
                             "resolved": resolved, "verdict": verdict,
                             "line_text": line.strip(), "allowlisted": reason is not None}
                        if reason:
                            f["reason"] = reason
                            allowlisted.append(f)
                        else:
                            findings.append(f)
    return findings, allowlisted


def check_absences(store_root, allowlist_file=None):
    """Walk store_root, find false absence claims, and return (findings, allowlisted)."""
    store_root = os.path.expanduser(store_root)
    allowlist = load_allowlist(allowlist_file)
    findings = []
    allowlisted = []
    seen = set()

    for root, dirs, files in os.walk(store_root):
        # Skip node_modules and .git
        dirs[:] = [d for d in dirs if d not in ("node_modules", ".git")]
        for fname in sorted(files):
            if not fname.endswith((".md", ".json", ".js")):
                continue
            fpath = os.path.join(root, fname)
            rel = os.path.relpath(fpath, store_root)
            try:
                with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                    lines = f.read().splitlines()
            except OSError:
                continue

            for line_no, line in enumerate(lines, 1):
                if HISTORICAL_PAT.search(line):
                    continue
                if not ABSENCE_PAT.search(line):
                    continue

                # Multi-sentence lines: evaluate each sentence segment separately
                # to prevent presence-asserting sentences from inheriting absence claims.
                segments = SENTENCE_SPLIT.split(line)
                for seg in segments:
                    if not ABSENCE_PAT.search(seg):
                        continue

                    # Split at first contrast marker; only examine text before it
                    parts = CONTRAST_PAT.split(seg, maxsplit=1)
                    pre_marker = parts[0]

                    # If the pre-marker text doesn't assert absence, the path is not claimed absent
                    if not ABSENCE_PAT.search(pre_marker):
                        continue

                    # Extract backticked paths starting with ~/ or /Users/
                    raw_paths = PATH_TICK.findall(pre_marker)
                    for raw_p in raw_paths:
                        clean_p = raw_p.rstrip(".,;:) ")
                        resolved = os.path.expanduser(clean_p)

                        # Check existence on filesystem
                        if os.path.exists(resolved):
                            key = (rel, line_no, clean_p)
                            if key in seen:
                                continue
                            seen.add(key)

                            # Check allowlist
                            reason = allowlist.get(clean_p) or allowlist.get(resolved)
                            is_allowlisted = reason is not None
                            finding = {
                                "file": rel,
                                "line": line_no,
                                "path": clean_p,
                                "resolved": resolved,
                                "text": line.strip(),
                                "line_text": line.strip(),
                                "allowlisted": is_allowlisted,
                            }
                            if is_allowlisted:
                                finding["reason"] = reason
                                allowlisted.append(finding)
                            else:
                                findings.append(finding)

    return findings, allowlisted



def selftest():
    """Prove both checks can FIRE, not merely that they print OK.

    A detector that has only ever reported zero is indistinguishable from a detector
    that cannot report anything. This builds a fixture with one known-bad empty claim,
    one known-bad missing claim, one honest disclosure and one negated sentence, and
    asserts exactly two findings.
    """
    import shutil, tempfile
    root = os.path.expanduser("~/.local/scratch/absence-selftest")
    shutil.rmtree(root, ignore_errors=True)
    os.makedirs(os.path.join(root, "fake-skill"))
    ledger = os.path.join(root, "ledger.jsonl")
    open(ledger, "w").close()
    gone = os.path.join(root, "gone.js")
    with open(os.path.join(root, "fake-skill", "SKILL.md"), "w") as fh:
        fh.write(
            f"- The ledger `{ledger}` EXISTS as of 2026-09-19, so the procedure can now run.\n"
            f"- The reader `{gone}` is present and the check is unblocked.\n"
            f"- Honest: `{ledger}` EXISTS but is empty, so this still reports NOT RUN.\n"
            f"- Negated: no capture hook exists at all, and `{gone}` is absent too.\n")
    found, _ = check_presence_claims(root)
    shutil.rmtree(root, ignore_errors=True)
    verdicts = sorted((f["line"], f["verdict"].split()[3]) for f in found)
    expected = [(1, "EMPTY"), (2, "MISSING")]
    if verdicts != expected:
        print(f"selftest FAILED: expected {expected}, got {verdicts}", file=sys.stderr)
        return 1
    print("selftest: both checks fire correctly (1 empty, 1 missing, 2 correctly silent)")
    return 0


def main():
    ap = argparse.ArgumentParser(description="Check skill stores for false absence claims.")
    ap.add_argument("pos_store", nargs="?", default=None, help="Skill store root directory")
    ap.add_argument("--store", default=os.path.expanduser("~/.claude/skills"), help="Skill store root directory")
    ap.add_argument("--selftest", action="store_true",
                    help="prove the checks can fire, then exit")
    ap.add_argument("--json", nargs="?", const=True, default=False, help="Emit JSON to stdout (or to specified file)")
    ap.add_argument("--allow", default=None, help="Path to allowlist file")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    store = os.path.expanduser(args.pos_store or args.store)
    findings, allowlisted = check_absences(store, allowlist_file=args.allow)

    pres_findings, pres_allow = check_presence_claims(store, allowlist_file=args.allow)
    for f in pres_findings:
        print(f"{f['file']}:{f['line']}  <{f['path']}>  {f['verdict']}")
    if pres_findings:
        print(f"{len(pres_findings)} false presence claim(s) found.")
    findings = findings + pres_findings

    if args.json:
        all_results = findings + allowlisted
        formatted_json = json.dumps(all_results, indent=2)
        if isinstance(args.json, str):
            with open(args.json, "w", encoding="utf-8") as out:
                out.write(formatted_json + "\n")
        else:
            print(formatted_json)
        sys.exit(1 if findings else 0)

    # Human-readable output
    for f in findings:
        print(f"{f['file']}:{f['line']}  <{f['path']}>  EXISTS but the line claims it is absent")

    if allowlisted:
        print("\nallowlisted findings:")
        for a in allowlisted:
            reason_str = f"  ({a['reason']})" if a.get("reason") else ""
            print(f"  {a['file']}:{a['line']}  <{a['path']}>{reason_str}")

    total_claims = len(findings) + len(allowlisted)
    print(f"\n{len(findings)} false absence claim(s) found ({len(allowlisted)} allowlisted, {total_claims} total).")
    sys.exit(1 if findings else 0)


if __name__ == "__main__":
    main()
