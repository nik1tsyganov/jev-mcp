#!/usr/bin/env python3
"""Audit support trees (~/.claude/docs, hooks, commands, workflows) for broken references,
Windows path leftovers, and unexpanded home paths.

Import `collect()`; run directly for a summary.
"""
import os
import re
import sys

DEFAULT_ROOTS = (
    "~/.claude/docs",
    "~/.claude/hooks",
    "~/.claude/commands",
    "~/.claude/workflows",
)
VALID_EXTS = (".md", ".js", ".json", ".sh", ".py")
MAX_FILE_SIZE = 2 * 1024 * 1024  # 2 MB

TICK = re.compile(r'`([^`\n]+)`')
BARE = re.compile(r'(?<![\w`/])((?:~[\\/]|~[\\/])[^\s`"\'()<>,;]+)')
PATHISH = re.compile(r'^(?:~[\\/]|~[\\/])')

WINDOWS_HOME_RE = re.compile(
    r'C:[\\/]+Users|%USERPROFILE%|process\.env(?:\.USERPROFILE|\[[\'"]USERPROFILE[\'"]\])',
    re.I
)

# Calls passing string literals beginning with ~/
UNEXPANDED_TILDE_RE = re.compile(
    r'(?:'
    r'\breadFileSync\s*\(\s*[\'"`]~/'
    r'|\breadFile\s*\(\s*[\'"`]~/'
    r'|\bopen\s*\(\s*[frbFRB]?[\'"`]~/'
    r'|\bcat\s+[\'"`]?~/'
    r'|\bsource\s+[\'"`]?~/'
    r')'
)

HOME_EXPANSION_MARKERS = ("os.homedir", "expanduser", "$HOME", "${HOME}", "process.env.HOME")
REDACT_KEYWORDS = ("KEY", "TOKEN", "SECRET", "PASSWORD")


def normalize_display_path(path):
    """Abbreviate user home prefix for clean reporting."""
    home = os.path.expanduser("~")
    if path.startswith(home):
        return "~" + path[len(home):]
    return path


def redact_line(text):
    """Truncate line to 160 characters, redacting credentials."""
    if any(k in text.upper() for k in REDACT_KEYWORDS):
        return "[redacted]"
    return text.strip()[:160]


def find_candidates(line):
    """Extract candidate path strings from a line."""
    out = []
    for c in TICK.findall(line):
        c = c.strip()
        first = c.split()[0] if c.split() else ""
        if PATHISH.match(first):
            out.append(first)
    out.extend(m.group(1) for m in BARE.finditer(line))
    return out


def check_path_status(ref, line=None):
    """Categorize a path reference: exists, placeholder, truncated, or missing."""
    if any(ch in ref for ch in "<>*{}"):
        return "placeholder"
    target = os.path.expanduser(ref)
    if os.path.exists(target):
        return "exists"
    # A path stopping at whitespace whose prefix matches a real file is truncated.
    clean_target = target.rstrip("/\\")
    parent, base = os.path.dirname(clean_target), os.path.basename(clean_target)
    # The extractor cuts a path at the first space, so `~/Library/Application Support/x`
    # arrives as `~/Library/Application`. Rebuild it from the line and see whether it
    # RESOLVES: a prefix heuristic guessed, and guessed both ways - it called a real
    # truncation missing and a genuinely absent path truncated (2026-09-19).
    if line:
        at = line.find(ref)
        if at >= 0:
            acc = ref
            for token in line[at + len(ref):].split()[:5]:
                acc = acc + " " + token.rstrip('`",;:)')
                if os.path.exists(os.path.expanduser(acc)):
                    return "truncated"
    if base and os.path.isdir(parent):
        try:
            if any(n.startswith(base) for n in os.listdir(parent)) and line and re.search(re.escape(ref) + r"\w", line):
                return "truncated"
        except OSError:
            pass
    return "missing"


def has_home_expansion(content):
    """Check whether a file contains any standard home directory expansion."""
    return any(marker in content for marker in HOME_EXPANSION_MARKERS)


# Three kinds of file legitimately carry paths that do not resolve here, and counting
# them buries the signal: a GENERATED index (its text is quoted from elsewhere), a DATED
# report or fixture (it records what was true then), and an AUDIT report (it quotes the
# broken paths it found). Measured 2026-09-19: excluding these takes 421 windows-home
# hits to 264 and 268 missing to 60, without hiding a single live defect.
EXCLUDE_NAMES = ("lesson-index.json",)
EXCLUDE_PAT = re.compile(r"(\d{4}-\d{2}-\d{2})|/reports/|/battery/|/fixtures|AUDIT|GAP-LIST|GAP-FIX")

# A path the document itself calls absent is a correct record, not a defect. The store
# auditor has had this since the 43-to-7 pass; without it here, 55 of 91 "missing paths"
# were lines that already say the target is gone.
DISCLOSES = ("not present", "does not exist", "did not travel", "is absent", "no longer exist",
             "not wired", "not on this mac", "is not a real", "absent on this mac",
             "never arrived", "no equivalent", "was renamed", "renamed to", "was replaced")
DISCLOSURE_BEFORE = 6
DISCLOSURE_AFTER = 3

def disclosed_near(lines, idx):
    lo = max(0, idx - DISCLOSURE_BEFORE)
    window = " ".join(lines[lo:idx + DISCLOSURE_AFTER + 1]).lower()
    return any(k in window for k in DISCLOSES)

# sync-map.json states presence per entry. An entry carrying presentOnThisMac:false has
# already been judged; re-reporting it is noise.
def declared_absent(lines, idx):
    lo = max(0, idx - 3)
    window = " ".join(lines[lo:idx + 6]).lower().replace(" ", "").replace("\n", "")
    return '"presentonthismac":false' in window


def is_excluded(path):
    return os.path.basename(path) in EXCLUDE_NAMES or bool(EXCLUDE_PAT.search(path))


def find_files(roots=None):
    """Yield all qualifying files across existing roots."""
    if roots is None:
        roots = DEFAULT_ROOTS
    for root in roots:
        root_path = os.path.expanduser(root)
        if not os.path.exists(root_path):
            continue
        if os.path.isfile(root_path):
            if root_path.endswith(VALID_EXTS):
                try:
                    if os.path.getsize(root_path) <= MAX_FILE_SIZE:
                        yield root_path
                except OSError:
                    pass
            continue
        for dirpath, dirnames, filenames in os.walk(root_path, topdown=True):
            dirnames[:] = [d for d in dirnames if d not in ("node_modules", ".git")]
            for f in sorted(filenames):
                if not f.endswith(VALID_EXTS):
                    continue
                full_path = os.path.join(dirpath, f)
                if is_excluded(full_path):
                    continue
                try:
                    if os.path.getsize(full_path) > MAX_FILE_SIZE:
                        continue
                except OSError:
                    continue
                yield full_path


def collect(roots=None):
    """Audit the support trees and partition findings into four classes.

    Returns dict mapping class name to list of (file, line, text):
      - windows_home: Class 1 findings
      - backslash_path: Class 2 findings
      - missing_path: Class 3 findings
      - unexpanded_tilde: Class 4 findings (SUSPECT heuristic)
      - truncated_path: Truncated paths (counted separately, excluded from missing)
    """
    windows_home = []
    backslash_path = []
    missing_path = []
    unexpanded_tilde = []
    truncated_path = []
    suppressed = 0

    for file_path in find_files(roots):
        disp_file = normalize_display_path(file_path)
        try:
            with open(file_path, "r", encoding="utf8", errors="replace") as f:
                content = f.read()
        except OSError:
            continue

        lines = content.splitlines()
        is_code_file = file_path.endswith((".js", ".py", ".sh"))
        file_has_expansion = has_home_expansion(content) if is_code_file else True

        for line_num, line in enumerate(lines, 1):
            redacted = redact_line(line)
            idx = line_num - 1

            # Class 1: WINDOWS HOME
            if WINDOWS_HOME_RE.search(line):
                windows_home.append((disp_file, line_num, redacted))

            # Path candidates for Class 2 (BACKSLASH PATH) and Class 3 (MISSING PATH)
            seen_candidates = set()
            line_has_backslash = False
            line_has_missing = False
            line_has_truncated = False

            for c in find_candidates(line):
                c = c.rstrip(".,;:)")
                if len(c) < 2 or c in seen_candidates:
                    continue
                seen_candidates.add(c)

                # Class 2: BACKSLASH PATH. `\"` is JSON string escaping, not a path
                # separator: three sync-map test commands reported as Windows paths on
                # 2026-09-19 were correctly-ported POSIX commands inside escaped quotes.
                if re.search(r"\\\\\w", c):
                    line_has_backslash = True
                    continue

                # Class 3: MISSING PATH
                st = check_path_status(c, line)
                if st == "missing":
                    # Only this class is about absence, so only this class is silenced
                    # by a nearby statement that the target is absent.
                    if disclosed_near(lines, idx) or declared_absent(lines, idx):
                        suppressed += 1
                        continue
                    line_has_missing = True
                elif st == "truncated":
                    line_has_truncated = True

            if line_has_backslash:
                backslash_path.append((disp_file, line_num, redacted))
            if line_has_missing:
                missing_path.append((disp_file, line_num, redacted))
            elif line_has_truncated:
                truncated_path.append((disp_file, line_num, redacted))

            # Class 4: UNEXPANDED TILDE IN CODE (heuristic)
            if is_code_file and not file_has_expansion:
                if UNEXPANDED_TILDE_RE.search(line):
                    unexpanded_tilde.append((disp_file, line_num, redacted))

    return {
        "windows_home": windows_home,
        "backslash_path": backslash_path,
        "missing_path": missing_path,
        "unexpanded_tilde": unexpanded_tilde,
        "truncated_path": truncated_path,
        "suppressed_disclosed": suppressed,
    }


def main():
    roots = sys.argv[1:] if len(sys.argv) > 1 else None
    findings = collect(roots)

    windows_home = findings["windows_home"]
    backslash_path = findings["backslash_path"]
    missing_path = findings["missing_path"]
    unexpanded_tilde = findings["unexpanded_tilde"]
    truncated_path = findings["truncated_path"]

    print("Audit counts by class:")
    print(f"  1. WINDOWS HOME               : {len(windows_home)}")
    print(f"  2. BACKSLASH PATH             : {len(backslash_path)}")
    print(f"  3. MISSING PATH               : {len(missing_path)}")
    print(f"  4. UNEXPANDED TILDE (SUSPECT) : {len(unexpanded_tilde)}")
    print(f"     Truncated paths (excluded) : {len(truncated_path)}")

    sections = [
        ("WINDOWS HOME", windows_home, None),
        ("BACKSLASH PATH", backslash_path, None),
        ("MISSING PATH", missing_path, None),
        ("UNEXPANDED TILDE IN CODE", unexpanded_tilde, "SUSPECT - heuristic, not verified broken"),
    ]

    for name, items, note in sections:
        header = f"\n=== {name} ({len(items)})"
        if note:
            header += f" [{note}]"
        header += " ==="
        print(header)
        for disp_file, line_num, text in items:
            print(f"  {disp_file}:{line_num}  {text}")

    sys.exit(0)


if __name__ == "__main__":
    main()
