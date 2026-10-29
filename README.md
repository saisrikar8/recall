# Recall

Recall is a local command-line search engine for Python code. Index a file or project, then describe the behavior you are looking for in natural language. Recall returns matching functions with similarity scores, file paths, line numbers, and short source previews.

It uses Python's AST to extract functions, `nomic-ai/CodeRankEmbed` to generate embeddings, and SQLite to store and rank the indexed code. No database server or hosted search API is required.

## Requirements

- Python 3.10 or newer and pip.
- Internet access for installing dependencies and downloading the embedding model on first use.
- Disk space for PyTorch, the model weights, and your local index. The model runs on your machine and can make initial indexing and fresh CLI startup slow.

The model loader uses `trust_remote_code=True`, allowing model-provided Python code to run. Review the model repository before using it in a sensitive environment.

## Installation

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

## Quick start

**Current path compatibility:** search still checks for `index/index.db` relative to the working directory, although database connections now default to a user data folder. Until that check is updated, run the following commands from the repository root and explicitly select the old database location:

```bash
export RECALL_DB_PATH="$PWD/index/index.db"
recall index -f ./example
recall search -q "add up the prices in a shopping cart"
```

For PowerShell, set `$env:RECALL_DB_PATH = Join-Path $PWD 'index/index.db'` before running the commands.

Indexing creates missing tables for a new database. Search requires an index to have been created first. The example contains `greet`, `calculate_total`, and `find_long_words`; ranking depends on the embedding model and threshold.

To index your own project and search only that collection:

```bash
recall index -f /absolute/path/to/project
recall search -q "retry failed requests" --collection /absolute/path/to/project
```

A collection is the resolved directory root passed to indexing. When indexing one file, its parent directory is the collection root. Without `--collection`, search considers all indexed collections.

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
| `index` / `search` | Required operation | — |
| `-f`, `--file` | Python file or directory to index | Current directory |
| `-q`, `--query` | Nonempty natural-language search query | Required for search |
| `-l`, `--limit` | Maximum number of results, at least 1 | `5` |
| `--min-threshold` | Minimum cosine similarity, from -1 to 1 | `0.4` |
| `--collection` | Exact indexed root to search | All collections |
| `-h`, `--help` | Show command help | — |

Higher scores indicate greater vector similarity; they are not confidence percentages. Raising the threshold removes weaker matches. Lowering it can reveal useful matches as well as noise. Search can return fewer than the requested limit or print `Function not found`.

Results show a score, relative file path, start/end lines, function name, collection root, and up to six source lines. Reindex after editing files to keep locations and results current.

## How indexing works

1. Discover `.py` files recursively, skipping `.git`, `.venv`, `venv`, `__pycache__`, and `.idea`. Discovery finishes before deletion cleanup begins.
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

**Known integration gaps:** `src/main.py` still checks the old relative `index/index.db` before searching, and `alembic.ini` still points there. An environment override changes application connections, but does not change Alembic's target. Consequently, running the installed command from arbitrary directories is not fully supported yet. The quick start above keeps these paths aligned.

`migrations/data/platform.py` is a one-time utility to copy the old database into the default user data location with SQLite's backup API. It refuses to overwrite an existing destination and leaves the source intact. Moving the database alone does not fix the search path check.

## Repository layout

| Path | Purpose |
| --- | --- |
| `pyproject.toml` | Package metadata, dependencies, build configuration, and the `recall = "src.main:main"` entry point |
| `src/__init__.py` | Marks the source directory as a regular Python package |
| `src/main.py` | Argument parsing, file discovery, AST extraction, incremental indexing, and result formatting |
| `src/database.py` | Database path selection, engine/session setup, persistence helpers, and ranked search |
| `src/models.py` | SQLAlchemy definitions for collections, files, and functions |
| `src/semantic_search.py` | Lazy model loading, code/query embedding helpers, and pure vector similarity |
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
python -m pip install --upgrade dist/recall_search-0.1.0-py3-none-any.whl
```

Package installation does not move or upgrade the database. Dependencies currently have no version constraints, so a fresh installation can resolve different versions from an existing development environment.

## Current scope

Recall indexes Python functions rather than arbitrary text, whole classes, or other programming languages. It does not execute the indexed source during AST extraction, watch files automatically, or honor `.gitignore` as a discovery rule. Reindex explicitly after changes. Search quality depends on the model, source context, and threshold, and model loading can dominate short CLI runs.
