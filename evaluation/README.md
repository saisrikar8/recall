# Search evaluation

Run from the project root:

```bash
python -m evaluation.run
python -m unittest discover -s tests -p test_semantic_workflow.py -v
```

The evaluation embeds functions from the CLI, discovery, extraction, indexing,
database, and semantic-search modules into a temporary SQLite database. It does not modify
your saved index. The local model must be downloaded first.

`queries.json` contains 12 behavioral queries with expected file/function pairs
and three unrelated queries. Edit these judgments if multiple implementations
are reasonably relevant. `results.json` records the top five scores for each
query and summaries at thresholds 0.3, 0.4, and 0.5.

Hit@5 is the fraction of relevant queries whose expected function survives the
threshold and appears in the first five results. The no-match count reports how
many unrelated queries incorrectly return at least one result.

This is a small, hand-written development set, not an independent benchmark.
Do not assume a threshold chosen here generalizes to other repositories. Expand
it with real user queries and hold out some queries before further tuning.
Source changes can change the results; rerun the evaluation after changes.

The workflow tests use controlled vectors to test persistence, filtering, and
query-encoding counts without confusing model quality with software behavior.
The evaluation uses the actual model to assess retrieval quality separately.

Search a particular indexed root with:

```bash
python -m src.main search -q "retry failed requests" --collection ./project --min-threshold 0.3
```

`--collection` is the exact indexed root (relative paths are resolved), not a
prefix filter. Without it, all collections using the default model are searched.

The saved results predate the extraction refactor and are historical. Rerun the
evaluation to compare current code; expected symbols follow the new modules.

For the isolated text/visual PDF comparison, see [visual/README.md](visual/README.md).

## Local corpus pipeline regression

Run the full real-model pipeline against both PDF folders and the Recall source:

```bash
RECALL_OCR_WORKERS=8 python -m evaluation.pipeline_run --output /tmp/recall-corpus-check
```

Use a fresh output directory to measure a cold index; reusing it tests cached
updates. Select subsets with `--corpora math`, `--corpora slides`, or
`--corpora code`. Three separate databases keep the tests independent of the
normal saved index and prevent collection auto-merge from mixing datasets.
The command uses its own local encoder context rather than a running worker.
It does not modify the originals. Outputs include private indexed/extracted
content, so keep the output folder local.

The run indexes each corpus, tries the exploratory queries in
`pipeline_queries.json` (and existing code queries), then indexes again. It
checks discovered/indexed counts, per-page visual vectors, failed files,
unchanged source hashes, and repeat-run skips. Software failures cause a nonzero
exit. Query ranks and Hit@1/Hit@5 are recorded separately; these development
judgments are incomplete, contain related/duplicate notes, and are not an
independent accuracy benchmark. `ocr_pages` records the selected mode and reason
for every PDF page. Timings include model loading/cache state; memory is process
RSS and excludes Metal allocation.


## Per-collection search sets

See [collections/RESULTS.md](collections/RESULTS.md) for 100 cases per current
collection, source judgments, grouped partitions, raw baseline/final results,
latency, and a bounded indexing benchmark. Reproduce using
`python -m evaluation.collections.snapshot` and `python -m evaluation.collections.run`.
These source-derived development sets include easy lookup questions and a
single-image diagnostic set; they are not a blind external benchmark.
