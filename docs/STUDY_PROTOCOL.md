# Study protocol (thesis)

Working title (from the proposal): *Αντιληπτή Υστέρηση και Γνωστικός Φόρτος σε
Push-to-Talk Ελληνική Φωνητική Πληκτρολόγηση: Συγκριτική Μελέτη με Παραδοσιακό
Πληκτρολόγιο σε Ακαδημαϊκό Περιβάλλον.*

The software is built and instrumented; this document specifies the experiments
it supports. Nothing here reports results — no participant data exist yet.

## Refined research questions

The proposal bundles several questions. Measured system behaviour suggests
separating them into two experiments, because latency must be *manipulated*
(not just observed) to say anything about perceived latency:

**Experiment 1 — input modality** (`research/study/protocols/input_modality.json`)

| | Question | Primary measure |
|---|---|---|
| RQ1 | Do speed and accuracy of copying Greek academic sentences differ between keyboard and push-to-talk dictation? | WPM; normalised MSD error rate after correction |
| RQ2 | Does dictation change perceived workload? | raw NASA-TLX |
| RQ3 | How does hands-free (VAD) dictation compare with push-to-talk? | WPM, error rate, TLX, utterances per sentence |

**Experiment 2 — perceived latency** (`latency_perception.json`)

| | Question | Primary measure |
|---|---|---|
| RQ4 | At what total release→text latency does dictation stop feeling immediate? | per-trial perceived speed (1–7) vs *measured* latency |
| RQ5 | Does added latency increase workload or change behaviour? | raw NASA-TLX; utterance length; re-dictations |

Hypotheses (directional, to be pre-registered before data collection):
H1 dictation yields higher WPM than keyboard for Greek (Greek keyboard entry requires
frequent accent dead-keys); H2 post-correction error rate does not differ by more than
an equivalence margin to be fixed in advance (e.g. 2 percentage points); H3 VAD shows
more utterances per sentence than PTT (endpointing splits pauses); H4 perceived speed
decreases monotonically with latency, with the steepest drop between 0.3 s and 1 s
(cf. Card, Moran & Newell; Nielsen's 0.1 s / 1 s limits).

## Why the baseline latency matters

Added delay is applied *on top of* the system's own release→text latency, which must
be measured on the study machine first (`python -m research.latency_ab`; and from
`interactions.release_to_text_ms` during practice trials). With a ~0.3–0.6 s system
latency, the levels 0 / +300 / +700 / +1500 ms span roughly 0.4–2 s total. The
analysis always uses the **measured** total per trial, not the nominal level.

## Design

* Within-subjects; condition order counterbalanced with a balanced Latin square
  (Williams design: `research/study/protocol.py`, verified by tests).
* Phrases: 40 original Greek academic sentences (`research/study/phrases_el.txt`),
  7–13 words. Each participant gets a seeded, disjoint subset per condition, so no
  sentence repeats within a session and assignment is reproducible.
* Per condition: 2 practice + 8 measured trials (Exp. 1); 1 + 8 (Exp. 2).
* Language fixed to Greek in the study runner (removes language-ID errors as a
  confound; auto mode is evaluated separately offline).

## Procedure (per participant, ~45 min)

1. Consent, demographics (age, keyboard layout habits, prior dictation use, typing
   self-rating); optional baseline typing test.
2. Short microphone check: `python -m pesto devices`; quiet room, same headset for all.
3. `python -m research.study run --protocol input_modality --participant P01`.
   The runner shows instructions per block, practice, trials, and NASA-TLX after
   each block. Speech goes through the real PESTO pipeline into the trial text box.
4. Break, then Experiment 2 (or a separate session).
5. Short semi-structured interview (preferences, perceived delay, trust).

## Measures and where they come from

| Measure | Definition | Stored in |
|---|---|---|
| WPM | (\|T\|−1)/S·60/5, S from first input to "Next" | `trials.wpm` |
| Error rate | MSD(P,T)/max(\|P\|,\|T\|)·100, literal and case/punctuation-insensitive | `trials.msd_error`, `trials.cer` |
| Corrective effort | backspaces/deletes, keystrokes, utterances per trial | `trials` |
| ASR accuracy before correction | WER of each utterance vs the sentence (join `data_json.interaction_ids` → `interactions.text`) | `interactions` |
| System latency | release→text, speech-end→text, ASR, queue, injection | `interactions` |
| Perceived speed | 7-point, after each trial (Exp. 2) | `trials.data_json.perceived_speed` |
| Workload | raw NASA-TLX, all six subscales must be moved | `questionnaires` |

## Analysis plan

`python -m research.study analyze --protocol <name>` (code: `research/study/analysis.py`):
aggregate per participant × condition; Friedman (k ≥ 3) then Holm-corrected pairwise
Wilcoxon signed-rank with rank-biserial effect sizes; for Exp. 2, Spearman's ρ between
measured latency and rating plus the share of trials rated ≥ 5 per level. For the
thesis, complement with a cumulative-link mixed model (ordinal rating ~ latency +
(1|participant) + (1|sentence)) in R (`ordinal::clmm`); export the tables from SQLite.

## Sample size

With a within-subjects design and an expected medium-to-large effect for speed
(d_z ≈ 0.8), ~15 participants give ≈ 80 % power at α = .05 (paired test, Holm
across 3 comparisons needs ≈ 18–20). Treat N < 10 as a pilot.

## Threats to validity (and mitigations)

* **Copy task vs composition**: copying sentences favours dictation (no thinking
  about content). State it; optionally add a short composition task.
* **Reading-aloud effect**: participants read rather than formulate speech. Same.
* **Learning/fatigue**: counterbalancing + practice trials; breaks between blocks.
* **Hardware**: GPU load changes latency — close other GPU applications; telemetry
  records latency per trial, so outliers are visible.
* **Demand characteristics**: condition names are never shown to participants.
* **Hold threshold**: feedback appears 150 ms after the key press by design;
  report it as part of the interaction design.

## Ethics

Audio is processed locally; `experiment.save_audio` is off by default (enable only
with explicit consent, for later WER scoring). Participant IDs are pseudonymous
(P01…); store the ID↔name key separately. Follow the department's ethics procedure
before recruiting.
