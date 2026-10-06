# Prior evidence inventory

Read-only source inventory, 2026-10-01. No model, API, build, test, or scorer was run. Hashes below were recomputed from source bytes. Results remain recorded historical evidence, not rerun results.

## Source notation

All short source citations below expand through this table. Paths inside jev-mcp are repository-relative.

| Prefix | Location |
| --- | --- |
| V2 | `~/.local/scratch/jev-shadow-v2-20261001` |
| V1 | `~/.local/scratch/jev-shadow-pilot-20261001` |
| LC | `~/.local/scratch/local-classifier-pilot-20261001` |
| LY | `~/.local/scratch/laya-comparison-20261001` |
| LR | `~/.local/scratch/laya-requal-2026-09-30` |
| OW | `~/.local/scratch/droppy-code-oracle-wt` |
| OQ | `OW/docs/hydra-oracle/qualification` |

## What each experiment measured

### Jev shadow v2

**Task:** context-deletion safety and batching, not routing or pair choice. Six synthetic development cases tested answers, sufficiency, and 12 independent evidence-coverage judgments per case. The protocol capped the run at 36 logical requests, with one attempt each. Held-out calls were zero. [V2/preregistered-protocol.json:2-7,18-33]

**Rule:** Choice acceptance requires selected probability ≥0.8. Noul acceptance requires ≥0.8 for positive or ≤0.2 for negative. Hiding requires needed probability <0.1 and the global keep guard. All six cases must pass answer, sufficiency, coverage, retention, and recall checks. Filtration benefit additionally requires fewer tokens and lower one-use cost. [V2/preregistered-protocol.json:19-33]

**Recorded outcome:** `DEVELOPMENT_RUBRIC_FAIL`; 36 requests, 4/6 full-case acceptance, 5/6 accepted answers, 4/6 accepted sufficiency judgments, and 72/72 coverage judgments matching gold. Held-out evidence remained untouched. [V2/live-results/results.json:676-703; LC/final-comparison.json:14-30]

Batching used 23,661 input tokens versus 57,249 across three groups: 58.7% fewer. This compares answer, sufficiency, and coverage groups against one 14-question batch. It does not compare 14 singleton calls. Every filter kept everything. Filter-plus-shadow used 44,726 input tokens, versus 23,661 without filtering. Thus batching showed savings; context deletion showed no reduction. [V2/preregistered-protocol.json:27-33; V2/live-results/results.json:90-99,202-211,314-323,426-435,538-547,650-659; LC/final-comparison.json:27]

**Does not show:** routing quality, model/effort/pair selection, calibrated probabilities, held-out generalization, production safety, or context-reduction benefit.

### Laya short-input comparison and contended diagnostic

**Task:** context-evidence classification plus runtime functionality. The idle benchmark planned 84 unique judgments across six cases plus one repeat. It remained `BLOCKED_PENDING_RESOURCES`. [LY/idle-benchmark-status.json:2-18]

**Protocols:** `shortening-rule-addendum.json`, `run_laya.mjs`, and `contended-diagnostic/preregistration.json`. Original full inputs exceeded the 1024-token budget in all 84 requests. Shortening retained all 12 events, removed metadata fields, and collapsed repeated filler sentences. It produced 896–984-token requests. The addendum corrects the manifest's accidental token-audit docstring. This is a materially different input experiment. [LY/shortening-rule-addendum.json:2-25]

**Diagnostic sample/rule:** one shortened case; 14 unique judgments plus one identical-input repeat, 15 calls total. Stage advancement required valid output, matching identity, GPU float16, monitoring, and resource limits. Quality was not a preregistered gate. [LY/contended-diagnostic/preregistration.json:13-24,143-179,208-211]

**Recorded outcome:** 15 valid calls. Later offline scoring found answer 0/1, sufficiency 0/1, evidence coverage 9/12, TP=0, FP=1, TN=9, FN=2. Both required evidence items would be dropped by binary argmax. No content was actually removed. Scoring used top choice and Noul >0.5/<0.5, with ties abstaining; it was a later development extension. [LY/contended-diagnostic/diagnostic-report.json:5-26; LY/contended-diagnostic/offline-scoring/REPORT.md:3-30]

**Overstatement:** “No ... memory breach” and “Stage-2 criteria all true” do not establish loaded-model footprint compliance. The only footprint sample preceded model loading. The report itself identifies this gap. [LY/contended-diagnostic/diagnostic-report.json:5,15-19; LY/contended-diagnostic/offline-scoring/REPORT.md:34-39]

**Does not show:** a passed idle benchmark, comparative latency, full-context capability, useful routing accuracy, or general determinism. This diagnostic neither qualifies nor rejects Laya as a pair selector. Fifteen calls are not fifteen independent cases.

### Qwen/Decider local classifier pilot

**Task:** evidence ranking and typed answer/sufficiency/coverage classification, not routing. Protocol: `LC/evaluation-protocol.json`; download manifest: `LC/download-plan.json`. Six shared development cases; Qwen CPU made 72 query-event judgments; Decider CPU made 84 typed judgments. MPS quality and latency were not measured. No holdout or calibration fit was used. [LC/evaluation-protocol.json:16-43; LC/final-comparison.json:32-66,123-130]

**Rule:** Qwen uses final-token yes/no logit softmax, then recall@k, reciprocal rank, and ordering metrics. Decider uses specialized letter logits and shipped temperatures, with forced Choice top label and Noul argmax. No action threshold was qualified. [LC/evaluation-protocol.json:32-43]

**Recorded outcome:** Qwen recall@1/2/3 = 0.50/0.75/0.8333; MRR=0.7667; ordering accuracy=0.8470. Required missing-information evidence ranked tenth. Decider answers=6/6, sufficiency=5/6, coverage=71/72, required-evidence recall=8/9. One necessary preservation fact was missed. [LC/final-comparison.json:32-66]

**Does not show:** a fair backend ranking. Qwen saw one event plus query; Jev and Decider saw full state. Jev's acceptance/abstention rule differed from Decider's forced argmax. CPU singleton latency differs from remote batched latency. The pilot supports neither calibrated deletion nor routing qualification. Recorded arm `PASS` means execution completed, not quality acceptance. [LC/results.json:9-13; LC/final-comparison.json:123-132]

### Laya requalification, 2026-09-30

**Task:** Hydra pair selection with manual keep-current fallback. This is routing evidence, unlike the context-deletion experiments. `LR/run.sh` records four variants over dev and holdout. Each variant directory retains its copied `prereg.json`, corpus, labels, and results. [LR/run.sh:2-18]

The rescore chooses a threshold on dev, minimizing loss, then scores holdout once. An abstained or invalid choice uses the manual row's loss. Losses are acceptable=0, abstain=0.5, eligible-but-unacceptable=1. [LR/tools/rescore_keep_current.py:18-42; OQ/prereg.json:34-38]

Each variant has 40 dev and 80 holdout rows. Manual keep-current regret is 0.425 dev and 0.350 holdout. The reference is recorded in `OQ/results/summary.json:637-646`; `LR/summary.json` repeats the holdout reference per variant. Direct arithmetic on each variant’s `results/manualDefault-dev.json:4` and `results/manualDefault-holdout.json:4` confirms .425/.350 using `LR/tools/score.py:85-112`. No scorer module was executed. The following top-pick and threshold values are recorded, not a fresh scorer run.

| Variant | Runtime/model source in run.sh | Manual regret dev / holdout | Top-pick regret dev / holdout | Chosen threshold | Threshold regret dev / holdout | Threshold picks dev / holdout | Correct picks dev / holdout | Source |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| v0-current | existing evaluation venv + existing HF home | .425 / .350 | .6000 / .4875 | .50 | .3500 / .3500 | 6 / 0 | 6 / 0 | LR/summary.json:3-48 |
| v1-runtime020 | venv020 + existing HF home | .425 / .350 | .6000 / .4875 | .50 | .3500 / .3500 | 6 / 0 | 6 / 0 | LR/summary.json:51-96 |
| v2-typed | venv020 + hf-typed | .425 / .350 | .5750 / .5563 | .30 | .3500 / .3500 | 11 / 0 | 9 / 0 | LR/summary.json:99-144 |
| v3-multilingual | venv020 + hf-multi | .425 / .350 | .4500 / .4562 | .35 | .3875 / .3875 | 3 / 6 | 3 / 0 | LR/summary.json:147-192 |

Every top-pick holdout regret exceeds manual regret. Three threshold variants make zero holdout picks and equal manual performance through fallback. Multilingual makes six incorrect holdout picks and worsens regret. This does not establish useful pair-choice improvement, calibrated probabilities, or the new 14-class routing policy. Variant names alone do not prove installed runtime versions. Historical dev/holdout rows reused here are not a new independent held-out qualification.

### Jev shadow pilot v1

**Task:** context-deletion safety and batching. No standalone preregistration JSON was found at the root. The frozen contract is in `V1/harness.py`, `V1/live_pilot.py`, and the recorded live directory's `authorization-and-runtime.json`. Corpus/gold hashes are fixed in `harness.py:18-20`; six-call rounds are defined at `harness.py:368-410`.

**Sample/rule:** six development cases planned; one completed. Six judgment requests plus one model-list request, no retries, zero held-out calls. Acceptance required Choice ≥0.8 and Noul ≥0.8/≤0.2; hiding <0.1 and global keep ≥0.1. Any case failure stopped extension. [V1/live-approved-Sentinel_cdbbf2b01e848191b8a7af343da340fa/measured-results.json:2-10,42-50]

**Recorded outcome:** `STOPPED_AT_FROZEN_ABSTENTION_GATE`. Original and shadow bytes both 7,312. Filter status was passthrough. The first sufficiency score was .68, and the selected source probability was .51, below acceptance. Singleton input tokens=9,221; batch=3,555; filter-plus-shadow=7,095. [V1/live-approved-Sentinel_cdbbf2b01e848191b8a7af343da340fa/measured-results.json:11-49,65-90]

**Does not show:** six-case success, held-out performance, context reduction, or routing quality. V2 changed the coverage question formulation and one gold interpretation; it must remain a separate experiment. [V2/preregistered-protocol.json:18,26]

### Oracle qualification

**Task:** candidate/Hydra pair choice using task family, scope, role needs, and candidate descriptions. Protocol: `OQ/prereg.json`. Corpus version `2026-09-23.1` has 120 rows and eight catalogs. Labels map each row ID to `acceptable`, `family`, and `note`. [OQ/corpus.json:1-8,2440-2457; OQ/labels.json:1-10]

**Sample/rule:** 40 dev + 80 holdout, with 40 repeated holdout rows planned for noise estimation. A dev-chosen threshold must achieve zero violations, holdout abstention ≤.35, p95 latency ≤3,000 ms Jev /1,500 ms Laya, and regret better than every baseline by more than noise. [OQ/prereg.json:19,25-38,39-94]

**Recorded outcome:** summary reports 143 live Jev calls. Jev is `qualified`: threshold=.55, holdout regret=.1812, abstention=.25, 48 commits, noise=.075, p95=2401.8364 ms, zero violations. Laya is `fail`: threshold=.50, holdout regret=.475, abstention=.825, zero commits, p95=165.5492 ms. Failure reasons include no dev threshold meeting abstention, holdout abstention, and regret not below manual. Baseline holdout regrets are manual=.35, keyword=.65, capability-only=.70. [OQ/results/summary.json:2,222-270,488-541,637-649; OQ/results/summary.json:104-108,372-376]

Jev's 120-row denominator includes 12 excluded, 4 invalid, 21 abstained, and 83 valid rows. Laya includes 12 excluded, 3 invalid, 2 errors, 12 abstained, and 91 valid rows. These categories precede threshold scoring; they are not the committed denominator. [OQ/results/summary.json:224-230,490-498]

**Does not show:** qualification of the newer classification-to-policy helper, 14-class routing, effort prediction, new pair catalog quality, or dynamic composition. Laya's fallback can remove candidates from state or split pair selection into candidate-level questions. It therefore does not certify exact-state transport. [OQ/prereg.json:23; OW/docs/hydra-oracle/ROUTING-HELPER.md:26-28,81-87]

The GUI's `qualified: true` for owner-permitted Laya is explicitly not a passed holdout. “Qualified” cannot be transferred from permission records to benchmark quality. Current pair documentation explicitly says no complete pair was benchmarked against another. [OW/docs/hydra-oracle/VALIDATION.md:285-290; OW/docs/hydra-pairs-2026-09-29.json:13-16]

## Versions and hardware

“Verified” below means a local file or read-only command established the fact. It does not establish runtime execution.

| Item | Status and observed fact | Source |
| --- | --- | --- |
| Laya default profile | Verified: `technical-bookmark-topic-v2`, checkpoint `aac6fef/laya-typed-decisions-mlx`, revision `28416e78cb26a239a4eabaa2e084904ec5e6cacb`; qualification status FAILED, enabled through owner override | config/decision-profiles.json:3,33-58 |
| Laya cache refs/main | NOT FOUND at `~/.cache/huggingface/hub/models--aac6fef--laya-typed-decisions-mlx/refs/main`; refs directory absent | read-only directory listing, 2026-10-01 |
| Laya cache snapshots | Verified: one directory, `28416e78cb26a239a4eabaa2e084904ec5e6cacb`; required revision PRESENT | same cache, snapshots directory listing |
| Snapshot contents | Verified: `encoder/`, `tokenizer/`, `mlx_config.json`, `rl_agent_config.json`, `model.safetensors`; model/config files are cache-blob symlinks | snapshot directory listing |
| Configured interpreter | Verified: `~/.local/scratch/laya-evaluation/venv/bin/python`, CPython 3.12.13 | config/decision-profiles.json:49-51; ~/.config/machine-paths/paths.ini:116-121; ~/.local/scratch/laya-evaluation/venv/pyvenv.cfg:1-5 |
| Configured HF home | Verified: `~/.local/scratch/laya-evaluation/hf`; distinct from the requested default Hugging Face cache | ~/.config/machine-paths/paths.ini:121 |
| Laya worker library/backend | Verified: imports `laya_mlx`, loads local path on GPU with float16; refuses missing or mismatched revision | tools/laya_worker.py:85-116,167-179 |
| Laya packages | Verified from installed METADATA: `laya-mlx` 0.1.0, `laya` 0.3.4, `mlx` 0.32.2, `mlx-metal` 0.32.2 | ~/.local/scratch/laya-evaluation/venv/lib/python3.12/site-packages/{laya_mlx-0.1.0,laya-0.3.4,mlx-0.32.2,mlx_metal-0.32.2}.dist-info/METADATA:2-3 |
| mlx-lm | NOT FOUND in the configured Laya venv's installed package metadata. The worker uses `laya_mlx`; no mlx-lm version can be asserted | same site-packages listing; tools/laya_worker.py:170-178 |
| Qwen model | Verified manifest ID `Qwen/Qwen3-Reranker-0.6B`, revision `e61197ed45024b0ed8a2d74b80b4d909f1255473`; local files enumerated below | LC/download-plan.json:294-363; LC/evaluation-protocol.json:12-14 |
| Decider model | Verified manifest ID `Mapika/decider-2b`, revision `533964dae8be954c5b5e19fa4948e48408094c1e`; local config `version: 2b-v11` | LC/download-plan.json:365-419; LC/models/decider/decider_config.json:9-18 |
| Local pilot interpreter | Verified recorded CPython 3.12.13 | LC/venv/pyvenv.cfg:1-6; LC/download-plan.json:4 |
| pip inventory | NOT AVAILABLE: both requested venv `python -m pip list --format json` calls returned `No module named pip`. No installation attempted. Installed metadata inventory follows | read-only command output, 2026-10-01 |
| Memory | Verified `sysctl hw.memsize`: 68,719,476,736 bytes = 64 GiB | read-only sysctl, 2026-10-01 |
| CPU | Verified `sysctl machdep.cpu.brand_string`: Apple M5 Max | read-only sysctl, 2026-10-01 |

Oracle's source pins a different Laya identity: `aac6fef/laya-mlx`, revision `047678560251f28113ee8f5df4be82102c7bf336`, response tag `laya-mlx-0476785`. Do not conflate it with the Jev-MCP typed checkpoint. [OW/DroppyCode/Core/Models/HydraOracle.swift:316-320]

### Installed local-pilot package metadata

All entries are VERIFIED from local `METADATA`, without imports. They are not pip output.

| Package | Version | Source |
| --- | --- | --- |
| annotated-doc | 0.0.5 | LC/venv/lib/python3.12/site-packages/annotated_doc-0.0.5.dist-info/METADATA:2-3 |
| anyio | 4.15.1 | LC/venv/lib/python3.12/site-packages/anyio-4.15.1.dist-info/METADATA:2-3 |
| certifi | 2026.7.22 | LC/venv/lib/python3.12/site-packages/certifi-2026.7.22.dist-info/METADATA:2-3 |
| decider-ai | 1.8.0 | LC/venv/lib/python3.12/site-packages/decider_ai-1.8.0.dist-info/METADATA:2-3 |
| einops | 0.8.2 | LC/venv/lib/python3.12/site-packages/einops-0.8.2.dist-info/METADATA:2-3 |
| filelock | 4.0.8 | LC/venv/lib/python3.12/site-packages/filelock-4.0.8.dist-info/METADATA:2-3 |
| fla-core | 0.5.2 | LC/venv/lib/python3.12/site-packages/fla_core-0.5.2.dist-info/METADATA:2-3 |
| flash-linear-attention | 0.5.2 | LC/venv/lib/python3.12/site-packages/flash_linear_attention-0.5.2.dist-info/METADATA:2-3 |
| fsspec | 2026.9.0 | LC/venv/lib/python3.12/site-packages/fsspec-2026.9.0.dist-info/METADATA:2-3 |
| h11 | 0.16.0 | LC/venv/lib/python3.12/site-packages/h11-0.16.0.dist-info/METADATA:2-3 |
| hf-xet | 1.6.0 | LC/venv/lib/python3.12/site-packages/hf_xet-1.6.0.dist-info/METADATA:2-3 |
| httpcore | 1.0.9 | LC/venv/lib/python3.12/site-packages/httpcore-1.0.9.dist-info/METADATA:2-3 |
| httpx | 0.28.1 | LC/venv/lib/python3.12/site-packages/httpx-0.28.1.dist-info/METADATA:2-3 |
| huggingface_hub | 1.5.0 | LC/venv/lib/python3.12/site-packages/huggingface_hub-1.5.0.dist-info/METADATA:2-3 |
| idna | 3.20 | LC/venv/lib/python3.12/site-packages/idna-3.20.dist-info/METADATA:2-3 |
| Jinja2 | 3.1.6 | LC/venv/lib/python3.12/site-packages/jinja2-3.1.6.dist-info/METADATA:2-3 |
| markdown-it-py | 4.2.0 | LC/venv/lib/python3.12/site-packages/markdown_it_py-4.2.0.dist-info/METADATA:2-3 |
| MarkupSafe | 3.0.3 | LC/venv/lib/python3.12/site-packages/markupsafe-3.0.3.dist-info/METADATA:2-3 |
| mdurl | 0.1.2 | LC/venv/lib/python3.12/site-packages/mdurl-0.1.2.dist-info/METADATA:2-3 |
| mpmath | 1.3.0 | LC/venv/lib/python3.12/site-packages/mpmath-1.3.0.dist-info/METADATA:2-3 |
| networkx | 3.7 | LC/venv/lib/python3.12/site-packages/networkx-3.7.dist-info/METADATA:2-3 |
| numpy | 2.5.3 | LC/venv/lib/python3.12/site-packages/numpy-2.5.3.dist-info/METADATA:2-3 |
| packaging | 26.3 | LC/venv/lib/python3.12/site-packages/packaging-26.3.dist-info/METADATA:2-3 |
| Pygments | 2.21.0 | LC/venv/lib/python3.12/site-packages/pygments-2.21.0.dist-info/METADATA:2-3 |
| PyYAML | 6.0.3 | LC/venv/lib/python3.12/site-packages/pyyaml-6.0.3.dist-info/METADATA:2-3 |
| regex | 2026.9.29 | LC/venv/lib/python3.12/site-packages/regex-2026.9.29.dist-info/METADATA:2-3 |
| rich | 15.0.0 | LC/venv/lib/python3.12/site-packages/rich-15.0.0.dist-info/METADATA:2-3 |
| safetensors | 0.8.0 | LC/venv/lib/python3.12/site-packages/safetensors-0.8.0.dist-info/METADATA:2-3 |
| setuptools | 84.0.0 | LC/venv/lib/python3.12/site-packages/setuptools-84.0.0.dist-info/METADATA:2-3 |
| shellingham | 1.5.4 | LC/venv/lib/python3.12/site-packages/shellingham-1.5.4.dist-info/METADATA:2-3 |
| sympy | 1.14.0 | LC/venv/lib/python3.12/site-packages/sympy-1.14.0.dist-info/METADATA:2-3 |
| tokenizers | 0.23.1 | LC/venv/lib/python3.12/site-packages/tokenizers-0.23.1.dist-info/METADATA:2-3 |
| torch | 2.14.0 | LC/venv/lib/python3.12/site-packages/torch-2.14.0.dist-info/METADATA:2-3 |
| tqdm | 4.70.1 | LC/venv/lib/python3.12/site-packages/tqdm-4.70.1.dist-info/METADATA:2-3 |
| transformers | 5.17.0 | LC/venv/lib/python3.12/site-packages/transformers-5.17.0.dist-info/METADATA:2-3 |
| typer | 0.27.2 | LC/venv/lib/python3.12/site-packages/typer-0.27.2.dist-info/METADATA:2-3 |
| typing_extensions | 4.16.0 | LC/venv/lib/python3.12/site-packages/typing_extensions-4.16.0.dist-info/METADATA:2-3 |

### Local model files

Every manifest model file below is VERIFIED present. The recorded revision is the download URL revision, not a live vendor lookup.

| File | Manifest citation | Current SHA-256 |
| --- | --- | --- |
| LC/models/qwen/model.safetensors | LC/download-plan.json:304 | `27cd75a405b9c1b46b59abfd88aaa209e6fed2a1972cde9b70e7659537c5e65b` |
| LC/models/qwen/config.json | LC/download-plan.json:311 | `d479c427a9ca5295218063d4f9aca4f297ab4ac27487cca7af42c84643d51ef0` |
| LC/models/qwen/generation_config.json | LC/download-plan.json:318 | `81051cd3f6e77013827148d0b8a6ead93f8ac390d5ab805f849199f0af6a08db` |
| LC/models/qwen/tokenizer.json | LC/download-plan.json:325 | `aeb13307a71acd8fe81861d94ad54ab689df773318809eed3cbe794b4492dae4` |
| LC/models/qwen/tokenizer_config.json | LC/download-plan.json:332 | `253153d0738ceb4c668d2eff957714dd2bea0b56de772a9fdccd96cbf517e6a0` |
| LC/models/qwen/merges.txt | LC/download-plan.json:339 | `8831e4f1a044471340f7c0a83d7bd71306a5b867e95fd870f74d0c5308a904d5` |
| LC/models/qwen/vocab.json | LC/download-plan.json:346 | `ca10d7e9fb3ed18575dd1e277a2579c16d108e32f27439684afa0e10b1440910` |
| LC/models/qwen/chat_template.jinja | LC/download-plan.json:353 | `6f682162495ec5b39fd9005c01b6aa2a74669379fe967039f1e2cbbe8752369d` |
| LC/models/qwen/README.md | LC/download-plan.json:360 | `5bba8c734f6dd3ae48317b4139317e45a7fce48fc55e15670b23a0dd15492ab6` |
| LC/models/decider/model.safetensors | LC/download-plan.json:367 | `acaef2228b134dcdc20cad4ee79219482c927ec819aa3687b9b8a575c338817f` |
| LC/models/decider/config.json | LC/download-plan.json:374 | `6cb8daca9fb653c61485ff7452fc068bacd5c27cbee659ecd24b47186b0d1b52` |
| LC/models/decider/decider_config.json | LC/download-plan.json:381 | `6e4891f2754a1c18a10f8dadb0c04e439e7f79fab0333d56641491bd4a05e722` |
| LC/models/decider/generation_config.json | LC/download-plan.json:388 | `62153eb6c69f2e1f426beaa8002b7186437e949c7588167085df14e10e9c0a73` |
| LC/models/decider/tokenizer.json | LC/download-plan.json:395 | `06b9509352d2af50381ab2247e083b80d32d5c0aba91c272ca9ff729b6a0e523` |
| LC/models/decider/tokenizer_config.json | LC/download-plan.json:402 | `171ecbe7ddae98d11840698f7df2b8d5b4722139db0f0620d3bbf429bd656250` |
| LC/models/decider/chat_template.jinja | LC/download-plan.json:409 | `273d8e0e683b885071fb17e08d71e5f2a5ddfb5309756181681de4f5a1822d80` |
| LC/models/decider/README.md | LC/download-plan.json:416 | `d736f764f9e6f62b2da816b14090b307dc796fbbdebca081d000b90d4217caab` |

## Protocol hash audit

Expected and actual values are full digests. Each row compares current local bytes against its cited record. Duplicate references are retained to expose conflicting expected hashes. SHA-1 rows use the Git blob header; they are not mislabelled SHA-256. All model files also have current SHA-256 above. Revision IDs are identities, not file SHA-256 digests. Diagnostic `plan.*.input_sha256` values identify serialized individual requests, not separate files; the enclosing frozen request file is checked.

Missing original files prevent a full historical reproduction. A current source mismatch does not by itself prove historical tampering or invalidate recorded outcomes.

| Protocol/source | File | Algorithm | Expected | Actual | Status | Note |
| --- | --- | --- | --- | --- | --- | --- |
| V2/preregistered-protocol.json:35 | V2/development-inputs.json | sha256 | `d040b307158bd1d10cf9722d55d4a0880cc4b8161cb1ac6c4d77d9604ef078ab` | `d040b307158bd1d10cf9722d55d4a0880cc4b8161cb1ac6c4d77d9604ef078ab` | MATCH |  |
| V2/preregistered-protocol.json:36 | V2/development-gold.json | sha256 | `b54949b4cd345d2bf00a72bf2b0681bd30d64446b649b47b3d6e178e6f17f14e` | `b54949b4cd345d2bf00a72bf2b0681bd30d64446b649b47b3d6e178e6f17f14e` | MATCH |  |
| V2/preregistered-protocol.json:37 | V2/frozen-requests.json | sha256 | `d9d0b15e006a390a318f566028d2c5cc26d6576e0d0540621ff8089957904d81` | `d9d0b15e006a390a318f566028d2c5cc26d6576e0d0540621ff8089957904d81` | MATCH |  |
| V2/preregistered-protocol.json:38 | V2/v2.py | sha256 | `ddb9ea4bdcb1ef8e769e9bd5f726092195e796666e8bbe82e0d901c16b2cc4fe` | `ddb9ea4bdcb1ef8e769e9bd5f726092195e796666e8bbe82e0d901c16b2cc4fe` | MATCH |  |
| V2/preregistered-protocol.json:41 | V1/corpus.json | sha256 | `a6231a71710d41bbd8104f1715f4d6e79f3ef10b8db68a12dde3a1b8f2ff61b3` | `a6231a71710d41bbd8104f1715f4d6e79f3ef10b8db68a12dde3a1b8f2ff61b3` | MATCH |  |
| V2/preregistered-protocol.json:42 | V1/gold.json | sha256 | `30e2ad98633fb47e1939cc8ce2be0c7b7e323f2f7322d4de44aaba7bbf254595` | `30e2ad98633fb47e1939cc8ce2be0c7b7e323f2f7322d4de44aaba7bbf254595` | MATCH |  |
| V2/preregistered-protocol.json:43 | V1/harness.py | sha256 | `6cb06be5f7fcf300dc3ef77e7769118ce901376ecfe9026a5891348b4c4d4033` | `6cb06be5f7fcf300dc3ef77e7769118ce901376ecfe9026a5891348b4c4d4033` | MATCH |  |
| V2/preregistered-protocol.json:44 | V1/live_pilot.py | sha256 | `5b5169ff98839a910199f3a1f21f3a364a86779319d3548c8affaaf10dd2d5af` | `5b5169ff98839a910199f3a1f21f3a364a86779319d3548c8affaaf10dd2d5af` | MATCH |  |
| V2/preregistered-protocol.json:45 | V1/sdk_bridge.mjs | sha256 | `b0cf48764c063e87af2e93a284bec579e2f555f43f0a4011b5f9970d3a081eb6` | `b0cf48764c063e87af2e93a284bec579e2f555f43f0a4011b5f9970d3a081eb6` | MATCH |  |
| V1/live-approved-Sentinel_cdbbf2b01e848191b8a7af343da340fa/authorization-and-runtime.json:16 | V1/corpus.json | sha256 | `a6231a71710d41bbd8104f1715f4d6e79f3ef10b8db68a12dde3a1b8f2ff61b3` | `a6231a71710d41bbd8104f1715f4d6e79f3ef10b8db68a12dde3a1b8f2ff61b3` | MATCH |  |
| V1/live-approved-Sentinel_cdbbf2b01e848191b8a7af343da340fa/authorization-and-runtime.json:17 | V1/gold.json | sha256 | `30e2ad98633fb47e1939cc8ce2be0c7b7e323f2f7322d4de44aaba7bbf254595` | `30e2ad98633fb47e1939cc8ce2be0c7b7e323f2f7322d4de44aaba7bbf254595` | MATCH |  |
| V1/live-approved-Sentinel_cdbbf2b01e848191b8a7af343da340fa/authorization-and-runtime.json:20 | V1/harness.py | sha256 | `6cb06be5f7fcf300dc3ef77e7769118ce901376ecfe9026a5891348b4c4d4033` | `6cb06be5f7fcf300dc3ef77e7769118ce901376ecfe9026a5891348b4c4d4033` | MATCH |  |
| V1/live-approved-Sentinel_cdbbf2b01e848191b8a7af343da340fa/authorization-and-runtime.json:21 | V1/live_pilot.py | sha256 | `a6a7315714f2922dd53de78f7691aa72fe8c1abdcce9f30f739a7525de813c76` | `5b5169ff98839a910199f3a1f21f3a364a86779319d3548c8affaaf10dd2d5af` | MISMATCH |  |
| V1/live-approved-Sentinel_cdbbf2b01e848191b8a7af343da340fa/authorization-and-runtime.json:22 | V1/sdk_bridge.mjs | sha256 | `b0cf48764c063e87af2e93a284bec579e2f555f43f0a4011b5f9970d3a081eb6` | `b0cf48764c063e87af2e93a284bec579e2f555f43f0a4011b5f9970d3a081eb6` | MATCH |  |
| LC/evaluation-protocol.json:4 | LC/development-requests.json | sha256 | `aefa246afa1659fb9f1642471cbfd94319ab9b4eed4c47bdb781de8113854c1f` | `aefa246afa1659fb9f1642471cbfd94319ab9b4eed4c47bdb781de8113854c1f` | MATCH |  |
| LC/evaluation-protocol.json:5 | LC/evaluate.py | sha256 | `bf007a60dd64aa86dd6c5d71953f27f63a57babff5d74007cd82a98ff4cbc8b6` | `bf007a60dd64aa86dd6c5d71953f27f63a57babff5d74007cd82a98ff4cbc8b6` | MATCH |  |
| LC/evaluation-protocol.json:7 | V2/development-inputs.json | sha256 | `d040b307158bd1d10cf9722d55d4a0880cc4b8161cb1ac6c4d77d9604ef078ab` | `d040b307158bd1d10cf9722d55d4a0880cc4b8161cb1ac6c4d77d9604ef078ab` | MATCH |  |
| LC/evaluation-protocol.json:8 | V2/development-gold.json | sha256 | `b54949b4cd345d2bf00a72bf2b0681bd30d64446b649b47b3d6e178e6f17f14e` | `b54949b4cd345d2bf00a72bf2b0681bd30d64446b649b47b3d6e178e6f17f14e` | MATCH |  |
| LC/evaluation-protocol.json:9 | V2/frozen-requests.json | sha256 | `d9d0b15e006a390a318f566028d2c5cc26d6576e0d0540621ff8089957904d81` | `d9d0b15e006a390a318f566028d2c5cc26d6576e0d0540621ff8089957904d81` | MATCH |  |
| LC/evaluation-protocol.json:10 | V2/preregistered-protocol.json | sha256 | `07d5fa665a5b03f89c43fe914965c7ad1836525d5161fd56c06922a1f774a462` | `07d5fa665a5b03f89c43fe914965c7ad1836525d5161fd56c06922a1f774a462` | MATCH |  |
| LC/download-plan.json:12 | LC/wheels/torch-2.14.0-cp312-cp312-macosx_14_0_arm64.whl | sha256 | `c1f844f1c750e87df4b68bc3afbc0e2b0c7ef19d7b8f666e48bdcf6a0c4f0056` | `c1f844f1c750e87df4b68bc3afbc0e2b0c7ef19d7b8f666e48bdcf6a0c4f0056` | MATCH |  |
| LC/download-plan.json:20 | LC/wheels/transformers-5.17.0-py3-none-any.whl | sha256 | `78ec1ce21579b38dfb83950a0658cd119f87212a2fcfdff478096ce9d6c03801` | `78ec1ce21579b38dfb83950a0658cd119f87212a2fcfdff478096ce9d6c03801` | MATCH |  |
| LC/download-plan.json:28 | LC/wheels/decider_ai-1.8.0-py3-none-any.whl | sha256 | `107cd5fb7fbca23d98a3cc755574a2d0b96cddf20edc8ed1ed5978022b0a2a1d` | `107cd5fb7fbca23d98a3cc755574a2d0b96cddf20edc8ed1ed5978022b0a2a1d` | MATCH |  |
| LC/download-plan.json:36 | LC/wheels/flash_linear_attention-0.5.2-py3-none-any.whl | sha256 | `dcf405d81f5426393b59037097aa700d0f4a841465d5028d5aa543f4502f2400` | `dcf405d81f5426393b59037097aa700d0f4a841465d5028d5aa543f4502f2400` | MATCH |  |
| LC/download-plan.json:44 | LC/wheels/fla_core-0.5.2-py3-none-any.whl | sha256 | `5e830c85bad3d0d34677f98ac7074d08687a3756f0f0499d95ceb96eb6920761` | `5e830c85bad3d0d34677f98ac7074d08687a3756f0f0499d95ceb96eb6920761` | MATCH |  |
| LC/download-plan.json:52 | LC/wheels/huggingface_hub-1.5.0-py3-none-any.whl | sha256 | `c9c0b3ab95a777fc91666111f3b3ede71c0cdced3614c553a64e98920585c4ee` | `c9c0b3ab95a777fc91666111f3b3ede71c0cdced3614c553a64e98920585c4ee` | MATCH |  |
| LC/download-plan.json:60 | LC/wheels/tokenizers-0.23.1-cp310-abi3-macosx_11_0_arm64.whl | sha256 | `e0948bbb1ac1d7cdfc9fb6d62c596e3b7550036ad60ecd654a66ad273326324e` | `e0948bbb1ac1d7cdfc9fb6d62c596e3b7550036ad60ecd654a66ad273326324e` | MATCH |  |
| LC/download-plan.json:68 | LC/wheels/safetensors-0.8.0-cp310-abi3-macosx_11_0_arm64.whl | sha256 | `c80201d22cbf405b80647a60ada77bba06c8fba2da2743ba1e89cdcc39a81f25` | `c80201d22cbf405b80647a60ada77bba06c8fba2da2743ba1e89cdcc39a81f25` | MATCH |  |
| LC/download-plan.json:76 | LC/wheels/numpy-2.5.3-cp312-cp312-macosx_14_0_arm64.whl | sha256 | `a72f874bc9e10e4b8f80426fb49716d5141f64442a0c8418065093ec8017fbb0` | `a72f874bc9e10e4b8f80426fb49716d5141f64442a0c8418065093ec8017fbb0` | MATCH |  |
| LC/download-plan.json:84 | LC/wheels/einops-0.8.2-py3-none-any.whl | sha256 | `54058201ac7087911181bfec4af6091bb59380360f069276601256a76af08193` | `54058201ac7087911181bfec4af6091bb59380360f069276601256a76af08193` | MATCH |  |
| LC/download-plan.json:92 | LC/wheels/jinja2-3.1.6-py3-none-any.whl | sha256 | `85ece4451f492d0c13c5dd7c13a64681a86afae63a5f347908daf103ce6d2f67` | `85ece4451f492d0c13c5dd7c13a64681a86afae63a5f347908daf103ce6d2f67` | MATCH |  |
| LC/download-plan.json:100 | LC/wheels/annotated_doc-0.0.5-py3-none-any.whl | sha256 | `117bac03a25ede5df5440e855b32d556049ca169ead221505badf432fed4b101` | `117bac03a25ede5df5440e855b32d556049ca169ead221505badf432fed4b101` | MATCH |  |
| LC/download-plan.json:108 | LC/wheels/anyio-4.15.1-py3-none-any.whl | sha256 | `6152fdbbf9a77fdec97731721bebf7c4c44f7c29b424b0065826173efc7ed101` | `6152fdbbf9a77fdec97731721bebf7c4c44f7c29b424b0065826173efc7ed101` | MATCH |  |
| LC/download-plan.json:116 | LC/wheels/certifi-2026.7.22-py3-none-any.whl | sha256 | `62f22742b58a1a33014a2b6b706588a8d7e2a88ae7bd1a6ebe8c992928483775` | `62f22742b58a1a33014a2b6b706588a8d7e2a88ae7bd1a6ebe8c992928483775` | MATCH |  |
| LC/download-plan.json:124 | LC/wheels/filelock-4.0.8-py3-none-any.whl | sha256 | `325ff22f358c18443b1fcdfa0a7aa3faec4b500c2807c554719da4567b533d31` | `325ff22f358c18443b1fcdfa0a7aa3faec4b500c2807c554719da4567b533d31` | MATCH |  |
| LC/download-plan.json:132 | LC/wheels/fsspec-2026.9.0-py3-none-any.whl | sha256 | `8dd6e646e99ea382bd85f97a45e6b526a442d79423a7dc673f1e2756d05fcb5f` | `8dd6e646e99ea382bd85f97a45e6b526a442d79423a7dc673f1e2756d05fcb5f` | MATCH |  |
| LC/download-plan.json:140 | LC/wheels/h11-0.16.0-py3-none-any.whl | sha256 | `63cf8bbe7522de3bf65932fda1d9c2772064ffb3dae62d55932da54b31cb6c86` | `63cf8bbe7522de3bf65932fda1d9c2772064ffb3dae62d55932da54b31cb6c86` | MATCH |  |
| LC/download-plan.json:148 | LC/wheels/hf_xet-1.6.0-cp38-abi3-macosx_11_0_arm64.whl | sha256 | `f0906082d9932ae0c0057fa194041c22b4e2cdb46b2592ef3b91f020d62a081a` | `f0906082d9932ae0c0057fa194041c22b4e2cdb46b2592ef3b91f020d62a081a` | MATCH |  |
| LC/download-plan.json:156 | LC/wheels/httpcore-1.0.9-py3-none-any.whl | sha256 | `2d400746a40668fc9dec9810239072b40b4484b640a8c38fd654a024c7a1bf55` | `2d400746a40668fc9dec9810239072b40b4484b640a8c38fd654a024c7a1bf55` | MATCH |  |
| LC/download-plan.json:164 | LC/wheels/httpx-0.28.1-py3-none-any.whl | sha256 | `d909fcccc110f8c7faf814ca82a9a4d816bc5a6dbfea25d6591d6985b8ba59ad` | `d909fcccc110f8c7faf814ca82a9a4d816bc5a6dbfea25d6591d6985b8ba59ad` | MATCH |  |
| LC/download-plan.json:172 | LC/wheels/idna-3.20-py3-none-any.whl | sha256 | `ab7ae7122974553370f0bdb919e1a960b2cd1bc1ef0276416d896db81c14582c` | `ab7ae7122974553370f0bdb919e1a960b2cd1bc1ef0276416d896db81c14582c` | MATCH |  |
| LC/download-plan.json:180 | LC/wheels/markdown_it_py-4.2.0-py3-none-any.whl | sha256 | `9f7ebbcd14fe59494226453aed97c1070d83f8d24b6fc3a3bcf9a38092641c4a` | `9f7ebbcd14fe59494226453aed97c1070d83f8d24b6fc3a3bcf9a38092641c4a` | MATCH |  |
| LC/download-plan.json:188 | LC/wheels/markupsafe-3.0.3-cp312-cp312-macosx_11_0_arm64.whl | sha256 | `1872df69a4de6aead3491198eaf13810b565bdbeec3ae2dc8780f14458ec73ce` | `1872df69a4de6aead3491198eaf13810b565bdbeec3ae2dc8780f14458ec73ce` | MATCH |  |
| LC/download-plan.json:196 | LC/wheels/mdurl-0.1.2-py3-none-any.whl | sha256 | `84008a41e51615a49fc9966191ff91509e3c40b939176e643fd50a5c2196b8f8` | `84008a41e51615a49fc9966191ff91509e3c40b939176e643fd50a5c2196b8f8` | MATCH |  |
| LC/download-plan.json:204 | LC/wheels/mpmath-1.3.0-py3-none-any.whl | sha256 | `a0b2b9fe80bbcd81a6647ff13108738cfb482d481d826cc0e02f5b35e5c88d2c` | `a0b2b9fe80bbcd81a6647ff13108738cfb482d481d826cc0e02f5b35e5c88d2c` | MATCH |  |
| LC/download-plan.json:212 | LC/wheels/networkx-3.7-py3-none-any.whl | sha256 | `e3fd2c13a7814cee3746340d8d7f8598a67f16a58bf47fb7f8793fab6efca1b0` | `e3fd2c13a7814cee3746340d8d7f8598a67f16a58bf47fb7f8793fab6efca1b0` | MATCH |  |
| LC/download-plan.json:220 | LC/wheels/packaging-26.3-py3-none-any.whl | sha256 | `d7193f7c8e4e93f444fde0262bf90af30e16fa0ad0ad44cb553c87339b23cd1c` | `d7193f7c8e4e93f444fde0262bf90af30e16fa0ad0ad44cb553c87339b23cd1c` | MATCH |  |
| LC/download-plan.json:228 | LC/wheels/pygments-2.21.0-py3-none-any.whl | sha256 | `2363c69b61c4a97c838da3b130dcd6468f4848992b21a82f2a63ec34377137d9` | `2363c69b61c4a97c838da3b130dcd6468f4848992b21a82f2a63ec34377137d9` | MATCH |  |
| LC/download-plan.json:236 | LC/wheels/pyyaml-6.0.3-cp312-cp312-macosx_11_0_arm64.whl | sha256 | `fc09d0aa354569bc501d4e787133afc08552722d3ab34836a80547331bb5d4a0` | `fc09d0aa354569bc501d4e787133afc08552722d3ab34836a80547331bb5d4a0` | MATCH |  |
| LC/download-plan.json:244 | LC/wheels/regex-2026.9.29-cp312-cp312-macosx_11_0_arm64.whl | sha256 | `f57dc6b8fef170f105d2cf5cdce254f47b137d7755086cf7050f47e16582abba` | `f57dc6b8fef170f105d2cf5cdce254f47b137d7755086cf7050f47e16582abba` | MATCH |  |
| LC/download-plan.json:252 | LC/wheels/rich-15.0.0-py3-none-any.whl | sha256 | `33bd4ef74232fb73fe9279a257718407f169c09b78a87ad3d296f548e27de0bb` | `33bd4ef74232fb73fe9279a257718407f169c09b78a87ad3d296f548e27de0bb` | MATCH |  |
| LC/download-plan.json:260 | LC/wheels/setuptools-84.0.0-py3-none-any.whl | sha256 | `51a52592b3b99e102b609654876bd65f19f999935166d1352678931132b0c670` | `51a52592b3b99e102b609654876bd65f19f999935166d1352678931132b0c670` | MATCH |  |
| LC/download-plan.json:268 | LC/wheels/shellingham-1.5.4-py2.py3-none-any.whl | sha256 | `7ecfff8f2fd72616f7481040475a65b2bf8af90a56c89140852d1120324e8686` | `7ecfff8f2fd72616f7481040475a65b2bf8af90a56c89140852d1120324e8686` | MATCH |  |
| LC/download-plan.json:276 | LC/wheels/sympy-1.14.0-py3-none-any.whl | sha256 | `e091cc3e99d2141a0ba2847328f5479b05d94a6635cb96148ccb3f34671bd8f5` | `e091cc3e99d2141a0ba2847328f5479b05d94a6635cb96148ccb3f34671bd8f5` | MATCH |  |
| LC/download-plan.json:284 | LC/wheels/tqdm-4.70.1-py3-none-any.whl | sha256 | `c293e525e6fef9c20e8728fd4612df02a0aa31bb5fe91ecd93e123b1b7bffa73` | `c293e525e6fef9c20e8728fd4612df02a0aa31bb5fe91ecd93e123b1b7bffa73` | MATCH |  |
| LC/download-plan.json:292 | LC/wheels/typer-0.27.2-py3-none-any.whl | sha256 | `b3a5fc4342d5fc8fda8fc3010b1cf117e9249aab7fae800c2eff62fd3842d97d` | `b3a5fc4342d5fc8fda8fc3010b1cf117e9249aab7fae800c2eff62fd3842d97d` | MATCH |  |
| LC/download-plan.json:300 | LC/wheels/typing_extensions-4.16.0-py3-none-any.whl | sha256 | `481caa481374e813c1b176ada14e97f1f67a4539ce9cfeb3f350d78d6370c2e8` | `481caa481374e813c1b176ada14e97f1f67a4539ce9cfeb3f350d78d6370c2e8` | MATCH |  |
| LC/download-plan.json:307 | LC/models/qwen/model.safetensors | sha256 | `27cd75a405b9c1b46b59abfd88aaa209e6fed2a1972cde9b70e7659537c5e65b` | `27cd75a405b9c1b46b59abfd88aaa209e6fed2a1972cde9b70e7659537c5e65b` | MATCH |  |
| LC/download-plan.json:314 | LC/models/qwen/config.json | sha1 | `39784456e9de7a06590f8a4a38760ac1fb38d65e` | `39784456e9de7a06590f8a4a38760ac1fb38d65e` | MATCH | Git blob SHA-1 comparison; SHA-256 also listed below |
| LC/download-plan.json:321 | LC/models/qwen/generation_config.json | sha1 | `e4f1d3193e99a3e5d7047edf56e93a6e933fa31b` | `e4f1d3193e99a3e5d7047edf56e93a6e933fa31b` | MATCH | Git blob SHA-1 comparison; SHA-256 also listed below |
| LC/download-plan.json:328 | LC/models/qwen/tokenizer.json | sha256 | `aeb13307a71acd8fe81861d94ad54ab689df773318809eed3cbe794b4492dae4` | `aeb13307a71acd8fe81861d94ad54ab689df773318809eed3cbe794b4492dae4` | MATCH |  |
| LC/download-plan.json:335 | LC/models/qwen/tokenizer_config.json | sha1 | `7345216a0785dc7086e8c245b2a9d3896ce2b756` | `7345216a0785dc7086e8c245b2a9d3896ce2b756` | MATCH | Git blob SHA-1 comparison; SHA-256 also listed below |
| LC/download-plan.json:342 | LC/models/qwen/merges.txt | sha1 | `31349551d90c7606f325fe0f11bbb8bd5fa0d7c7` | `31349551d90c7606f325fe0f11bbb8bd5fa0d7c7` | MATCH | Git blob SHA-1 comparison; SHA-256 also listed below |
| LC/download-plan.json:349 | LC/models/qwen/vocab.json | sha1 | `4783fe10ac3adce15ac8f358ef5462739852c569` | `4783fe10ac3adce15ac8f358ef5462739852c569` | MATCH | Git blob SHA-1 comparison; SHA-256 also listed below |
| LC/download-plan.json:356 | LC/models/qwen/chat_template.jinja | sha1 | `63b97f268a9ddb9c6b34e6d7d8ef531d1fee9cf4` | `63b97f268a9ddb9c6b34e6d7d8ef531d1fee9cf4` | MATCH | Git blob SHA-1 comparison; SHA-256 also listed below |
| LC/download-plan.json:363 | LC/models/qwen/README.md | sha1 | `b8bfdef6c3cd9297bf8f5965c87edbee65a444aa` | `b8bfdef6c3cd9297bf8f5965c87edbee65a444aa` | MATCH | Git blob SHA-1 comparison; SHA-256 also listed below |
| LC/download-plan.json:370 | LC/models/decider/model.safetensors | sha256 | `acaef2228b134dcdc20cad4ee79219482c927ec819aa3687b9b8a575c338817f` | `acaef2228b134dcdc20cad4ee79219482c927ec819aa3687b9b8a575c338817f` | MATCH |  |
| LC/download-plan.json:377 | LC/models/decider/config.json | sha1 | `27e38437e7c493534cab7a41521acba190da65ed` | `27e38437e7c493534cab7a41521acba190da65ed` | MATCH | Git blob SHA-1 comparison; SHA-256 also listed below |
| LC/download-plan.json:384 | LC/models/decider/decider_config.json | sha1 | `589d43974801443adbc41a27a713d133e8687ca8` | `589d43974801443adbc41a27a713d133e8687ca8` | MATCH | Git blob SHA-1 comparison; SHA-256 also listed below |
| LC/download-plan.json:391 | LC/models/decider/generation_config.json | sha1 | `31ec2a53cc9cde720b0a8fbc68b9c4e73ac5a18f` | `31ec2a53cc9cde720b0a8fbc68b9c4e73ac5a18f` | MATCH | Git blob SHA-1 comparison; SHA-256 also listed below |
| LC/download-plan.json:398 | LC/models/decider/tokenizer.json | sha256 | `06b9509352d2af50381ab2247e083b80d32d5c0aba91c272ca9ff729b6a0e523` | `06b9509352d2af50381ab2247e083b80d32d5c0aba91c272ca9ff729b6a0e523` | MATCH |  |
| LC/download-plan.json:405 | LC/models/decider/tokenizer_config.json | sha1 | `8a675cf6071546d7c13fea4c9d1acf1d1958569c` | `8a675cf6071546d7c13fea4c9d1acf1d1958569c` | MATCH | Git blob SHA-1 comparison; SHA-256 also listed below |
| LC/download-plan.json:412 | LC/models/decider/chat_template.jinja | sha1 | `0ef09f214eaa6d9bca297988afc1454b5827b2c7` | `0ef09f214eaa6d9bca297988afc1454b5827b2c7` | MATCH | Git blob SHA-1 comparison; SHA-256 also listed below |
| LC/download-plan.json:419 | LC/models/decider/README.md | sha1 | `881af6d4c1f77bf4158f9e04c14047ab84269341` | `881af6d4c1f77bf4158f9e04c14047ab84269341` | MATCH | Git blob SHA-1 comparison; SHA-256 also listed below |
| LC/final-comparison.json:5 | V2/live-results/results.json | sha256 | `ef593acc8da8aec3020282d20d7799d801e005a9815449cbf080f8ea7d916f29` | `ef593acc8da8aec3020282d20d7799d801e005a9815449cbf080f8ea7d916f29` | MATCH |  |
| LC/final-comparison.json:6 | LC/results.json | sha256 | `e0edfb0454c7d6ac852126454241520603cbc25609eb1f8cdc4dbfa80b0853fd` | `e0edfb0454c7d6ac852126454241520603cbc25609eb1f8cdc4dbfa80b0853fd` | MATCH |  |
| LC/final-comparison.json:7 | LC/evaluation-protocol.json | sha256 | `9ef7c315b1c213d56efa413ddc367f51e02e348df9fe2595c41a4b85878219c6` | `9ef7c315b1c213d56efa413ddc367f51e02e348df9fe2595c41a4b85878219c6` | MATCH |  |
| LC/final-comparison.json:8 | V2/preregistered-protocol.json | sha256 | `07d5fa665a5b03f89c43fe914965c7ad1836525d5161fd56c06922a1f774a462` | `07d5fa665a5b03f89c43fe914965c7ad1836525d5161fd56c06922a1f774a462` | MATCH |  |
| LY/shortening-rule-addendum.json:3 | LY/build_subset.py | sha256 | `75ba8e0d4cce9caa6d61612e680ec4313bbae6b43f29fdd12dc487c6b3fd53f1` | `75ba8e0d4cce9caa6d61612e680ec4313bbae6b43f29fdd12dc487c6b3fd53f1` | MATCH |  |
| LY/shortening-rule-addendum.json:4 | LC/development-requests.json | sha256 | `aefa246afa1659fb9f1642471cbfd94319ab9b4eed4c47bdb781de8113854c1f` | `aefa246afa1659fb9f1642471cbfd94319ab9b4eed4c47bdb781de8113854c1f` | MATCH |  |
| LY/shortening-rule-addendum.json:5 | LY/short-input-requests.json | sha256 | `479d483e06d7812dc9b8bd76ed8a880ea5e27334ddc88c0327358e2bb8fd5abd` | `479d483e06d7812dc9b8bd76ed8a880ea5e27334ddc88c0327358e2bb8fd5abd` | MATCH |  |
| LY/shortening-rule-addendum.json:24 | LY/fidelity-check.json | sha256 | `7d3dfa2fccc4db2bb57db62cf05d659bb2146406d8bf5412a4f06a0378a6466b` | `7d3dfa2fccc4db2bb57db62cf05d659bb2146406d8bf5412a4f06a0378a6466b` | MATCH |  |
| LY/shortening-rule-addendum.json:24 | LY/fidelity_check.py | sha256 | `a6b8122520dbcb6f88923bc4d5fc58ca086d12a107dfdc8e699f4a04d401ff7f` | `a6b8122520dbcb6f88923bc4d5fc58ca086d12a107dfdc8e699f4a04d401ff7f` | MATCH |  |
| LY/shortening-rule-addendum.json:2 | LY/short-input-manifest.json | sha256 | `1a8922c17b87fccb84ac7b5a02bc9422f9da6984bb59c942d7dbb3e26f63980b` | `1a8922c17b87fccb84ac7b5a02bc9422f9da6984bb59c942d7dbb3e26f63980b` | MATCH |  |
| LY/shortening-rule-addendum.json:25 | LY/full-input-token-audit.json | sha256 | `be1a3c72cfa77084ff5d914650a60466ecba153d86520029668bebffb9455763` | `be1a3c72cfa77084ff5d914650a60466ecba153d86520029668bebffb9455763` | MATCH |  |
| LY/short-input-manifest.json:3 | LC/development-requests.json | sha256 | `aefa246afa1659fb9f1642471cbfd94319ab9b4eed4c47bdb781de8113854c1f` | `aefa246afa1659fb9f1642471cbfd94319ab9b4eed4c47bdb781de8113854c1f` | MATCH |  |
| LY/idle-benchmark-status.json:13 | LY/run_laya.mjs | sha256 | `701cf48294dbde4a88abccb302e46e0eb047a4916662ff7f5e60faa50d049013` | `701cf48294dbde4a88abccb302e46e0eb047a4916662ff7f5e60faa50d049013` | MATCH |  |
| LY/idle-benchmark-status.json:20 | LY/score.py | sha256 | `8e19519825125e67024185b01bc2af6d1fed6a5177e896bec06b92a722de5543` | `8e19519825125e67024185b01bc2af6d1fed6a5177e896bec06b92a722de5543` | MATCH |  |
| LY/contended-diagnostic/preregistration.json:9 | LY/contended-diagnostic/../short-input-requests.json | sha256 | `479d483e06d7812dc9b8bd76ed8a880ea5e27334ddc88c0327358e2bb8fd5abd` | `479d483e06d7812dc9b8bd76ed8a880ea5e27334ddc88c0327358e2bb8fd5abd` | MATCH |  |
| LY/contended-diagnostic/preregistration.json:195 | LY/contended-diagnostic/monitor-probe.json | sha256 | `03e9e4ed2dbddc13c22371d9b841d37f01f5565fa6b61fb666793fa9f1432ce8` | `03e9e4ed2dbddc13c22371d9b841d37f01f5565fa6b61fb666793fa9f1432ce8` | MATCH |  |
| LY/contended-diagnostic/preregistration.json:215 | LY/contended-diagnostic/sequential-runtime-behavior.md | sha256 | `7723961f170f7850b5c668b039bf86ec4139812bc3323cb5ffe8063ba53a2f4b` | `7723961f170f7850b5c668b039bf86ec4139812bc3323cb5ffe8063ba53a2f4b` | MATCH |  |
| LY/contended-diagnostic/preregistration.json:219 | LY/contended-diagnostic/run_diag.mjs | sha256 | `51153472143a40d6b479b7c6547b50960d434c9f43b5b6ba70195e9ddebc9e43` | `51153472143a40d6b479b7c6547b50960d434c9f43b5b6ba70195e9ddebc9e43` | MATCH |  |
| LY/contended-diagnostic/preregistration.json:225 | LY/contended-diagnostic/tests/fake_worker_diag.py | sha256 | `10935c6bf534a92275ac7aca559be3863e6102b5a660aa12612947d28760c147` | `10935c6bf534a92275ac7aca559be3863e6102b5a660aa12612947d28760c147` | MATCH |  |
| LY/contended-diagnostic/diagnostic-report.json:3 | LY/contended-diagnostic/preregistration.json | sha256 | `aef6f428f4bc3960bc8abbaa7a732681ec3eb2c5c83ed6f53162def342b74292` | `aef6f428f4bc3960bc8abbaa7a732681ec3eb2c5c83ed6f53162def342b74292` | MATCH |  |
| LY/contended-diagnostic/diagnostic-report.json:4 | LY/contended-diagnostic/live-run-1/raw-results.jsonl | sha256 | `71905d3da2c261bb4cf046e82dd9b66d3d544871dd6fc9cf8f22fb57d57a9b3b` | `71905d3da2c261bb4cf046e82dd9b66d3d544871dd6fc9cf8f22fb57d57a9b3b` | MATCH |  |
| LY/contended-diagnostic/diagnostic-report.json:4 | LY/contended-diagnostic/live-run-1/status.json | sha256 | `dd05d5a8dd7eba37fbd1229a47c4eaf2a095853d9bf0672ec8bb38eff2d05367` | `dd05d5a8dd7eba37fbd1229a47c4eaf2a095853d9bf0672ec8bb38eff2d05367` | MATCH |  |
| LY/contended-diagnostic/diagnostic-report.json:4 | LY/contended-diagnostic/live-run-1/monitor-samples.jsonl | sha256 | `c4e6f73d52598e99df5219e348563b86f7e3f550a578c4de4e9f27547ae0a2d1` | `c4e6f73d52598e99df5219e348563b86f7e3f550a578c4de4e9f27547ae0a2d1` | MATCH |  |
| LY/contended-diagnostic/offline-scoring/source-hashes.json:6 | LY/contended-diagnostic/diagnostic-report.json | sha256 | `a600ab099c3a7b393d85b269a4b36ee93db224d63b5b22f130c86709e03b8ba3` | `a600ab099c3a7b393d85b269a4b36ee93db224d63b5b22f130c86709e03b8ba3` | MATCH | before and after expected hashes are identical |
| LY/contended-diagnostic/offline-scoring/source-hashes.json:12 | LY/contended-diagnostic/live-run-1/status.json | sha256 | `dd05d5a8dd7eba37fbd1229a47c4eaf2a095853d9bf0672ec8bb38eff2d05367` | `dd05d5a8dd7eba37fbd1229a47c4eaf2a095853d9bf0672ec8bb38eff2d05367` | MATCH | before and after expected hashes are identical |
| LY/contended-diagnostic/offline-scoring/source-hashes.json:18 | LY/contended-diagnostic/live-run-1/raw-results.jsonl | sha256 | `71905d3da2c261bb4cf046e82dd9b66d3d544871dd6fc9cf8f22fb57d57a9b3b` | `71905d3da2c261bb4cf046e82dd9b66d3d544871dd6fc9cf8f22fb57d57a9b3b` | MATCH | before and after expected hashes are identical |
| LY/contended-diagnostic/offline-scoring/source-hashes.json:24 | LY/contended-diagnostic/preregistration.json | sha256 | `aef6f428f4bc3960bc8abbaa7a732681ec3eb2c5c83ed6f53162def342b74292` | `aef6f428f4bc3960bc8abbaa7a732681ec3eb2c5c83ed6f53162def342b74292` | MATCH | before and after expected hashes are identical |
| LY/contended-diagnostic/offline-scoring/source-hashes.json:30 | LY/score.py | sha256 | `8e19519825125e67024185b01bc2af6d1fed6a5177e896bec06b92a722de5543` | `8e19519825125e67024185b01bc2af6d1fed6a5177e896bec06b92a722de5543` | MATCH | before and after expected hashes are identical |
| LY/contended-diagnostic/offline-scoring/source-hashes.json:36 | LY/short-input-manifest.json | sha256 | `1a8922c17b87fccb84ac7b5a02bc9422f9da6984bb59c942d7dbb3e26f63980b` | `1a8922c17b87fccb84ac7b5a02bc9422f9da6984bb59c942d7dbb3e26f63980b` | MATCH | before and after expected hashes are identical |
| LY/contended-diagnostic/offline-scoring/source-hashes.json:42 | LY/shortening-rule-addendum.json | sha256 | `473ef82256dc4555ff2d630af61af7b4bb4686204d6eaaeb42d04a1e1c41f3b1` | `473ef82256dc4555ff2d630af61af7b4bb4686204d6eaaeb42d04a1e1c41f3b1` | MATCH | before and after expected hashes are identical |
| LY/contended-diagnostic/offline-scoring/source-hashes.json:48 | LY/fidelity-check.json | sha256 | `7d3dfa2fccc4db2bb57db62cf05d659bb2146406d8bf5412a4f06a0378a6466b` | `7d3dfa2fccc4db2bb57db62cf05d659bb2146406d8bf5412a4f06a0378a6466b` | MATCH | before and after expected hashes are identical |
| LY/contended-diagnostic/offline-scoring/source-hashes.json:54 | V2/development-gold.json | sha256 | `b54949b4cd345d2bf00a72bf2b0681bd30d64446b649b47b3d6e178e6f17f14e` | `b54949b4cd345d2bf00a72bf2b0681bd30d64446b649b47b3d6e178e6f17f14e` | MATCH | before and after expected hashes are identical |
| OQ/prereg.json:17 | OQ/corpus.json | sha256 | `fcf7859c905b16f1425cd3c4a73091594515672b58ed5aaf7e9210fc8e4441aa` | `fcf7859c905b16f1425cd3c4a73091594515672b58ed5aaf7e9210fc8e4441aa` | MATCH |  |
| OQ/prereg.json:22 | OQ/labels.json | sha256 | `2fb797f55c479d307e7df3e82445eda45a8f5b3dc83c54a7e532a2877e333644` | `2fb797f55c479d307e7df3e82445eda45a8f5b3dc83c54a7e532a2877e333644` | MATCH |  |
| OQ/prereg.json:12 | OW/DroppyCode/Core/Models/HydraOracle.swift | sha256 | `7640916a22ab6f8ff11883ff321aed32aa2937247855e3b7e4e4737499ab9673` | `3c989ea408a4080b541de485e2a63b6711af33e42fb2fd5af871a7d9a19399b2` | MISMATCH | current Oracle worktree path; not a historical checkout |
| OQ/prereg.json:8 | OW/DroppyCodeTests/OracleLiveRuns.swift | sha256 | `c9a47d19bda90179c2e52a338c7713fa064f2eaae8d10c980a0923cadf70060d` | `—` | NOT FOUND | current Oracle worktree path; not a historical checkout |
| OQ/prereg.json:14 | OW/DroppyCode/Resources/Oracle/oracle_laya_worker.py | sha256 | `5bd792eb6f2ec10565cc7a60798a19566b901463241c8b686b7f1b85ae76f667` | `d16dfb56b4de4f31a8083546d758fa0f28cab7b211fe040cb9d8605b99531761` | MISMATCH | current Oracle worktree path; not a historical checkout |
| OQ/prereg.json:15 | OQ/score.py | sha256 | `b565e4750c8c12b956335e4c3973527e5cd8fa7f48666899511305243cd7f9e2` | `—` | NOT FOUND | current Oracle worktree path; not a historical checkout |
| OQ/prereg.json:6 | OW/DroppyCodeTests/OracleLiveRuns.swift | sha256 | `c876f77c6b33778815dad9ea6e0076d750701e4112d17606509e8218ef86bbcd` | `—` | NOT FOUND | superseded pre-amendment hash, historical reference only |
| LR/v0-current/prereg.json:17 | LR/v0-current/corpus.json | sha256 | `fcf7859c905b16f1425cd3c4a73091594515672b58ed5aaf7e9210fc8e4441aa` | `fcf7859c905b16f1425cd3c4a73091594515672b58ed5aaf7e9210fc8e4441aa` | MATCH |  |
| LR/v0-current/prereg.json:22 | LR/v0-current/labels.json | sha256 | `2fb797f55c479d307e7df3e82445eda45a8f5b3dc83c54a7e532a2877e333644` | `2fb797f55c479d307e7df3e82445eda45a8f5b3dc83c54a7e532a2877e333644` | MATCH |  |
| LR/v0-current/prereg.json:12 | OW/DroppyCode/Core/Models/HydraOracle.swift | sha256 | `7640916a22ab6f8ff11883ff321aed32aa2937247855e3b7e4e4737499ab9673` | `3c989ea408a4080b541de485e2a63b6711af33e42fb2fd5af871a7d9a19399b2` | MISMATCH | current Oracle worktree path; not a historical checkout |
| LR/v0-current/prereg.json:8 | OW/DroppyCodeTests/OracleLiveRuns.swift | sha256 | `c9a47d19bda90179c2e52a338c7713fa064f2eaae8d10c980a0923cadf70060d` | `—` | NOT FOUND | current Oracle worktree path; not a historical checkout |
| LR/v0-current/prereg.json:14 | OW/DroppyCode/Resources/Oracle/oracle_laya_worker.py | sha256 | `5bd792eb6f2ec10565cc7a60798a19566b901463241c8b686b7f1b85ae76f667` | `d16dfb56b4de4f31a8083546d758fa0f28cab7b211fe040cb9d8605b99531761` | MISMATCH | current Oracle worktree path; not a historical checkout |
| LR/v0-current/prereg.json:15 | OQ/score.py | sha256 | `b565e4750c8c12b956335e4c3973527e5cd8fa7f48666899511305243cd7f9e2` | `—` | NOT FOUND | current Oracle worktree path; not a historical checkout |
| LR/v0-current/prereg.json:6 | OW/DroppyCodeTests/OracleLiveRuns.swift | sha256 | `c876f77c6b33778815dad9ea6e0076d750701e4112d17606509e8218ef86bbcd` | `—` | NOT FOUND | superseded pre-amendment hash, historical reference only |
| LR/v1-runtime020/prereg.json:17 | LR/v1-runtime020/corpus.json | sha256 | `fcf7859c905b16f1425cd3c4a73091594515672b58ed5aaf7e9210fc8e4441aa` | `fcf7859c905b16f1425cd3c4a73091594515672b58ed5aaf7e9210fc8e4441aa` | MATCH |  |
| LR/v1-runtime020/prereg.json:22 | LR/v1-runtime020/labels.json | sha256 | `2fb797f55c479d307e7df3e82445eda45a8f5b3dc83c54a7e532a2877e333644` | `2fb797f55c479d307e7df3e82445eda45a8f5b3dc83c54a7e532a2877e333644` | MATCH |  |
| LR/v1-runtime020/prereg.json:12 | OW/DroppyCode/Core/Models/HydraOracle.swift | sha256 | `7640916a22ab6f8ff11883ff321aed32aa2937247855e3b7e4e4737499ab9673` | `3c989ea408a4080b541de485e2a63b6711af33e42fb2fd5af871a7d9a19399b2` | MISMATCH | current Oracle worktree path; not a historical checkout |
| LR/v1-runtime020/prereg.json:8 | OW/DroppyCodeTests/OracleLiveRuns.swift | sha256 | `c9a47d19bda90179c2e52a338c7713fa064f2eaae8d10c980a0923cadf70060d` | `—` | NOT FOUND | current Oracle worktree path; not a historical checkout |
| LR/v1-runtime020/prereg.json:14 | OW/DroppyCode/Resources/Oracle/oracle_laya_worker.py | sha256 | `5bd792eb6f2ec10565cc7a60798a19566b901463241c8b686b7f1b85ae76f667` | `d16dfb56b4de4f31a8083546d758fa0f28cab7b211fe040cb9d8605b99531761` | MISMATCH | current Oracle worktree path; not a historical checkout |
| LR/v1-runtime020/prereg.json:15 | OQ/score.py | sha256 | `b565e4750c8c12b956335e4c3973527e5cd8fa7f48666899511305243cd7f9e2` | `—` | NOT FOUND | current Oracle worktree path; not a historical checkout |
| LR/v1-runtime020/prereg.json:6 | OW/DroppyCodeTests/OracleLiveRuns.swift | sha256 | `c876f77c6b33778815dad9ea6e0076d750701e4112d17606509e8218ef86bbcd` | `—` | NOT FOUND | superseded pre-amendment hash, historical reference only |
| LR/v2-typed/prereg.json:17 | LR/v2-typed/corpus.json | sha256 | `fcf7859c905b16f1425cd3c4a73091594515672b58ed5aaf7e9210fc8e4441aa` | `fcf7859c905b16f1425cd3c4a73091594515672b58ed5aaf7e9210fc8e4441aa` | MATCH |  |
| LR/v2-typed/prereg.json:22 | LR/v2-typed/labels.json | sha256 | `2fb797f55c479d307e7df3e82445eda45a8f5b3dc83c54a7e532a2877e333644` | `2fb797f55c479d307e7df3e82445eda45a8f5b3dc83c54a7e532a2877e333644` | MATCH |  |
| LR/v2-typed/prereg.json:12 | OW/DroppyCode/Core/Models/HydraOracle.swift | sha256 | `7640916a22ab6f8ff11883ff321aed32aa2937247855e3b7e4e4737499ab9673` | `3c989ea408a4080b541de485e2a63b6711af33e42fb2fd5af871a7d9a19399b2` | MISMATCH | current Oracle worktree path; not a historical checkout |
| LR/v2-typed/prereg.json:8 | OW/DroppyCodeTests/OracleLiveRuns.swift | sha256 | `c9a47d19bda90179c2e52a338c7713fa064f2eaae8d10c980a0923cadf70060d` | `—` | NOT FOUND | current Oracle worktree path; not a historical checkout |
| LR/v2-typed/prereg.json:14 | OW/DroppyCode/Resources/Oracle/oracle_laya_worker.py | sha256 | `5bd792eb6f2ec10565cc7a60798a19566b901463241c8b686b7f1b85ae76f667` | `d16dfb56b4de4f31a8083546d758fa0f28cab7b211fe040cb9d8605b99531761` | MISMATCH | current Oracle worktree path; not a historical checkout |
| LR/v2-typed/prereg.json:15 | OQ/score.py | sha256 | `b565e4750c8c12b956335e4c3973527e5cd8fa7f48666899511305243cd7f9e2` | `—` | NOT FOUND | current Oracle worktree path; not a historical checkout |
| LR/v2-typed/prereg.json:6 | OW/DroppyCodeTests/OracleLiveRuns.swift | sha256 | `c876f77c6b33778815dad9ea6e0076d750701e4112d17606509e8218ef86bbcd` | `—` | NOT FOUND | superseded pre-amendment hash, historical reference only |
| LR/v3-multilingual/prereg.json:17 | LR/v3-multilingual/corpus.json | sha256 | `fcf7859c905b16f1425cd3c4a73091594515672b58ed5aaf7e9210fc8e4441aa` | `fcf7859c905b16f1425cd3c4a73091594515672b58ed5aaf7e9210fc8e4441aa` | MATCH |  |
| LR/v3-multilingual/prereg.json:22 | LR/v3-multilingual/labels.json | sha256 | `2fb797f55c479d307e7df3e82445eda45a8f5b3dc83c54a7e532a2877e333644` | `2fb797f55c479d307e7df3e82445eda45a8f5b3dc83c54a7e532a2877e333644` | MATCH |  |
| LR/v3-multilingual/prereg.json:12 | OW/DroppyCode/Core/Models/HydraOracle.swift | sha256 | `7640916a22ab6f8ff11883ff321aed32aa2937247855e3b7e4e4737499ab9673` | `3c989ea408a4080b541de485e2a63b6711af33e42fb2fd5af871a7d9a19399b2` | MISMATCH | current Oracle worktree path; not a historical checkout |
| LR/v3-multilingual/prereg.json:8 | OW/DroppyCodeTests/OracleLiveRuns.swift | sha256 | `c9a47d19bda90179c2e52a338c7713fa064f2eaae8d10c980a0923cadf70060d` | `—` | NOT FOUND | current Oracle worktree path; not a historical checkout |
| LR/v3-multilingual/prereg.json:14 | OW/DroppyCode/Resources/Oracle/oracle_laya_worker.py | sha256 | `5bd792eb6f2ec10565cc7a60798a19566b901463241c8b686b7f1b85ae76f667` | `d16dfb56b4de4f31a8083546d758fa0f28cab7b211fe040cb9d8605b99531761` | MISMATCH | current Oracle worktree path; not a historical checkout |
| LR/v3-multilingual/prereg.json:15 | OQ/score.py | sha256 | `b565e4750c8c12b956335e4c3973527e5cd8fa7f48666899511305243cd7f9e2` | `—` | NOT FOUND | current Oracle worktree path; not a historical checkout |
| LR/v3-multilingual/prereg.json:6 | OW/DroppyCodeTests/OracleLiveRuns.swift | sha256 | `c876f77c6b33778815dad9ea6e0076d750701e4112d17606509e8218ef86bbcd` | `—` | NOT FOUND | superseded pre-amendment hash, historical reference only |
| LR/v0-current/prereg.json:15 | LR/tools/score.py | sha256 | `b565e4750c8c12b956335e4c3973527e5cd8fa7f48666899511305243cd7f9e2` | `3f862d63606172438cf691873c460d595c902ca1b9e237633cb2745bd097cfea` | MISMATCH | retained scorer copy; original OQ/score.py absent |
| OW/DroppyCode/Resources/Oracle/requalify-v1.json:2606 | OQ/corpus.json | sha256 | `fcf7859c905b16f1425cd3c4a73091594515672b58ed5aaf7e9210fc8e4441aa` | `fcf7859c905b16f1425cd3c4a73091594515672b58ed5aaf7e9210fc8e4441aa` | MATCH |  |
| OW/DroppyCode/Resources/Oracle/requalify-v1.json:2607 | OQ/labels.json | sha256 | `2fb797f55c479d307e7df3e82445eda45a8f5b3dc83c54a7e532a2877e333644` | `2fb797f55c479d307e7df3e82445eda45a8f5b3dc83c54a7e532a2877e333644` | MATCH |  |

### Exceptions

- **MISMATCH** `V1/live_pilot.py` against `V1/live-approved-Sentinel_cdbbf2b01e848191b8a7af343da340fa/authorization-and-runtime.json:21` (sha256). Expected `a6a7315714f2922dd53de78f7691aa72fe8c1abdcce9f30f739a7525de813c76`; actual `5b5169ff98839a910199f3a1f21f3a364a86779319d3548c8affaaf10dd2d5af`. .
- **MISMATCH** `OW/DroppyCode/Core/Models/HydraOracle.swift` against `OQ/prereg.json:12` (sha256). Expected `7640916a22ab6f8ff11883ff321aed32aa2937247855e3b7e4e4737499ab9673`; actual `3c989ea408a4080b541de485e2a63b6711af33e42fb2fd5af871a7d9a19399b2`. current Oracle worktree path; not a historical checkout.
- **MISMATCH** `OW/DroppyCode/Resources/Oracle/oracle_laya_worker.py` against `OQ/prereg.json:14` (sha256). Expected `5bd792eb6f2ec10565cc7a60798a19566b901463241c8b686b7f1b85ae76f667`; actual `d16dfb56b4de4f31a8083546d758fa0f28cab7b211fe040cb9d8605b99531761`. current Oracle worktree path; not a historical checkout.
- **MISMATCH** `OW/DroppyCode/Core/Models/HydraOracle.swift` against `LR/v0-current/prereg.json:12` (sha256). Expected `7640916a22ab6f8ff11883ff321aed32aa2937247855e3b7e4e4737499ab9673`; actual `3c989ea408a4080b541de485e2a63b6711af33e42fb2fd5af871a7d9a19399b2`. current Oracle worktree path; not a historical checkout.
- **MISMATCH** `OW/DroppyCode/Resources/Oracle/oracle_laya_worker.py` against `LR/v0-current/prereg.json:14` (sha256). Expected `5bd792eb6f2ec10565cc7a60798a19566b901463241c8b686b7f1b85ae76f667`; actual `d16dfb56b4de4f31a8083546d758fa0f28cab7b211fe040cb9d8605b99531761`. current Oracle worktree path; not a historical checkout.
- **MISMATCH** `OW/DroppyCode/Core/Models/HydraOracle.swift` against `LR/v1-runtime020/prereg.json:12` (sha256). Expected `7640916a22ab6f8ff11883ff321aed32aa2937247855e3b7e4e4737499ab9673`; actual `3c989ea408a4080b541de485e2a63b6711af33e42fb2fd5af871a7d9a19399b2`. current Oracle worktree path; not a historical checkout.
- **MISMATCH** `OW/DroppyCode/Resources/Oracle/oracle_laya_worker.py` against `LR/v1-runtime020/prereg.json:14` (sha256). Expected `5bd792eb6f2ec10565cc7a60798a19566b901463241c8b686b7f1b85ae76f667`; actual `d16dfb56b4de4f31a8083546d758fa0f28cab7b211fe040cb9d8605b99531761`. current Oracle worktree path; not a historical checkout.
- **MISMATCH** `OW/DroppyCode/Core/Models/HydraOracle.swift` against `LR/v2-typed/prereg.json:12` (sha256). Expected `7640916a22ab6f8ff11883ff321aed32aa2937247855e3b7e4e4737499ab9673`; actual `3c989ea408a4080b541de485e2a63b6711af33e42fb2fd5af871a7d9a19399b2`. current Oracle worktree path; not a historical checkout.
- **MISMATCH** `OW/DroppyCode/Resources/Oracle/oracle_laya_worker.py` against `LR/v2-typed/prereg.json:14` (sha256). Expected `5bd792eb6f2ec10565cc7a60798a19566b901463241c8b686b7f1b85ae76f667`; actual `d16dfb56b4de4f31a8083546d758fa0f28cab7b211fe040cb9d8605b99531761`. current Oracle worktree path; not a historical checkout.
- **MISMATCH** `OW/DroppyCode/Core/Models/HydraOracle.swift` against `LR/v3-multilingual/prereg.json:12` (sha256). Expected `7640916a22ab6f8ff11883ff321aed32aa2937247855e3b7e4e4737499ab9673`; actual `3c989ea408a4080b541de485e2a63b6711af33e42fb2fd5af871a7d9a19399b2`. current Oracle worktree path; not a historical checkout.
- **MISMATCH** `OW/DroppyCode/Resources/Oracle/oracle_laya_worker.py` against `LR/v3-multilingual/prereg.json:14` (sha256). Expected `5bd792eb6f2ec10565cc7a60798a19566b901463241c8b686b7f1b85ae76f667`; actual `d16dfb56b4de4f31a8083546d758fa0f28cab7b211fe040cb9d8605b99531761`. current Oracle worktree path; not a historical checkout.
- **MISMATCH** `LR/tools/score.py` against `LR/v0-current/prereg.json:15` (sha256). Expected `b565e4750c8c12b956335e4c3973527e5cd8fa7f48666899511305243cd7f9e2`; actual `3f862d63606172438cf691873c460d595c902ca1b9e237633cb2745bd097cfea`. retained scorer copy; original OQ/score.py absent.

Missing referenced originals: `OW/DroppyCodeTests/OracleLiveRuns.swift` and `OQ/score.py`. Their hash comparisons are NOT FOUND, including the superseded amendment reference. No archived file was substituted silently.

Document validation: NOT RUN; assigned to the lead. This inventory performed only source inspection, requested source hashing, package metadata reads, and hardware reads.

### Retained requalification tools protocol

`LR/tools/prereg.json` retains the same historical protocol. Its locally retained scorer is also changed.

| Source | File | Expected SHA-256 | Actual SHA-256 | Status |
| --- | --- | --- | --- | --- |
| LR/tools/prereg.json:17 | `~/.local/scratch/laya-requal-2026-09-30/tools/corpus.json` | `fcf7859c905b16f1425cd3c4a73091594515672b58ed5aaf7e9210fc8e4441aa` | `fcf7859c905b16f1425cd3c4a73091594515672b58ed5aaf7e9210fc8e4441aa` | MATCH |
| LR/tools/prereg.json:22 | `~/.local/scratch/laya-requal-2026-09-30/tools/labels.json` | `2fb797f55c479d307e7df3e82445eda45a8f5b3dc83c54a7e532a2877e333644` | `2fb797f55c479d307e7df3e82445eda45a8f5b3dc83c54a7e532a2877e333644` | MATCH |
| LR/tools/prereg.json:12 | `~/.local/scratch/droppy-code-oracle-wt/DroppyCode/Core/Models/HydraOracle.swift` | `7640916a22ab6f8ff11883ff321aed32aa2937247855e3b7e4e4737499ab9673` | `3c989ea408a4080b541de485e2a63b6711af33e42fb2fd5af871a7d9a19399b2` | MISMATCH |
| LR/tools/prereg.json:8 | `~/.local/scratch/droppy-code-oracle-wt/DroppyCodeTests/OracleLiveRuns.swift` | `c9a47d19bda90179c2e52a338c7713fa064f2eaae8d10c980a0923cadf70060d` | `—` | NOT FOUND |
| LR/tools/prereg.json:14 | `~/.local/scratch/droppy-code-oracle-wt/DroppyCode/Resources/Oracle/oracle_laya_worker.py` | `5bd792eb6f2ec10565cc7a60798a19566b901463241c8b686b7f1b85ae76f667` | `d16dfb56b4de4f31a8083546d758fa0f28cab7b211fe040cb9d8605b99531761` | MISMATCH |
| LR/tools/prereg.json:15 | `~/.local/scratch/laya-requal-2026-09-30/tools/score.py` | `b565e4750c8c12b956335e4c3973527e5cd8fa7f48666899511305243cd7f9e2` | `3f862d63606172438cf691873c460d595c902ca1b9e237633cb2745bd097cfea` | MISMATCH |
| LR/tools/prereg.json:6 | `~/.local/scratch/droppy-code-oracle-wt/DroppyCodeTests/OracleLiveRuns.swift` | `c876f77c6b33778815dad9ea6e0076d750701e4112d17606509e8218ef86bbcd` | `—` | NOT FOUND |
