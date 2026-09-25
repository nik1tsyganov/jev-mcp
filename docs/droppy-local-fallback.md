# Droppy Code: the Jev + Laya managed entry

This records the pre-split combined router (before 2026-09-25).

Status: implemented and checked locally on 2026-09-21. The macOS Release build,
162 Node tests and two installer safety tests passed. A fresh scratch installation
answered real local requests without a Jev key; a network-blocking check recorded
zero cloud attempts. The new app has not been installed or relaunched, and its
settings controls have not been exercised in a running app. No release or MR
publication is claimed.

Droppy Code gains a managed entry named **Jev + Laya** that bundles two
providers behind one decision call:

- **Jev** — the remote TypeSafe System One model this server already exposes.
- **Laya** — a local decision runtime installed explicitly with the companion installer
  and run on-device. The app does not bundle or automatically install it.

## Credentials

- The Jev key is **optional**. Droppy Code stores it in the macOS Keychain.
- App-scoped credentials are the only source the managed entry reads: it ignores
  legacy credential files such as `~/.config/typesafe/env.sh` and an inherited
  `TYPESAFE_API_KEY`. A key that works for this repo's MCP registrations is not
  silently reused by the app.
- An explicit Jev request fails when no key is saved.

## Modes

The entry carries a **Local only** control beside the default automatic mode.

| Situation | Behaviour |
| --- | --- |
| Auto, key saved | The current combination policy is preserved: Jev is authoritative; an enabled registered profile may answer locally on an exact question match; failure and low-confidence cases fall back to one Jev call, and shadow sampling is unchanged. |
| Auto, no key | Supported local decisions are answered by Laya and no Jev request is made. Explicit Jev requests fail. |
| Local only | No Jev request is made, including fallback and shadow. Supported local decisions use Laya; anything else fails with a clear error. |

The same profile gates this repository already enforces still apply: a
registered profile must be enabled, its checkpoint and revision must match the
installed runtime, and its probability threshold governs whether a local answer
is authoritative. Evidence and identity gates are not relaxed for the app path.

`decision_browser_action` is exempt from local routing: it asks Jev explicitly
on every call, so Auto without a saved key and Local only both fail it with a
clear error. Laya never answers it — in replay the pinned checkpoint's
question-head budget rejected all 8 browser decision requests before inference.

A local result no registered profile covers is **generic**: unqualified, and not
evidence of parity with Jev. Calibrated packs (`packs/*.json`) and CONCLAVE
remain Jev-only. Laya is not a substitute for every Jev task — the managed entry
covers the decisions its profiles and runtime support, and the rest either use
Jev (with a key, in auto) or fail.

## Setup

Run from the `jev-mcp` checkout:

    python3 scripts/install-decision-runtime.py --download-laya

- Requires Node >= 20 and Python >= 3.11.
- Installs to `~/Library/Application Support/Droppy Code/decision-runtime` by
  default, with `launch.mjs` as the launcher the app invokes.
- Downloads and installation happen only during this explicit setup step, never
  during a prediction.
- The installer ships no copied owner credentials and no owner-override
  profiles. A new install starts with an empty profile registry; the two
  bookmark-topic profiles in `config/decision-profiles.json` are this machine's
  owner-override adoption, not defaults for new users.

Without an explicit profile, `decision_bookmark_topic` uses its frozen v2
questions as an unqualified general request when no v2 profile is registered.
If a profile exists, its gates still apply. An explicitly named missing profile
fails locally; the convenience tool does not invent an approved profile.

## Errors

- **Runtime unavailable** — the local runtime is not installed, cannot start, or
  fails a call: the request fails with a clear error. In Local only mode there
  is no remote fallback to fail over to.
- **Unsupported input** — an invalid question shape, truncated input, unsupported language, or
  calibrated-pack question fails with a
  clear error rather than silently routing to Jev when remote use is off or no
  key is saved.
- **Explicit Jev without a key** — fails; the error names the missing app
  credential, not a file path.

## Privacy boundary

The local worker processes state and questions on this Mac without network
access. Routing metadata is logged outside the runtime directory under
`~/.claude/docs/telemetry`; that log excludes raw state and question text. Remote use is optional and happens only
when a key is saved and the mode permits it — auto mode, never Local only.

## Changing modes

The Local only control and the Keychain credential live in the app's settings
for the Jev + Laya entry. Changes apply to new decisions; an installed local
worker is reused, not reinstalled.

## Historical measurements stay historical

The 400-case v2 confirmation figures quoted in the README (Jev 94.5%, Laya
74.75%, combination 92.0%, accepted-local 88.53% against a 95% target) describe
this machine's owner-override adoption and remain FAILED qualification results.
They are not a promise about a fresh install and must not be presented to a new
user as the managed entry's expected accuracy.
