# Collection search and indexing evaluation

300 source-grounded questions: 100 for each collection present in the frozen index. Searches ran globally across all three collections, using the desktop's file/page grouping. Original files and the live index were not changed.

## Relevance and latency

Hit@1 means the expected file/page was first; Hit@5 means it appeared in the first five. These are development results, not an independent benchmark.

| Collection | Before Hit@1 | After Hit@1 | Before Hit@5 | After Hit@5 | Warm median before → after |
|---|---:|---:|---:|---:|---:|
| cs61a | 86% | 91% | 92% | 95% | 1.580s → 0.128s |
| example_pdfs | 92% | 92% | 98% | 98% | 1.750s → 0.142s |
| Downloads | 58% | 83% | 61% | 85% | 1.602s → 0.153s |

Natural-language reranking adds work: final p95 latency was approximately 0.74s for CS61A, 0.76s for Downloads, and 0.20s for PDFs. Models were warmed before timing; app startup/model downloads are separate. Baseline ran with two CPU threads; some exploratory work overlapped parts of that run, so these observations are not a controlled hardware-isolation study.

## Judgment protocol and limits

- CS61A includes 32 authored concept questions, 43 docstring-derived prompts, and 25 filename lookups. The latter categories are easier than arbitrary natural-language search. Identical filenames/docstrings can have multiple valid expected files.
- PDF questions are generated from page topics and titles, with exact supporting page text. Exact repeated source phrases were used to add valid alternative pages. They often reuse source vocabulary and should not be treated as a broad semantic-understanding test.
- Downloads contains one image. Its set has 40 paraphrases describing that same image and 60 cross-collection distractors. Image-only Hit@1 increased from 8/40 to 29/40; distractor Hit@1 increased from 50/60 to 54/60. The distractors reuse questions from the other two sets: there are 240 distinct query strings across 300 cases. There is **no independent held-out image subject**, and the 100 questions are not 100 independent visual examples.
- The tuning/evaluation split groups questions by their seed source file. CS61A has 32 tuning and 68 evaluation questions; PDFs have 60/40. The grouped evaluation subset scored CS61A 63/68 → 66/68 Hit@1 (65/68 → 67/68 Hit@5), and PDFs 38/40 → 38/40 Hit@1 (40/40 Hit@5 in both).
- Alternative answers, duplicated content, earlier project checks, and the one-image Downloads set limit independence. Some questions overlap earlier development topics. This is not a blind externally judged test.
- One unsupported mutable-default-argument prompt was replaced during tuning with a source-supported mutable-list comparison. The corrected baseline query was rerun; source-only judgment audits were applied to both baseline and final results.
- Ranking changes were chosen from tuning cases. Remaining failures are preserved in final-results.json rather than removed from the set. Some intended-file judgments remain narrower than a human relevance judgment; further manual review is appropriate.

CS61A concept questions (separate from easier docstring and filename prompts) improved from 21/32 to 25/32 first-result hits.

## Changes retained

- Exact filename lookups bypass embedding models entirely, including OCR-free image filenames. Bare function names retain semantic/entity search.
- A bounded 64 MiB published-vector cosine cache avoids reparsing stored vector JSON for every query. It invalidates on index/database changes, including external writes, and does not change persistent embeddings.
- Natural handwriting/page-appearance descriptions and explicit image requests can use the scene model. This improves retrieval of the OCR-free image without inserting arbitrary image slots into all searches.
- A small pinned text cross-encoder reranks a bounded shortlist for ambiguous natural-language questions. Exact keyword, filename, numbered-reference, and explicit visual paths retain their existing handling. Failure falls back to base ranking with backoff.
- E5 document-vector trials did not improve the tuning subset enough and were not enabled. No large visual reranker was added to ordinary search.
- Text indexing batches are length-grouped, capped, and saved per batch. Compatible prior rows remain reusable, and a file becomes searchable only after its complete extraction is published. Default batch sizes are four on Metal/CUDA and two on CPU; RECALL_TEXT_BATCH_SIZE can override within bounds.

## Indexing benchmark

Four unchanged CS61A source files (hw02.py, hw03.py, ants.py, and Mutable Data notes) were re-embedded in disposable database copies using saved extraction output. The test generated 258 text vectors, excluded model-load time, and did not repeat OCR. It does **not** measure a complete fresh CS61A scan.

| Trial | Before | After | Calls before → after | Python peak RSS before → after |
|---|---:|---:|---:|---:|
| CPU, initial unsorted batch 8 (rejected) | 14.66s | 19.32s | 258 → 33 | 1389 → 2346 MiB |
| Metal, sorted batch 2 | 6.74s | 5.71s | 258 → 130 | 855 → 862 MiB |
| Metal, sorted batch 4 (selected) | 6.88s | 4.77s | 258 → 65 | 852 → 861 MiB |

The selected Metal trial reduced elapsed time by about 31%. A separate Metal check found cosine similarity above 0.999999 between single-item and batched embeddings for three representative inputs. RSS is Python process memory, not a complete GPU/unified-memory accounting. Hardware-enabled and restricted CPU runs are different environments and should not be compared directly. The CPU batch-8 attempt was slower and substantially larger; it was rejected.

## Live indexing interface

Folder totals include descendant files. Completion advances only after publication, an unchanged check, or a recorded failure. Failed files count as processed and retain a visible failure count. PDF preparation does not count as completed publication.

A real Electron test observed the first new file in the library while a larger file in a nested folder was still being processed.

The dashboard polls structured progress, shows overall/per-folder completion, and refreshes the library as files publish. Other windows receive library-change notifications. Pending unpublished files are omitted; existing published versions remain visible. Updates retain the selected preview and throttle library refreshes.

## Reproduce

```sh
python -m evaluation.collections.snapshot
RECALL_DB_PATH=/tmp/recall-collection-eval/snapshot.db python -m evaluation.collections.run --output /tmp/recall-results.json
```

Use --split tune or --split evaluation for a subset. Sets include local collection paths and source evidence. build.py/audit.py document source-derived construction for this three-collection snapshot; adapt them when collections change. summary.json and the raw result files retain all cases and timings.
