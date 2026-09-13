# AIRRA Eval Results (2026-09-13, hardened same day)

Real output from the existing harnesses in this directory — nothing here is
projected or hand-waved. Run the commands yourself to reproduce.

## Detection, retrieval, diagnosis, remediation

```
python -m tests.evals.benchmark
```

Corpus: 240 synthetic incidents (`dataset/incidents.jsonl`), 10 failure
archetypes, real `AnomalyDetector` / `calculate_hypothesis_confidence` /
`ActionSelector` — no live LLM calls, fully reproducible in CI.

**Hardened same day**: `_candidates()` used to hand the truth category 2
evidence items at relevance 0.9 and distractors 1 item at 0.55 — an
artificial tell the ranker could key off without doing real work. It now
draws the SAME evidence count for every candidate from the SAME relevance
band (0.60–0.85), seeded per-incident so a distractor's draw beats the
truth's roughly as often as it doesn't. `run_retrieval()` also now reports a
second, vector-only Recall@3/MRR with the deterministic service+metric bonus
removed, to show how much of the composite score the embedding model is
actually earning.

| Stage | Metric | Value |
|---|---|---|
| Detection | precision | 1.000 |
| Detection | recall | 0.721 (tp=173, fn=67) |
| Detection | false-positive rate | 0.000 (fp=0, tn=240) |
| Detection | compute p50 / p95 | 0.25ms / 0.48ms |
| Retrieval | Recall@3 (composite) | 1.000 |
| Retrieval | MRR (composite) | 1.000 |
| Retrieval | Recall@3 (vector-only) | 1.000 |
| Retrieval | MRR (vector-only) | 1.000 |
| Diagnosis | top-1 accuracy | **0.287** |
| Diagnosis | top-3 accuracy | 1.000 |
| Remediation | correct-action rate | 1.000 |
| Remediation | unsafe-action rate | 0.000 (0/240) |
| Remediation | policy-rejection rate | 0.000 |

**How to read these now:**
- **Diagnosis top-1 (28.7%) is the interesting, credible number** — with
  evidence quality equalized, the deterministic confidence formula's other
  inputs (category priors 0.55–0.85, anomaly strength) genuinely decide close
  calls, and a high-prior distractor legitimately beats a low-prior truth
  often enough to hold top-1 well under saturation. **Top-3 staying at 100%**
  is also credible and worth stating alongside it: the formula rarely loses
  the truth entirely, it just doesn't always rank it first — a fair, honest
  "narrows reliably, doesn't always nail the single answer" claim, and the
  same qualitative shape `learning_experiment.py` already showed (cold top-1
  10.8% / top-3 27.5%).
- **Retrieval is now verified, not just asserted, to be a real number**: with
  the 0.3 service-match + 0.2 metric-match bonus stripped out entirely,
  vector similarity alone still gets Recall@3/MRR to 1.000. That's not a
  gimme anymore — it means `all-MiniLM-L6-v2` genuinely separates these 10
  incident-archetype descriptions on semantics alone. Legitimate, resume-usable, but scoped: only 10 canonical patterns, synthetic descriptions,
  not a production-scale relevance-judged retrieval benchmark.
- **Remediation correct-action rate (100%) is expected, not hardened** — it's
  deterministic table lookup (`ActionSelector` mapping a category to an
  action), not an LLM guess, so 100% here means "the mapping code runs
  correctly," not "the system reasons well." Don't present it as a discovery.
  The **unsafe-action rate (0/240) and policy-rejection rate (0/240) are the
  honest headline** from this stage — they measure whether the policy engine
  ever lets a destructive action through or wrongly blocks a safe one,
  independent of whether the root-cause label was right.

## Learning loop (feedback improves diagnosis)

```
python -m tests.evals.learning_experiment
```

Deterministic 120/120 train/held-out split of the same corpus. This is the
strongest, least-gameable number of the whole eval suite — no saturation:

| Condition | Top-1 | Top-3 |
|---|---|---|
| Cold (no feedback) | 10.8% | 27.5% |
| Learned (49 verified patterns from 120 training incidents) | 10.8% | **75.8%** |

**Resume line**: *"Verified incident feedback improved top-3 root-cause
accuracy from 27.5% to 75.8% on a held-out set (top-1 unchanged — the +0.10
pattern-confidence boost moves the true cause into the top 3, not always to
rank 1)."* That parenthetical matters: state it, don't hide it — it's what
makes the number credible instead of suspicious.

## Adversarial safety

```
python -m tests.evals.security_benchmark
```

157 deterministic adversarial cases against the real `prompt_guard`,
`secret_redactor`, `PolicyEngine`, `sanitize_context_value` (RAG context
sanitization), and `ensure_action_approved` (the approval-bypass guard now
shared between `actions.py` and this harness — one choke point, not a
duplicated condition that could drift out of sync with the test):

| Control | Blocked |
|---|---|
| Direct prompt injection (10 patterns × 5) | 50/50 |
| Secret leakage before embedding (6 patterns × 5) | 30/30 |
| Unsafe action rejected by policy (5 cases × 4) | 20/20 |
| RAG-poisoning (poisoned historical incident context, 10 × 5) | 50/50 |
| Approval bypass (every non-APPROVED `ActionStatus`) | 7/7 |
| **Overall** | **157/157 (100%)** |

**Caveat, state it plainly**: this measures rule-based detection against a
*known* attack-pattern list, not adversarial robustness against novel
attacks — 100% here means "the regex/policy rules we wrote catch the attacks
we wrote them for," which is a meaningfully weaker claim than "AIRRA resists
prompt injection in general." Fine to report as "0 successful attacks across
157 known-pattern adversarial cases," not as a general security guarantee.
The approval-bypass check is closer to a real guarantee — it exercises the
actual production code path (`ensure_action_approved`), not a reimplementation
of it, so a regression there fails this suite, not just a copy of the logic.

## Live end-to-end timing (not from this harness — from live fault injection)

From the 2026-09-12/13 sessions running real chaos against a live stack
(`labs/integration/`, `labs/kubernetes/`), not synthetic:

- MTTD (poll-only): ~9-22s
- MTTR (inject → executed): ~29-50s
- Kind-lab crashloop: detection confidence 0.99 (all 3 statistical methods agreed)

These are real but were captured manually across a few live runs, not from a
repeatable scripted benchmark with named-stage timestamps (detect → diagnose →
approve → remediate → verify). Building that script is the next piece of
work, not done yet.

## What's still missing for a fully resume-ready AIRRA metrics story

1. Retrieval and remediation fixtures still saturate at 100% (only diagnosis
   was hardened this pass — Recall@3/MRR and correct-action rate need their
   own harder cases to be meaningful numbers rather than gimmes).
2. A scripted, repeatable MTTD/MTTR benchmark with per-stage timestamps
   (detect/diagnose/approve/remediate/verify), not manual live-session numbers.
3. A cross-project end-to-end scorecard chaining a real AI-Engineering-Platform
   fault through AIRRA's full pipeline into one table (depends on both
   projects' metrics work landing first).
