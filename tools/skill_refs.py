"""Extract and resolve references in a skill store, with the document-level context a
judgment needs. Import `collect()`; run directly for a summary."""
import os, re, glob, json

TICK = re.compile(r'`([^`\n]+)`')
BARE = re.compile(r'(?<![\w`/])((?:~/|~/)[^\s`"\'()<>,;]+)')
PATHISH = re.compile(r'^(?:~/|~/)')
URL = re.compile(r'https?://[^\s)>\]`"\',]+')
# Relative pointers between skill files. This class hid the MAGI->CONCLAVE rename for
# three days: every doc said `references/conclave-battery.md` and the file on disk was
# `magi-battery.md`, and an audit that only resolved ~/ and /Users/ paths never saw it.
REL = re.compile(r'`((?:\./|\.\./|references/|scripts/|tools/|assets/)[\w./-]+\.[\w]{1,5})`')
# A disclosure can sit under a section heading well above the line it governs.
DISCLOSURE_WINDOW_BEFORE = 12
DISCLOSURE_WINDOW_AFTER = 3
DISCLOSES = ("not present", "does not exist", "did not travel", "is absent", "no longer",
             "not wired", "not on this mac", "is not a real", "absent on this mac",
             "never arrived", "no equivalent")
ARCHIVE_MARKS = ("archived generation", "previous-host text", "archived text",
                 "reference only", "history, not instructions")

def _fenced_lines(lines):
    inside, marks = False, set()
    for i, l in enumerate(lines, 1):
        if l.lstrip().startswith("```"):
            inside = not inside
            continue
        if inside:
            marks.add(i)
    return marks

def _candidates(line):
    out = []
    for c in TICK.findall(line):
        c = c.strip()
        # A backticked span can be `<path> <subcommand>`; only the first token is a path.
        first = c.split()[0] if c.split() else ""
        if PATHISH.match(first):
            out.append(first)
    out += [m.group(1) for m in BARE.finditer(line)]
    return out

def status(ref):
    # A backslash path is a previous-host leftover: categorically wrong here, no judgment needed.
    if "\\" in ref:
        return "windows-path"
    target = os.path.expanduser(ref)
    if os.path.exists(target):
        return "exists"
    # `{a,b,c}` is a shell brace expansion, not a path.
    if any(ch in ref for ch in "<>*{}") or ref.endswith("/"):
        return "placeholder"
    parent, base = os.path.dirname(target), os.path.basename(target)
    if base and os.path.isdir(parent) and any(n.startswith(base) for n in os.listdir(parent)):
        return "truncated"
    return "missing"

def collect(store):
    files = sorted(glob.glob(os.path.join(store, "*/SKILL.md"))) + \
            sorted(glob.glob(os.path.join(store, "*/references/*")))
    refs = []
    for path in files:
        if not path.endswith((".md", ".json", ".js")):
            continue
        rel = os.path.relpath(path, store)
        try:
            lines = open(path, encoding="utf8", errors="replace").read().splitlines()
        except OSError:
            continue
        fenced = _fenced_lines(lines)
        head = "\n".join(lines[:14]).lower()
        archived = any(m in head for m in ARCHIVE_MARKS)
        for i, line in enumerate(lines, 1):
            near = "\n".join(lines[max(0, i - 1 - DISCLOSURE_WINDOW_BEFORE):i + DISCLOSURE_WINDOW_AFTER]).lower()
            discloses = any(k in near for k in DISCLOSES)
            seen = set()
            for c in _candidates(line):
                c = c.rstrip('.,;:)')
                if len(c) < 4 or c in seen:
                    continue
                seen.add(c)
                refs.append({"file": rel, "line": i, "kind": "path", "ref": c,
                             "text": line.strip()[:400], "status": status(c),
                             "file_declares_archived": archived,
                             "surrounding_text_says_absent": discloses,
                             "inside_code_block": i in fenced})
            for m in REL.finditer(line):
                rel = m.group(1)
                # `references/x.md` is written from the SKILL ROOT even when the citing
                # file itself lives under references/. `./x` and `../x` are relative to
                # the citing file.
                skill_root = os.path.join(store, os.path.relpath(path, store).split(os.sep)[0])
                anchor = os.path.dirname(path) if rel.startswith(".") else skill_root
                target = os.path.normpath(os.path.join(anchor, rel))
                refs.append({"file": os.path.relpath(path, store), "line": i, "kind": "relative",
                             "ref": rel, "text": line.strip()[:400],
                             "status": "exists" if os.path.exists(target) else "missing",
                             "resolved": target,
                             "file_declares_archived": archived,
                             "surrounding_text_says_absent": discloses,
                             "inside_code_block": i in fenced})
            for m in URL.finditer(line):
                refs.append({"file": rel, "line": i, "kind": "url", "ref": m.group(0).rstrip('.,;:`'),
                             "text": line.strip()[:400], "status": "unresolved",
                             "file_declares_archived": archived,
                             "surrounding_text_says_absent": discloses,
                             "inside_code_block": i in fenced})
    return refs

if __name__ == "__main__":
    import sys
    from collections import Counter
    store = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/.claude/skills")
    refs = collect(store)
    paths = [r for r in refs if r["kind"] == "path"]
    print("files with refs :", len({r["file"] for r in refs}))
    print("path references :", len(paths), dict(Counter(r["status"] for r in paths)))
    print("url references  :", len([r for r in refs if r["kind"] == "url"]),
          "unique", len({r["ref"] for r in refs if r["kind"] == "url"}))
    miss = [r for r in paths if r["status"] == "missing"]
    print("missing         :", len(miss))
    print("  archived file :", len([r for r in miss if r["file_declares_archived"]]))
    print("  disclosed     :", len([r for r in miss if r["surrounding_text_says_absent"]]))
    print("  in code fence :", len([r for r in miss if r["inside_code_block"]]))
    print("  none of those :", len([r for r in miss if not (r["file_declares_archived"] or r["surrounding_text_says_absent"] or r["inside_code_block"])]))
    json.dump(refs, open("/tmp/skill-refs3.json", "w"), indent=1)


# A line that asserts paths ARE present is a claim a script can settle outright: no
# judgment, no spend. Measured 2026-09-19: these score 0.32-0.39 on the stale question
# even with the enriched state, because the file around them is archived.
ASSERTS_PRESENT = re.compile(r'^\s*>?\s*(present|installed|lives at|is archived at|available)\b', re.I)

def deterministic_findings(refs, store):
    """Every reference on a present-asserting line whose target does not exist."""
    out = []
    for r in refs:
        if r["kind"] != "path" or r["status"] in ("exists", "placeholder"):
            continue
        if ASSERTS_PRESENT.match(r["text"]) or " is archived at " in r["text"]:
            out.append(r)
    return out
