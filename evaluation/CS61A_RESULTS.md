# CS61A search relevance follow-up

These are development checks against the user's existing CS61A collection, not
held-out accuracy estimates. No index rebuild, source changes, or database
cleanup was performed. Two queries came from the user's reported failures; eight
additional queries were selected after inspecting the indexed CS61A files.

## Reported failures

| Query | Before | After, first desktop result |
|---|---|---|
| append vs extend | Generated Gleam `append` function, followed by unrelated images | `2.4 - Mutable Data.md`, “Mutable Containers” |
| what was question 9 in the ants project | `tests/q09.py`, followed by unrelated images | `ants.py`, `TankAnt` |

For the second query, `q09.py` repeatedly references `TankAnt`; the implementation
and its methods already exist in the index. Retrieval now follows that relation
and retains the test path as provenance. This is an implementation reference,
not a reconstructed assignment statement or a generated answer.

## Changes

- Comparisons ignore connecting words such as “vs” and “between” in keyword
  matching. All-term BM25 hits are preferred; weaker partial-term matches can
  supplement semantic candidates. Numeric task labels do not become generic
  single-number keyword matches when the query also contains words.
- Current directory-exclusion decisions apply to older indexed records during
  retrieval too. Previously indexed generated build files stop appearing without
  deleting them or modifying original files.
- Ordinary searches give text ranking more weight. Visual channels do not each
  receive a guaranteed top-result slot. Agreement between both visual models can
  still surface OCR-free content when there is no exact keyword/file/reference
  match; this remains a heuristic, not calibrated multimodal confidence.
- Test files remain searchable but are downweighted unless tests are requested.
  Comparison queries give matching explanatory documents a modest preference.
- Exact filename/stem matches admit file overviews independently of cosine cutoffs.
- Numbered test-file lookup links dominant named class/constructor references to
  existing declarations and child methods in the same project. It avoids choosing
  arbitrary unrelated projects with the same numbered question. It currently
  handles the supported numbered filename patterns and named symbols, not a
  complete dependency graph or arbitrary task numbering conventions.
- Desktop/web results group code and note chunks by file; PDF/image pages retain
  page-level identity. CLI entity results remain available.

## Checks

Using the actual desktop search operation, all ten queries in
`cs61a_queries.json` had the labeled file/entity first. The broader eight include
higher-order functions, linked-list digits, coin-change code, an exact filename,
mutable-data notes, environment diagrams, and accumulate.

The existing small PDF regression sets scored 12/14 math Hit@1 and 13/14 Hit@5,
and 3/4 slide Hit@1 and Hit@5. The slide baseline copy predates the later scene
index upgrade. Those checks do not establish general quality.

Across the now-larger live library, the OCR-free matrix image ranked first for
“What are P and C equal to?” and “handwritten matrices P and C on graph paper”.
It ranked 11th for “linear algebra”; this is worse than the previous forced visual
promotion and exposes the remaining tradeoff between broad visual and text search.

A trial of the existing MiniLM text cross-encoder did not reliably improve the
reported cases and was not enabled. The embedding models were not replaced, and
no new model download or reindex is required by these changes.

## Reproduce

From the repository root with the relevant collection already indexed:

```sh
python -m evaluation.cs61a_run --collection /path/to/cs61a
```

The read-only runner writes result metadata to
`/tmp/recall-cs61a-evaluation.json`. Use `--output` to change that destination.
