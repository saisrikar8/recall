# Recall

Recall is a local command-line search engine for Python code. Index a file or project, then describe the behavior you are looking for in natural language. Recall returns matching functions with similarity scores, file paths, line numbers, and short source previews.

It uses Python's AST to extract functions, `nomic-ai/CodeRankEmbed` to generate embeddings, and SQLite to store and rank the indexed code. No database server or hosted search API is required.

## Requirements

- Python 3.10 or newer and pip.
- Internet access for installing dependencies and downloading the embedding model on first use.
- Disk space for PyTorch, the model weights, and your local index. The model runs on your machine and can make initial indexing and fresh CLI startup slow.

The model loader uses `trust_remote_code=True`, allowing model-provided Python code to run. Review the model repository before using it in a sensitive environment.

## Installation

### Install the v0.1.1 release

Download `recall_search-0.1.1-py3-none-any.whl` from the
[GitHub release](https://github.com/saisrikar8/recall/releases/tag/v0.1.1).
For a command available outside a project virtual environment, install with pipx:

```bash
pipx install /absolute/path/to/recall_search-0.1.1-py3-none-any.whl
recall --help
```

On macOS, you can install pipx with `brew install pipx`, then run
`pipx ensurepath` and restart your terminal. The model stack has been verified
with Python 3.13. If pipx selects another interpreter that cannot install the
pinned dependencies, select Python 3.13 with `pipx install --python python3.13`
followed by the wheel path.

The wheel installs Recall and its dependencies; the model weights are downloaded
separately on first use. Installing a GitHub release does not require a PyPI
release of Recall.

### Develop from source

Clone the repository and install into a virtual environment:

```bash
git clone https://github.com/saisrikar8/recall.git
cd recall
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
recall --help
```

On Windows PowerShell, activate with `.venv\Scripts\Activate.ps1` instead. The `dev` extra adds Alembic and the build tool; for runtime dependencies alone, use `python -m pip install -e .`.

The distribution is named `recall-search`; the installed command is `recall`. Editable installation means changes to Python source take effect without reinstalling. Reinstall after changing dependencies or package metadata.

## Upgrading to v0.1.1

Stop any running `recall serve` worker with Ctrl-C. Download the v0.1.1 wheel,
then replace your pipx installation:

```bash
pipx install --force /absolute/path/to/recall_search-0.1.1-py3-none-any.whl
```

If your existing pipx environment uses an incompatible Python version, include
`--python python3.13`. For an editable source installation, update your checkout
and rerun `python -m pip install -e ".[dev]"` in its virtual environment.
Restart `recall serve` after the upgrade. The package update preserves the saved
index and does not perform a database schema migration. Version 0.1.1 pins the
model stack to avoid the removed attention-mask API used by newer Transformers.
See [the changelog](CHANGELOG.md) for release changes.

## Quick start

For any installation, index a Python project and search it:

```bash
recall index -f /absolute/path/to/project
recall search -q "parse command line arguments" --collection /absolute/path/to/project
```

If you cloned the repository, run these commands from its root to try the included example:

```bash
recall index -f ./example
recall search -q "add up the prices in a shopping cart"
```

Recall uses the same configured database for indexing and search, regardless of your working directory.

Indexing creates missing tables for a new database. Search requires an index to have been created first. The example contains `greet`, `calculate_total`, and `find_long_words`; ranking depends on the embedding model and threshold.

To index your own project and search only that collection:

```bash
recall index -f /absolute/path/to/project
recall search -q "retry failed requests" --collection /absolute/path/to/project
```

A collection is the resolved directory root passed to indexing. When indexing one file, its parent directory is the collection root. Without `--collection`, search considers all indexed collections.

## Faster repeated commands

On macOS and Linux, start the optional embedding worker in a separate terminal:

```bash
recall serve
```

Wait for `Recall embedding worker ready`, then run index and search commands in
another terminal. They automatically use the worker, which loads the model once
and retains it in memory. The first worker startup still pays model import and
loading costs. Stop it with Ctrl-C to release its memory. Restart the worker after
upgrading Recall so it uses the new code and dependencies.

The worker uses a user-only Unix socket, not a network port. Requests are processed
serially. Without a worker, commands fall back to loading the model in their own
process. `RECALL_EMBEDDING_SOCKET` can select an alternate socket path; set it to
the same absolute path in both terminals. Windows currently uses local inference
without the worker. Help and argument parsing do not import model dependencies.

## Profiling time and memory

Use a small, explicitly selected folder first:

```bash
recall index -f ./homework --exclude ./homework/.grader --profile 2> recall-profile.log
```

Profiling performs real indexing and updates the selected index. Use
`RECALL_DB_PATH=/absolute/path/to/temporary-profile.db` to keep a diagnostic run
separate from your normal index. A fresh database measures embedding work;
reindexing unchanged files normally skips it. `--profile` cannot be combined
with `--dry-run`.

Each `[profile]` line on stderr is a JSON record with the stage, PID, elapsed
seconds, starting/ending RSS, and sampled peak RSS in MiB. Stages include model
import/loading, individual embeddings, functions (name, line, character count),
file processing, and the overall indexing operation. Source text is not logged,
but paths and function names can be sensitive.

With a current `recall serve` worker, profiled clients automatically request
worker-side measurements; returned records are marked `process: worker` and
carry the worker PID. Start the worker with `recall serve --profile` to also
measure its one-time startup. Restart older workers before profiling.

RSS is sampled every 50 ms and can miss brief spikes. It measures process
resident memory, not all GPU/Metal allocations or total system memory. Peaks
from overlapping stages and processes should not be summed; elapsed times
include profiling overhead. These diagnostics help locate the expensive input
or stage; they do not impose memory limits or establish the cause of a spike.

## Commands and options

```bash
recall index -f ./project
recall index -f ./project/module.py
recall search -q "parse command line arguments"
recall search -q "open a database session" --limit 10 --min-threshold 0.3
recall search -q "extract Python functions" --collection ./src
```

| Argument | Meaning | Default |
| --- | --- | --- |
| `index` / `search` / `serve` / `list` / `remove` | Required operation | — |
| `-f`, `--file` | Python file or directory to index | Current directory |
| `-q`, `--query` | Nonempty natural-language search query | Required for search |
| `-l`, `--limit` | Maximum number of results, at least 1 | `5` |
| `--min-threshold` | Minimum cosine similarity, from -1 to 1 | `0.4` |
| `--collection` | Exact indexed root to search | All collections |
| `-h`, `--help` | Show command help | — |

Higher scores indicate greater vector similarity; they are not confidence percentages. Raising the threshold removes weaker matches. Lowering it can reveal useful matches as well as noise. Search can return fewer than the requested limit or print `Function not found`.

Results show a score, relative file path, start/end lines, function name, collection root, and up to six source lines. Reindex after editing files to keep locations and results current.

## Browsing and removing indexed code

These commands query SQLite without loading the embedding model:

```bash
recall list
recall list --tree
recall list --collection /absolute/path/to/project
recall list --collection /absolute/path/to/project --file module.py
```

`list` shows collection roots. Selecting a collection shows its files; selecting
a file shows its functions with IDs and line ranges. `--tree` expands all three
levels, optionally restricted to a collection or file. File selectors are paths
relative to the collection root (absolute paths inside it also work).
You can omit `--collection` and pass a direct file path instead:

```bash
recall list --file ./homework/hw03.py
recall remove --file /absolute/path/to/homework/hw03.py
recall remove --file ./homework/hw03.py --function pingpong
```

Without `--collection`, relative paths resolve from your current directory.
Recall matches saved index records even if the source file has been deleted.
If the same file is indexed under multiple collections, specify `--collection`
to select one; ambiguous lookups do not delete anything.

Look up a function directly by its listed ID, without a file or collection:

```bash
recall list --function-id 42
recall search --function-id 42
```

Both show the function's absolute path, line range, and full indexed source.
ID lookup does not load the model or calculate a similarity score. IDs identify
current database records and may change after reindexing. Use `--function-id`
on its own, without a query, file, collection, function name, or tree flag.

Remove saved index records at any level:

```bash
recall remove --collection /absolute/path/to/project
recall remove --collection /absolute/path/to/project --file module.py
recall remove --collection /absolute/path/to/project --file module.py --function parse
recall remove --function-id 42
```

Removal takes effect immediately and does not change source files. Use a function
ID from `list` when multiple functions have the same name. `--function-id` is a
standalone selector and cannot be combined with other selectors. Removing a
function invalidates its file's saved hash so reindexing restores the file's
functions. Removing files or collections also allows a later reindex to restore
them; removal is not a permanent exclusion rule.

## How indexing works

1. Discover `.py` files recursively. Automatic directory classification skips version-control internals, known tool caches, marked Python/Conda environments, installed Python package layouts (including custom folders such as `.grader`), recognized Node dependencies, and selected framework/build output with corroborating project markers. macOS application bundles are skipped when their bundle structure is present. Discovery finishes before deletion cleanup begins.

   Skipped directories report a human-readable reason and rule ID on stderr, including during `--dry-run`. Directory symlinks are not traversed. Explicit exclusions and existing Git ignore rules also apply. Ordinary folders named `build`, `target`, `vendor`, `Library`, or `tests` are not excluded solely by name. Detection is conservative and heuristic, not a guarantee that every dependency folder will be recognized. Explicitly selected files remain eligible subject to explicit exclusions and Git ignore rules.
2. Read each file and calculate a SHA-256 content hash. Files whose saved hash is unchanged are skipped without generating new embeddings.
3. Detect the source encoding and parse Python's abstract syntax tree. Extract regular and async functions, including methods and nested functions, with their source, docstrings, and line ranges.
4. Embed each extracted function's source using CodeRankEmbed. Save its vector and model name alongside its metadata.
5. Replace records for changed files and remove records for deleted files during a directory reindex. A single-file update preserves sibling records. Read or parse failures preserve previously indexed contents for that file and record an error.

The command prints counts of new, changed, unchanged, deleted, and failed files. Incremental skipping operates at the file level: changing a file regenerates embeddings for its extracted functions.

## How search works

1. Generate one embedding for the query, with the model's code-search query prefix.
2. Select stored functions using the current default embedding model, optionally restricted to one collection.
3. Compare the query vector with stored vectors through a SQLite callback that calculates cosine similarity. The callback does not load or invoke the model.
4. Filter by threshold, sort by score, and return the highest-ranking functions up to the limit.

Embeddings are stored as JSON arrays. Similarity is computed across candidate rows; Recall currently has no approximate nearest-neighbor index. Missing, incompatible, or invalid vectors are excluded. The active search path is semantic; the older keyword helper is not used by the CLI.

## Database storage

`src/database.py` chooses its location when imported:

- `RECALL_DB_PATH`, if set, selects a database file. Use an absolute path for consistent behavior across working directories.
- Otherwise, `platformdirs` selects the user's application data folder. On macOS this is `~/Library/Application Support/recall/index.db`.

The parent directory is created automatically. The database stores project roots, file metadata, extracted source code, and embeddings. Treat it as a copy of the indexed source when deciding what to share or commit.

**Migration configuration:** `alembic.ini` still points to `index/index.db`. An environment override changes application connections, but does not change Alembic's target. Before migrating, explicitly configure Alembic to use the same database as the CLI.

`migrations/data/platform.py` is a one-time utility to copy the old database into the default user data location with SQLite's backup API. It refuses to overwrite an existing destination and leaves the source intact. After copying, leave `RECALL_DB_PATH` unset to use the default user data location.

## Repository layout

| Path | Purpose |
| --- | --- |
| `pyproject.toml` | Package metadata, dependencies, build configuration, and the `recall = "src.main:main"` entry point |
| `src/__init__.py` | Marks the source directory as a regular Python package |
| `src/main.py` | Argument parsing, file discovery, AST extraction, incremental indexing, and result formatting |
| `src/index_management.py` | Collection/file/function browsing and index-only removal |
| `src/database.py` | Database path selection, engine/session setup, persistence helpers, and ranked search |
| `src/models.py` | SQLAlchemy definitions for collections, files, and functions |
| `src/semantic_search.py` | Lazy model imports, worker routing, embedding helpers, and vector similarity |
| `src/embedding_service.py` | Optional persistent local model worker over a Unix socket |
| `example/example.py` | Small functions for trying indexing and search |
| `tests/` | Database, extraction, CLI, and embedding workflow tests |
| `evaluation/` | Query judgments, model-based evaluation runner, saved results, and methodology |
| `migrations/versions/` | Alembic schema revisions |
| `migrations/data/backfill_embeddings.py` | Manually populate missing embeddings in an existing schema |
| `migrations/data/platform.py` | Copy a legacy index into the user data folder |
| `migrations/env.py`, `alembic.ini` | Alembic environment and database configuration |

The schema has three levels: a **Collection** owns files under an absolute project root; a **File** stores its relative path, content hash, indexing timestamp, and last error; a **Function** stores its name, source location, docstring, source text, vector, and model identifier. File paths are unique within a collection, and function line ranges are unique within a file.

## Tests and retrieval evaluation

Run from the repository root with the development environment active:

```bash
python -m unittest discover -s tests -v
```

Some CLI tests start separate processes and load the real model, so the complete suite can take several minutes. For focused embedding lifecycle and search logic checks using controlled vectors:

```bash
python -m unittest discover -s tests -p test_semantic_workflow.py -v
```

Evaluate retrieval quality with the actual model:

```bash
python -m evaluation.run
```

The evaluation builds a temporary SQLite index of Recall's own source and writes `evaluation/results.json`. Its 15 cases include 12 queries with expected functions and three unrelated queries. It reports Hit@5 and unrelated queries returning matches at thresholds 0.3, 0.4, and 0.5. This small development set is not an independent benchmark; rerun after source changes and add queries from your own projects. See [the evaluation guide](evaluation/README.md).

## Schema migrations and backfilling

Fresh databases get their tables through the index command. `create_all()` does not upgrade existing tables. Alembic revisions handle schema changes; the backfill separately generates embeddings for rows where the embedding is missing.

Before migrating an existing database, back it up and verify that Alembic's configured URL points to the intended file. Do not blindly apply the initial revision to tables already created by the application; the existing schema and Alembic revision history need to agree first.

Once the schema and migration history are aligned, the normal sequence is:

```bash
alembic upgrade head
python -m migrations.data.backfill_embeddings
```

The backfill uses the application's database selection, whereas Alembic currently uses `alembic.ini`. Confirm both targets match. The backfill loads missing embeddings and commits at the end; it is not a batched migration. These tools are run from the source checkout and are not included in the installed `src` package.

## Building a release

Update `version` in `pyproject.toml`, then build:

```bash
python -m build
```

This creates a wheel and source archive in `dist/`. Install the specific wheel produced by your build, for example:

```bash
python -m pip install --upgrade dist/recall_search-0.1.1-py3-none-any.whl
```

Package installation does not move or upgrade the database. The model stack is pinned to the tested versions of sentence-transformers, Transformers, and PyTorch. CodeRankEmbed uses a legacy attention-mask API that newer Transformers releases removed; update these pins only after testing actual code and query embeddings. Other dependencies are currently unconstrained.

## Current scope

Recall indexes Python functions rather than arbitrary text, whole classes, or other programming languages. It does not execute the indexed source during AST extraction, or watch files automatically. Reindex explicitly after changes. Search quality depends on the model, source context, and threshold. Without the optional worker, model loading can dominate short CLI runs.
