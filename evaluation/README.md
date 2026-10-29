# Search evaluation

Run from the project root:

```bash
python -m evaluation.run
python -m unittest discover -s tests -p test_semantic_workflow.py -v
```

The evaluation embeds the functions in `src/main.py`, `src/database.py`, and
`src/semantic_search.py` into a temporary SQLite database. It does not modify
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
