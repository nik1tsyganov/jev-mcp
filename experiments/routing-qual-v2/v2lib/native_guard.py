"""Model@effort guard for Oracle-helper slots, backed by frozen catalog copies.

Helper slots name providers and models in Droppy's vocabulary (codex, claude,
antigravity; `opus[1m]`, `claude-opus-5-5`, `gemini-3.8-flash` + effort). Each
slot is normalised to a canonical routing.json member and checked with the v1
catalog_guard rules. Anything unmappable or unknown is unsupported.
"""
from pathlib import Path

from .common import FROZEN_INPUTS, read_json

import catalog_guard  # v1 module, unchanged

HELPER_TO_PROVIDER = {"codex": "openai", "claude": "anthropic", "antigravity": "google"}


class NativeGuard:
    def __init__(self, frozen=FROZEN_INPUTS):
        frozen = Path(frozen)
        self.support = catalog_guard.Support(frozen / "routing.json", frozen / "codex-models_cache.json")
        routing = read_json(frozen / "routing.json")
        self.claude_aliases = {full: short for short, full in (routing.get("claudeModelAliases") or {}).items()}
        self.sources = self.support.sources

    def canonical(self, provider, model, effort):
        canonical_provider = HELPER_TO_PROVIDER.get(provider)
        if canonical_provider is None:
            return None, f"provider-not-in-canonical-catalog:{provider}"
        if not isinstance(model, str) or not model:
            return None, "model-missing"
        name = model.split("[", 1)[0]
        if canonical_provider == "anthropic":
            name = self.claude_aliases.get(name, name)
        if canonical_provider == "google" and name not in self.support.models and isinstance(effort, str):
            name = f"{name}-{effort.removeprefix('fused-')}"
        return {"model": name, "provider": canonical_provider, "effort": effort}, None

    def check_slot(self, provider, model, effort):
        member, reason = self.canonical(provider, model, effort)
        if member is None:
            return False, reason
        ok, reason, _ = self.support.check(member)
        return ok, reason

    def variant_failures(self, variant):
        if not isinstance(variant, dict):
            return ["variant-missing"]
        slots = [(variant.get("leadProvider"), variant.get("leadModel"), variant.get("leadEffort"))]
        for head in [variant.get("defaultHead"), *(variant.get("profiles") or [])]:
            if isinstance(head, dict):
                slots.append((head.get("provider"), head.get("model"), head.get("effort")))
        failures = []
        for slot in slots:
            ok, reason = self.check_slot(*slot)
            if not ok:
                failures.append(reason)
        return failures

    def filter_providers(self, providers):
        """Drop unsupported model@effort facts so the helper treats them as ineligible."""
        kept, removed = [], []
        for fact in providers:
            fact = dict(fact)
            models = {}
            for model, info in (fact.get("models") or {}).items():
                efforts = [e for e in info.get("efforts", []) if self.check_slot(fact.get("provider"), model, e)[0]]
                dropped = [e for e in info.get("efforts", []) if e not in efforts]
                if dropped:
                    removed.append({"provider": fact.get("provider"), "model": model, "efforts": dropped})
                if efforts:
                    models[model] = {**info, "efforts": efforts}
            fact["models"] = models
            kept.append(fact)
        return kept, removed
