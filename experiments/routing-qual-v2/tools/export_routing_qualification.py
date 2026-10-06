#!/usr/bin/env python3
"""Export the completed v8 qualification without applying settings or invoking providers."""

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
from datetime import datetime, timedelta, timezone
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
SCRATCH = Path.home() / ".local/scratch"
QUAL = SCRATCH / "routing-qual-v2"
CHECKOUT = SCRATCH / "droppy-oracle-cli-integration"
ADAPTER = CHECKOUT / "build.noindex/integration-oracle/adapter"
CONTRACTS = ROOT.parents[2] / "conclave/contracts"
DEFAULT_OUT = QUAL / "export-v8/droppy-app-routing-export.json"
CONCLAVE_OUT = QUAL / "export-v8/conclave-export.json"


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def file_digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def import_path(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def exclusive_write(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.write(raw)


def conclave_export(module, now):
    captured = {}

    # The adapter also writes an audit report. Capture both writes in memory so
    # only the explicitly requested raw export reaches disk, with O_EXCL and 0600.
    class CapturePath(type(Path())):
        def write_text(self, data, *args, **kwargs):
            if self not in (CONCLAVE_OUT, CONCLAVE_OUT.with_suffix(".report.json")):
                raise ValueError("unexpected Conclave output: " + str(self))
            captured[Path(self)] = data
            return len(data)

    previous_argv, previous_path = sys.argv, module.Path
    try:
        module.Path = CapturePath
        sys.argv = [str(ADAPTER / "conclave_export.py"),
                    "--matrix", str(CONTRACTS / "dispatch-matrix.json"),
                    "--seat-profiles", str(CONTRACTS / "seat-profiles.json"),
                    "--now", now, "--out", str(CONCLAVE_OUT)]
        module.main()
    finally:
        sys.argv, module.Path = previous_argv, previous_path
    raw = captured[CONCLAVE_OUT].encode("utf-8")
    exported = json.loads(raw)
    if set(exported) != {"conclaveClasses", "candidates", "bindings", "matrixVersion"}:
        raise ValueError("unexpected Conclave export fields")
    return raw, exported


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--conclave-export", type=Path,
                        help="conclave-export.json from the probe pipeline; without it seats stay unqualified")
    args = parser.parse_args()
    out = args.out.expanduser().absolute()
    readme = out.parent / "README.md"
    targets = (out, readme) if args.conclave_export else (out, CONCLAVE_OUT, readme)
    if len(set(targets)) != len(targets):
        raise ValueError("output paths must be distinct")
    for path in targets:
        if os.path.lexists(path):
            raise FileExistsError("refusing to overwrite " + str(path))

    freeze_raw = (ROOT / "FROZEN-v8.json").read_bytes()
    freeze = json.loads(freeze_raw)
    hashes = freeze["hashes"]
    if not isinstance(hashes, dict) or not hashes:
        raise ValueError("freeze must contain file hashes")
    for name, expected in hashes.items():
        path = Path(name).expanduser()
        if not path.is_absolute():
            path = ROOT / path
        if file_digest(path) != expected:
            raise ValueError("frozen hash mismatch: " + name)

    verdict_raw = (QUAL / "runs-v8/heldout-owner-verdict.json").read_bytes()
    jev = json.loads(verdict_raw)["jev"]
    historical = jev["historical_gate"]
    if (jev.get("final") != "QUALIFIED" or jev.get("failed") != []
            or historical.get("failed") != []
            or historical.get("status") != "qualified"
            or not jev.get("checks")
            or any(value is not True for value in jev["checks"].values())):
        raise ValueError("Jev verdict is not qualified without failures")
    modes = historical["exportable_modes"]
    if (not isinstance(modes, list) or not modes
            or any(mode not in ("hydraOracle", "experimentalOracle", "conclave") for mode in modes)
            or len(set(modes)) != len(modes)):
        raise ValueError("invalid exportable modes")

    # Imported input modules must remain read-only, including their directories.
    sys.dont_write_bytecode = True
    snapshot = import_path("qualification_oracle_snapshot", QUAL / "frozen-inputs-r3/oracle_snapshot.py")
    conclave = import_path("qualification_conclave_export", ADAPTER / "conclave_export.py")
    now = datetime.now(timezone.utc).replace(microsecond=0)
    pairs = snapshot.saved_from_app("iordv.droppycode.dev")
    if not isinstance(pairs, list):
        raise ValueError("saved pairs must be a JSON array")
    candidates = [snapshot.from_saved(pair) for pair in pairs]
    helper_cap = max((c["variant"]["maxHeads"] for c in candidates
                      if c["variant"].get("maxHeads") is not None), default=0)
    rows, version = snapshot.evidence_file(ADAPTER / "routing-evidence.json")
    bindings = []
    for priority, candidate in enumerate(candidates, 1):
        families, expiry = snapshot.qualifying_domains(snapshot.sides(candidate), rows, now)
        bindings.append({"kind": "savedPair", "candidateID": candidate["id"],
                         "revision": candidate["revision"], "configuration": candidate["variant"],
                         "families": families, "requiredRoles": [], "priority": priority,
                         "evidenceVersion": version, "validUntil": snapshot.iso(expiry),
                         "qualified": bool(families)})
    compositions = []
    if "experimentalOracle" in modes:
        for lead in candidates:
            for head in candidates:
                a, b = lead["variant"].get("maxHeads"), head["variant"].get("maxHeads")
                if a is None or b is None:
                    continue
                families, expiry = snapshot.qualifying_domains(
                    snapshot.sides(lead, heads=False) + snapshot.sides(head, lead=False), rows, now)
                if not families:
                    continue
                priority = len(compositions) + 1
                compositions.append({"id": "composition:" + lead["id"] + ":" + head["id"],
                    "leadCandidateID": lead["id"], "headCandidateID": head["id"],
                    "helperCount": min(helper_cap, a, b), "families": families,
                    "requiredRoles": [], "purpose": lead["variant"]["purpose"], "priority": priority,
                    "evidenceVersion": version, "validUntil": snapshot.iso(expiry)})
                if len(compositions) == 32:
                    break
            if len(compositions) == 32:
                break
    matrix_version = "saved-pairs:" + digest(snapshot.swift_json(
        {"candidates": candidates, "bindings": bindings}))[:16]
    if args.conclave_export:
        conclave_raw = args.conclave_export.expanduser().read_bytes()
        exported = json.loads(conclave_raw)
    else:
        conclave_raw, exported = conclave_export(conclave, snapshot.iso(now))
    # Seat proof expires (probe start + 60 minutes); keep a seat only while its proof and contract are current.
    seats = []
    for binding in exported["bindings"]:
        contract = binding.get("conclave") or {}
        if binding.get("qualified") is True:
            if not (contract.get("validated") is True and contract.get("nativeEvidenceVersion")):
                binding["qualified"] = False
            else:
                expiry = min(snapshot.utc(binding["validUntil"]), snapshot.utc(contract["validUntil"]))
                if expiry <= now:
                    binding["qualified"] = False
                else:
                    binding["validUntil"] = contract["validUntil"] = snapshot.iso(expiry)
        seats.append(binding)
    classes = {}
    if "conclave" in modes:
        bindings += seats
        classes = exported["conclaveClasses"]
        matrix_version = exported["matrixVersion"]

    frozen_matrix_raw = (QUAL / "frozen-inputs-r3/dispatch-matrix.json").read_bytes()
    live_matrix_raw = (CONTRACTS / "dispatch-matrix.json").read_bytes()
    frozen_classes = {key: spec["title"] for key, spec in json.loads(frozen_matrix_raw)["classes"].items()}
    live_classes = {key: spec["title"] for key, spec in json.loads(live_matrix_raw)["classes"].items()}
    if frozen_classes != live_classes or exported["conclaveClasses"] != live_classes:
        raise ValueError("Conclave class titles differ from the frozen request")
    manifest = json.loads((SCRATCH / "oracle-bundles/debug-signed-c2168378d3512c03/manifest.json").read_bytes())
    freeze_hash = digest(freeze_raw)
    entries = [{"caller": "droppy-app", "backend": "jev", "model": "jev-1.13.0",
                "capability": "oracle-classification-policy-v1",
                "evidenceVersion": "FROZEN-v8.json sha256:" + freeze_hash,
                "validUntil": snapshot.iso(now + timedelta(days=30)), "threshold": 0.8,
                "qualified": True, "preservesExactState": True, "mode": mode} for mode in modes]
    # Export only modes with something eligible; a mode with nothing to route would abstain on every task.
    live_seats = [b for b in seats if b["qualified"]]
    has_route = {"hydraOracle": any(b["qualified"] for b in bindings if b["kind"] == "savedPair"),
                 "experimentalOracle": bool(compositions), "conclave": bool(live_seats)}
    entries = [entry for entry in entries if has_route[entry["mode"]]]
    for entry in entries:
        if entry["mode"] == "conclave":
            entry["validUntil"] = snapshot.iso(min(snapshot.utc(b["validUntil"]) for b in live_seats))
    if not entries:
        raise SystemExit("refusing: no mode has a qualified saved pair, composition or seat")
    result = {"schema": "oracle-routing-qualification-export-v1", "exportID": str(uuid4()).upper(),
              "issuedAt": snapshot.iso(now), "entries": entries,
              "policy": {"matrixVersion": matrix_version, "bindings": bindings,
                         "compositions": compositions, "conclaveClasses": classes, "helperCap": helper_cap},
              "evidence": {"freezeSHA256": freeze_hash, "verdictSHA256": digest(verdict_raw),
                           "adjudicationSHA256": file_digest(QUAL / "sealed/adjudication-v5/ADJUDICATION-LOG-heldout-v5.json"),
                           "helperBundleTreeSHA256": manifest["bundle"]["treeSHA256"],
                           "corpusSHA256": file_digest(ROOT / "cases/v5/heldout.jsonl"),
                           "summary": "v8 Jev QUALIFIED with no failures; all frozen file hashes match; "
                           "Conclave class titles unchanged; "
                           + ("Conclave seats from probe pipeline export sha256:" + digest(conclave_raw) + "; "
                              if args.conclave_export else "no native probe evidence; ")
                           + "modes exported: " + ", ".join(e["mode"] for e in entries) + "; "
                           "frozen matrix sha256:" + digest(frozen_matrix_raw)
                           + "; live matrix sha256:" + digest(live_matrix_raw)}}
    # An export with nothing eligible would switch routing on and then abstain on every task.
    usable = [binding for binding in bindings if binding["qualified"]]
    if not usable and not compositions:
        raise SystemExit("refusing: no qualified saved-pair binding, seat or composition; "
                         "routing-evidence.json has no current 'qualified' rows for these configurations")
    # The app accepts at most 32 bindings; unqualified rows carry no routing value, so keep qualified ones.
    if len(bindings) > 32:
        result["policy"]["bindings"] = usable[:32]
    # Custom Codable exposes arrays, not the internal entriesData/bindingsData storage.
    raw = snapshot.swift_json(result) + b"\n"
    readme_raw = ("# Routing qualification export\n\n"
                  "Applying this export is an owner action in Dev Settings.\n"
                  "This export authorizes no spending.\n"
                  "The generator does not apply app settings or run provider requests.\n"
                  "Qualification entries do not qualify individual saved pairs or Conclave seats.\n").encode("utf-8")
    if not args.conclave_export:
        exclusive_write(CONCLAVE_OUT, conclave_raw)
    exclusive_write(readme, readme_raw)
    exclusive_write(out, raw)
    print("export:", out)
    print("sha256:", digest(raw))
    print("modes:", ", ".join(modes))
    names = {candidate["id"]: candidate["displayName"] for candidate in candidates}
    for kind in ("savedPair", "qualifiedSeat"):
        selected = [binding for binding in bindings if binding["kind"] == kind]
        qualified = [binding for binding in selected if binding["qualified"]]
        print(f"{kind}: {len(qualified)} qualified, {len(selected) - len(qualified)} not qualified")
        for binding in qualified:
            print("qualified:", names.get(binding["candidateID"], binding["candidateID"]),
                  binding["candidateID"], "families=" + ",".join(binding["families"]))
    print("compositions:", len(compositions))
    print("helperCap:", helper_cap)
    if len(bindings) > 32:
        print("caveat: combined bindings exceed the consumer's 32-binding input limit")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise SystemExit("export_routing_qualification: " + str(error)) from error
