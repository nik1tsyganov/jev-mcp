"""Model@effort eligibility guard against the canonical catalogs (post-v1 addition).

The frozen v1 policy trusts the caller's snapshot for model/effort support, so a
snapshot can fabricate a combination. This guard removes every candidate whose
lead, head or checker is not a supported model@effort before the v1 policy runs,
then re-checks the emitted route. Unknown is unsupported; with nothing left the
route abstains. policy.py and the v1 freeze are not changed.

Support rules:
- The model must be listed for its vendor in routing.json (claudeModels,
  codexModels plus codexReviewModel, geminiModels). routing.json is the canonical
  dispatch catalog; aliases and dispatch-row-only names are not listed models.
- anthropic: effort in routing.json efforts.claude.
- openai: effort in the Codex vendor-native cache (~/.codex/models_cache.json,
  supported_reasoning_levels) and, when routing.json efforts.codexByModel has an
  entry for the model, also in that entry (intersection). A model with neither
  source is unsupported.
- google: effort is fused into the slug; an explicit effort must equal the slug
  suffix ('fused', 'fused-<x>' and an absent effort resolve to the suffix).
- Any other provider (including cognition) is unsupported: the canonical catalog
  lists no such models.
"""
import hashlib
import json
from copy import deepcopy
from pathlib import Path

import policy

GUARD_VERSION = "catalog-guard-v1"
VENDOR_PROVIDER = {"claude": "anthropic", "codex": "openai", "gemini": "google"}
DEFAULT_ROUTING = Path.home() / "Documents/Agent-Vault/Skills/mix-mode/references/routing.json"
DEFAULT_CODEX_CACHE = Path.home() / ".codex/models_cache.json"


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class Support:
    def __init__(self, routing_path=DEFAULT_ROUTING, codex_cache_path=DEFAULT_CODEX_CACHE):
        routing = json.loads(Path(routing_path).read_text(encoding="utf-8"))
        self.sources = {"routing_json": {"sha256": _sha(routing_path),
                                         "updated": (routing.get("_meta") or {}).get("updated")}}
        self.models = {}
        for name in routing.get("claudeModels", []):
            self.models[name] = ("anthropic", set(routing["efforts"]["claude"]), "routing.efforts.claude")
        by_model = routing["efforts"].get("codexByModel", {})
        cache = {}
        try:
            data = json.loads(Path(codex_cache_path).read_text(encoding="utf-8"))
            for row in data.get("models", []):
                slug = row.get("slug") or row.get("id") or row.get("model")
                levels = {level.get("effort") for level in row.get("supported_reasoning_levels", [])}
                if slug and levels:
                    cache[slug] = levels
            self.sources["codex_cache"] = {"sha256": _sha(codex_cache_path), "fetched_at": data.get("fetched_at")}
        except (OSError, ValueError):
            self.sources["codex_cache"] = None
        for name in [*routing.get("codexModels", []), routing.get("codexReviewModel")]:
            if not name:
                continue
            native, listed = cache.get(name), by_model.get(name)
            if native is not None and listed is not None:
                efforts, source = native & set(listed), "codex-cache ∩ routing.codexByModel"
            elif native is not None:
                efforts, source = native, "codex-cache"
            elif listed is not None:
                efforts, source = set(listed), "routing.codexByModel"
            else:
                efforts, source = set(), "no-effort-source"
            self.models[name] = ("openai", efforts, source)
        for name in routing.get("geminiModels", []):
            suffix = name.rsplit("-", 1)[-1]
            self.models[name] = ("google", {suffix} if suffix in ("low", "medium", "high") else set(), "slug-fused")

    def check(self, member):
        """Return (supported, reason, source) for {model, provider, effort}."""
        if not isinstance(member, dict):
            return False, "member-missing", None
        model, provider = member.get("model"), member.get("provider")
        entry = self.models.get(model)
        if entry is None:
            return False, f"model-not-in-canonical-catalog:{model}", None
        listed_provider, efforts, source = entry
        if provider != listed_provider:
            return False, f"provider-mismatch:{model}:{provider}", source
        effort = member.get("effort")
        if listed_provider == "google":
            suffix = next(iter(efforts), None)
            if effort is None or effort == "fused" or (isinstance(effort, str) and effort.startswith("fused ")):
                effort = suffix  # the slug carries the effort
            elif isinstance(effort, str) and effort.startswith("fused-"):
                effort = effort.removeprefix("fused-")
        if not isinstance(effort, str) or effort not in efforts:
            return False, f"effort-unsupported:{model}@{effort}", source
        return True, "supported", source

    def candidate_failures(self, candidate):
        members = [candidate.get("lead"), candidate.get("head"), *candidate.get("checkers", [])]
        return [reason for member in members if member is not None
                for ok, reason, _ in [self.check(member)] if not ok]


def guard_case(case, support):
    """Copy of case without unsupported candidates, and {id: [reasons]} for removed ones."""
    guarded = deepcopy(case)
    removed = {}
    kept = []
    for candidate in guarded["snapshot"]["candidates"]:
        failures = support.candidate_failures(candidate)
        if failures:
            removed[candidate["id"]] = failures
        else:
            kept.append(candidate)
    guarded["snapshot"]["candidates"] = kept
    if guarded["snapshot"].get("current_candidate_id") in removed:
        guarded["snapshot"].pop("current_candidate_id")
    return guarded, removed


def guarded_route(case, answers, rule, backend_info, support):
    guarded, removed = guard_case(case, support)
    route = policy.route(guarded, answers, rule, backend_info)
    if removed:
        route["reasons"].append("catalog-unsupported:" + ",".join(sorted(removed)))
    # Defence in depth: never emit a member the guard does not support.
    members = [route.get("lead"), route.get("heads"), *(route.get("checkers") or [])]
    if any(member is not None and not support.check(member)[0] for member in members):
        abstained = policy.route_from_error(guarded, "catalog-guard-violation", rule, backend_info)
        abstained["outcome"] = "abstain"
        route = abstained
    route["provenance"]["catalog_guard"] = {"version": GUARD_VERSION, "sources": support.sources,
                                            "removed": removed}
    return route
