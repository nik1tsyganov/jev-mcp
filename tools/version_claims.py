"""Extract and check tool version claims and model slugs against live ground truth.

Import `claims()`, `live_facts()`, `compare()`; run directly for a summary.
Plain standard library only.
"""
import glob
import os
import re
import subprocess
import sys

ARCHIVE_MARKS = (
    "archived generation",
    "previous-host text",
    "archived text",
    "reference only",
)

TOOL_MAP = {
    "agy": "agy",
    "antigravity cli": "agy",
    "claude": "claude",
    "claude code": "claude",
    "codex": "codex",
    "codex cli": "codex",
    "cursor-agent": "cursor-agent",
}

TOOL_PAT = re.compile(
    r"\b(antigravity\s+cli|claude\s+code|codex\s+cli|cursor-agent|agy|claude|codex)\b",
    re.IGNORECASE,
)

SLUG_PAT = re.compile(r"\bgemini-\d+(?:\.\d+)?-(?:flash|pro)(?:-(?:high|medium|low))?\b")

# A bare decimal is almost never a version: a routing log full of probabilities
# (0.48, 0.59) produced 82 of 84 false positives on the first run, 2026-09-19. Require
# either three parts (1.2.7) or an explicit version marker right before the number.
# Deliberately omitted: two-part versions following tool names without 'version' or 'v' (e.g. 'agy 1.2') are excluded to prevent bare decimals from matching as false positives.
VERSION_PAT = re.compile(
    r"(?<![\w-])(?:(?<=[vV])|(?<=version )|(?<=version: )|(?<=CLI )|(?<=cli ))?(\d+(?:\.\d+){2,})\b"
    r"|(?<![\w-])[vV](\d+(?:\.\d+)+)\b"
    r"|(?<=version )(\d+(?:\.\d+)+)\b"
    r"|(?<=CLI )(\d+(?:\.\d+)+)\b")

def _version_of(match):
    """The first non-empty group of VERSION_PAT."""
    for g in match.groups():
        if g:
            return g
    return None

# A skill's own frontmatter `version:` is the skill's version, not a tool's.
FRONTMATTER_VERSION = re.compile(r'"version"\s*:|^version:', re.M)

# A line that already says the slug is retired is a correct historical statement, not a
# stale claim. Same rule the path auditor uses: judge the claim, not the string.
# A dated record — a log, or an evidence file whose name or title carries the date it
# was written — is expected to name what was live THEN. Judging it against today is a
# category error, the same one that flagged archived files in the path audit.
DATED_RECORD = re.compile(r"(\d{4}-\d{2}-\d{2})|(^|/)[\w-]*-log\.md$|routing-log|history-")

def is_dated_record(rel_path, head_text):
    if DATED_RECORD.search(rel_path):
        return True
    first_heading = next((l for l in head_text.splitlines() if l.startswith("#")), "")
    return bool(re.search(r"\d{4}-\d{2}-\d{2}", first_heading))

RETIRED_NEARBY = re.compile(
    r"(?i)\b(no longer exist|retired|is gone|was gone|older generation|previous generation|"
    r"historical|superseded|culled|not present|absent|deprecat|used to be|the old default|"
    r"stale|illustrative|for example|an example of)\b")


def _run_cmd(cmd, timeout=5):
    """Run a local command with short timeout; return stdout or None on failure/missing binary."""
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if res.returncode != 0:
            return None
        return res.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError, subprocess.SubprocessError):
        return None


def _extract_version(output):
    """Extract the first dotted version number from command stdout."""
    if not output:
        return None
    m = re.search(r"\b\d+(?:\.\d+)+\b", output)
    return m.group(0) if m else (output.strip() or None)


def _get_models(timeout=5):
    """Run `agy models` and parse slug<TAB>Name stdout into a set of model slugs."""
    out = _run_cmd(["agy", "models"], timeout=timeout)
    if out is None:
        return None
    slugs = set()
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            s = parts[0].strip()
            if s:
                slugs.add(s)
    return slugs


def live_facts(timeout=5):
    """Gather ground truth by running local commands with short timeouts.

    Missing binaries yield None rather than raising exceptions.
    Never passes or prints credentials.
    """
    return {
        "agy": _extract_version(_run_cmd(["agy", "--version"], timeout=timeout)),
        "claude": _extract_version(_run_cmd(["claude", "--version"], timeout=timeout)),
        "codex": _extract_version(_run_cmd(["codex", "--version"], timeout=timeout)),
        "cursor-agent": _extract_version(_run_cmd(["cursor-agent", "--version"], timeout=timeout)),
        "models": _get_models(timeout=timeout),
    }


class ClaimsList(list):
    """List of claims with an attached count of skipped archived/historical files."""

    def __init__(self, items=(), skipped=0):
        super().__init__(items)
        self.skipped = skipped


def claims(store, return_skipped=False):
    """Walk */SKILL.md and */references/*.md under store and extract claims.

    Extracts:
    - VERSION claim: tool name within ~40 characters of a dotted version number.
    - SLUG claim: token matching gemini-<digits>(.<digits>)?-(flash|pro)(-(high|medium|low))?.

    Skips files containing 'archiv' or 'historical' in filename/path, or whose
    first 14 lines mark them as archived/previous-host text.
    """
    store = os.path.expanduser(store)
    pattern1 = os.path.join(store, "*/SKILL.md")
    pattern2 = os.path.join(store, "*/references/*.md")
    files = sorted(set(glob.glob(pattern1) + glob.glob(pattern2)))

    skipped = 0
    all_claims = []

    for path in files:
        fname = os.path.basename(path).lower()
        rel = os.path.relpath(path, store)

        if "archiv" in fname or "historical" in fname or "archiv" in rel.lower() or "historical" in rel.lower():
            skipped += 1
            continue

        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.read().splitlines()
        except OSError:
            continue

        head = "\n".join(lines[:14]).lower()
        if any(m in head for m in ARCHIVE_MARKS):
            skipped += 1
            continue
        if is_dated_record(rel, "\n".join(lines[:14])):
            skipped += 1
            continue

        for i, line in enumerate(lines, 1):
            line_claims = []

            # SLUG claims
            slug_matches = list(SLUG_PAT.finditer(line))
            for sm in slug_matches:
                line_claims.append({
                    "file": rel,
                    "line": i,
                    "text": line,
                    "kind": "slug",
                    "claim": sm.group(0),
                })

            # VERSION claims
            tool_matches = []
            for tm in TOOL_PAT.finditer(line):
                raw = tm.group(0)
                # `claude` inside `~/.claude/docs/...` is a directory, not the CLI:
                # it paired with a schema version (`v1.1`) and produced a false claim.
                before = line[max(0, tm.start() - 1):tm.start()]
                after = line[tm.end():tm.end() + 1]
                if before in ("/", ".", "-") or after in ("/", "-"):
                    continue
                norm = re.sub(r"\s+", " ", raw.lower())
                canonical = TOOL_MAP.get(norm, norm)
                tool_matches.append((tm.start(), tm.end(), canonical, raw))

            if tool_matches:
                for vm in VERSION_PAT.finditer(line):
                    # Avoid treating digits inside a model slug as a tool version claim
                    if any(sm.start() <= vm.start() and vm.end() <= sm.end() for sm in slug_matches):
                        continue

                    ver_str = _version_of(vm)
                    if not ver_str:
                        continue
                    gi = next(i for i, g in enumerate(vm.groups(), start=1) if g)
                    v_start, v_end = vm.start(gi), vm.end(gi)
                    # A skill's own frontmatter version is not a tool version.
                    if FRONTMATTER_VERSION.search(line):
                        continue

                    closest_dist = None
                    closest_tool = None
                    for t_start, t_end, canonical, _ in tool_matches:
                        dist = max(0, v_start - t_end) if v_start >= t_end else max(0, t_start - v_end)
                        if closest_dist is None or dist < closest_dist:
                            closest_dist = dist
                            closest_tool = canonical

                    if closest_dist is not None and closest_dist <= 40:
                        line_claims.append({
                            "file": rel,
                            "line": i,
                            "text": line,
                            "kind": "version",
                            "tool": closest_tool,
                            "claim": ver_str,
                        })

            seen = set()
            for c in line_claims:
                key = (c["kind"], c.get("tool"), c["claim"])
                if key not in seen:
                    seen.add(key)
                    all_claims.append(c)

    result = ClaimsList(all_claims, skipped=skipped)
    if return_skipped:
        return result, skipped
    return result


def _version_parts(v):
    if not v or not isinstance(v, str):
        return []
    parts = []
    for p in v.split("."):
        parts.append(int(p) if p.isdigit() else p)
    return parts


def _version_agrees(claimed, installed):
    """Check if claimed version agrees with installed version.

    Only compares parts given in the claim: e.g. claimed '1.2' against
    installed '1.2.7' agrees; claimed '1.2.4' against '1.2.7' disagrees.
    """
    if not claimed or not installed:
        return False
    c_parts = _version_parts(claimed)
    i_parts = _version_parts(installed)
    if not c_parts or not i_parts:
        return False
    if len(c_parts) > len(i_parts):
        return False
    return i_parts[:len(c_parts)] == c_parts


def compare(claims, facts):
    """Return only disagreements between extracted claims and live facts."""
    disagreements = []
    models = facts.get("models")
    models_set = models if isinstance(models, set) else set()

    for c in claims:
        kind = c.get("kind")
        if kind == "version":
            tool = c.get("tool")
            canonical = TOOL_MAP.get(tool.lower(), tool.lower()) if tool else None
            installed = facts.get(canonical) if (canonical and canonical in facts) else facts.get(tool)
            claimed = c.get("claim")

            if installed is None:
                disagreements.append({
                    "file": c.get("file"),
                    "line": c.get("line"),
                    "kind": "not_installed",
                    "tool": tool,
                    "claimed": claimed,
                    "installed": "not installed",
                    "text": c.get("text"),
                })
            elif not _version_agrees(claimed, installed):
                disagreements.append({
                    "file": c.get("file"),
                    "line": c.get("line"),
                    "kind": "version",
                    "tool": tool,
                    "claimed": claimed,
                    "installed": installed,
                    "text": c.get("text"),
                })
        elif kind == "slug":
            slug = c.get("claim")
            if RETIRED_NEARBY.search(c.get("text", "")):
                continue  # the sentence itself records the retirement
            # A base slug is live when the catalog carries an effort-suffixed form of it:
            # `gemini-3.1-pro` is real because `gemini-3.1-pro-high` and `-low` exist.
            live = slug in models_set or any(m.startswith(slug + "-") for m in models_set)
            if not live:
                disagreements.append({
                    "file": c.get("file"),
                    "line": c.get("line"),
                    "kind": "slug",
                    "claimed": slug,
                    "installed": "absent",
                    "text": c.get("text"),
                })

    return disagreements


if __name__ == "__main__":
    store_arg = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/.claude/skills")
    facts_data = live_facts()
    print("Live facts:")
    for k in ("agy", "claude", "codex", "cursor-agent"):
        print(f"  {k}: {facts_data.get(k)}")
    live_models = facts_data.get("models")
    if isinstance(live_models, set):
        print(f"  models: {len(live_models)} slugs")
    else:
        print(f"  models: {live_models}")

    extracted_claims = claims(store_arg)
    print(f"Skipped {extracted_claims.skipped} archived or historical files")

    discrepancies = compare(extracted_claims, facts_data)
    for d in discrepancies:
        if d.get("kind") == "not_installed":
            print(f"{d['file']}:{d['line']}  tool '{d['tool']}' not installed (claims {d['claimed']})")
        else:
            print(f"{d['file']}:{d['line']}  claims {d['claimed']}, installed {d['installed']}")

    print(f"Total: {len(discrepancies)}")
    sys.exit(0)
