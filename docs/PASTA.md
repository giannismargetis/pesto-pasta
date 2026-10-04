# PASTA — voice commands

```
utterance ─► router ─► grammar (─► LLM, optional) ─► for each step:
             (wake      (typed intents)               ground on live desktop
              word)                                    ─► safety gate ─► [confirm] ─► execute ─► verify
```

## Where models are (and are not) used

| Stage | Method | Why |
|---|---|---|
| Dictation vs command | explicit rule (mode + wake word) | the boundary must be predictable; guessing from imperative verbs executed dictated sentences |
| Understanding | deterministic bilingual grammar, 0.06 ms p50 | covers the action space with 99.5 % of the labelled corpus; testable; no hallucinated actions |
| Unparsed utterances | optional local LLM (Ollama), JSON-schema constrained to the action table | widens understanding for odd phrasings; **always** asks for confirmation |
| Grounding | fuzzy matching against live windows, installed Start-menu apps (localised names), known sites, known folders | the world, not the parser, decides what "Discord" or "αριθμομηχανή" refers to |
| Verification | independent observation (Win32 window state, Core Audio, clipboard sequence number, process exit code, browser title, UI Automation) | success must be observed, not assumed |

The PASTA v2 design advertised a 2B-parameter decision model ranking keyword-generated
candidates. In practice the model never loaded (missing `transformers` architecture),
and the keyword mock that replaced it could only choose among candidates produced
by the same keywords, so it added nothing a grammar could not do transparently.

## Action space (`pasta/intents.py`)

open · focus · close · minimize · maximize · restore · show_desktop · list_windows ·
open_url · web_search (web / YouTube / Wikipedia / Maps) · browser (tabs, back,
forward, reload) · press · edit (copy, paste, cut, undo, redo, select all, save) ·
type_text · scroll · volume (mute, unmute, up, down, set %) · media · open_folder ·
find_file · click (named button/link via UI Automation) · run_command (allow-list) · stop.

Deleting files, power actions (shut down, restart, sign out) and sending messages
are deliberately outside the action space; such requests are answered with "didn't
understand" (tested in the out-of-scope split).

## Safety (`pasta/safety.py`)

| Risk | Examples | Runs automatically when |
|---|---|---|
| READ | list windows | confidence ≥ 0.80 |
| LOW | open, focus, search, volume, scroll | confidence ≥ 0.80 |
| MEDIUM | type, keys, click, close one window/tab | confidence ≥ 0.95 (closing windows: always asks by default) |
| HIGH | terminal commands, closing several windows, Alt+F4-like keys | never — always asks |

Below 0.50 PASTA refuses ("not sure what you meant"). LLM-derived steps always ask.
Permission categories can be switched off entirely (Settings → Commands).
Confirmation: Enter / Esc (captured system-wide only while the question is open),
or say "ναι" / "όχι"; it times out to *cancel* after 10 s.

Shell commands are tokenised into argv and matched against a per-program argument
pattern, then run without a shell: `&&`, pipes, redirections and quoting cannot
smuggle anything through (tested with injection attempts).

## Verification outcomes

`verified` (effect observed), `failed` (error, or effect demonstrably absent — the
plan stops; later steps are marked skipped), `unverified` (input delivered, effect
not observable, e.g. media keys). The HUD and the Commands page show which.

## Multi-step commands

"Άνοιξε το Chrome, μπες στο YouTube και παίξε ένα πασχαλινό τραγούδι" is split at
commas/conjunctions only where a new command starts, then folded into what the user
means: one `web_search(query, site=youtube, browser=chrome)` step. Each step is grounded
right before it runs. A clause the grammar cannot parse rejects the whole utterance —
PASTA never runs half a request.

## Known limitations

* Live execution success (as opposed to understanding) has not yet been measured
  on a desktop task suite.
* Browser verification uses the window title; reading the address bar via UI
  Automation would be stronger.
* `run_command` runs in the user's home folder, not "the current project".
* Elevated (administrator) windows cannot receive synthetic input from a
  non-elevated process; PASTA reports this as a failure. Running PASTA elevated is
  not recommended.
