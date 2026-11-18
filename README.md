# Recall

Recall is a local search engine for source code, text, Markdown, PDFs, and images. Index a file or project, then describe the behavior you are looking for in natural language. Recall returns matching files, classes, functions, and passages with similarity scores, source locations, and short previews.

It uses language-aware parsers to extract functions and methods, `nomic-ai/CodeRankEmbed` to generate embeddings, and SQLite to store and rank the indexed code. No database server or hosted search API is required.

## Requirements

- Python 3.10 or newer and pip. Recall can index other programming languages without installing their compilers.
- Internet access for installing dependencies and downloading the embedding model on first use.
- Tesseract for automatic PDF/image OCR (`brew install tesseract` on macOS). Code and plain-text indexing do not need Tesseract.
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

On Windows PowerShell, activate with `.venv\Scripts\Activate.ps1` instead. The `dev` extra adds build/test tools; for runtime dependencies alone, use `python -m pip install -e .`.

The distribution is named `recall-search`; the installed command is `recall`. Editable installation means changes to Python source take effect without reinstalling. Reinstall after changing dependencies or package metadata.

## Local UI

From your source checkout, start the barebones browser interface:

```bash
.venv/bin/python -m src.main ui
```

With an updated installation, use `recall ui`. It opens
`http://127.0.0.1:8765` in your browser. Keep the terminal running; press Ctrl+C
to stop. Use `--port 8766` if the default port is occupied, or `--no-browser`
to open the address yourself.

Paste a local file or folder path to add/update it, preview the files that will
be scanned, search across all collections or one collection, and browse saved
files and entities. Results include saved source previews and an **Open file**
button that uses your default application. Removal affects only the index;
original files remain on disk. Reindexing restores removed items.

The UI uses the same database and `RECALL_DB_PATH` override as the CLI. Operations
show progress and run one at a time, keeping the local model warm between calls.
First use may download the model. PDFs and images automatically receive visual embeddings, with OCR selected per page or image region as needed.
Search uses text/OCR, independent keyword matches, and ColSmol visual retrieval. No additional web framework
or frontend build is needed. The interface listens only on your laptop.

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

For any installation, index a supported code project and search it:

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

Indexing initializes or upgrades the recognized database schema before processing files. Search requires an index to have been created first. The example contains `greet`, `calculate_total`, and `find_long_words`; ranking depends on the embedding model and threshold.

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
| `-f`, `--file` | Supported source file or directory to index | Current directory |
| `-q`, `--query` | Nonempty natural-language search query | Required for search |
| `-l`, `--limit` | Maximum number of results, at least 1 | `5` |
| `--min-threshold` | Minimum text cosine similarity, from -1 to 1 | `0.4` |
| `--collection` | Exact indexed root to search | All collections |
| `-h`, `--help` | Show command help | — |

Higher scores indicate greater vector similarity; they are not confidence percentages. The threshold filters semantic text candidates. Exact keyword evidence can still return a result below that cutoff. Visual retrieval uses a separate ColSmol MaxSim score distribution and never applies the text cutoff. Search can return fewer than the requested limit.

Results show a score, relative path, line range or PDF page, entity name, collection root, and up to six preview lines. Reindex after editing files to keep locations and results current.

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
recall list --function-id e:42
recall search --entity-id 42
```

Both show the published entity's path, location, and saved body chunks (or overview). New listings use `e:<id>` references; plain numeric `--function-id` values refer only to legacy function records, avoiding ID collisions during migration.
ID lookup does not load the model or calculate a similarity score. IDs identify
current database records and may change after reindexing. Use `--function-id`
on its own, without a query, file, collection, function name, or tree flag.

Remove saved index records at any level:

```bash
recall remove --collection /absolute/path/to/project
recall remove --collection /absolute/path/to/project --file module.py
recall remove --collection /absolute/path/to/project --file module.py --function parse
recall remove --function-id e:42
```

Removal takes effect immediately and does not change source files. Use a function
ID from `list` when multiple functions have the same name. `--function-id` is a
standalone selector and cannot be combined with other selectors. Removing a
function invalidates its file's saved hash so reindexing restores the file's
functions. Removing files or collections also allows a later reindex to restore
them; removal is not a permanent exclusion rule.

## Supported codebases

`recall index -f ./project` detects supported languages automatically; no project
configuration or language compiler is required. Existing search, listing, removal,
collection merging, incremental updates, and profiling apply to these files.

| Language / project style | Extensions |
| --- | --- |
| Python | `.py` |
| JavaScript, Node, React | `.js`, `.mjs`, `.cjs`, `.jsx` |
| TypeScript, React / Next.js | `.ts`, `.mts`, `.cts`, `.tsx` |
| Java | `.java` |
| Go | `.go` |
| Rust | `.rs` |
| C | `.c` |
| C++ and headers | `.cpp`, `.cc`, `.cxx`, `.h`, `.hpp`, `.hh`, `.hxx` |
| C# / .NET | `.cs` |
| Ruby | `.rb` |
| PHP | `.php` |
| Kotlin | `.kt`, `.kts` |
| Swift | `.swift` |
| Bash | `.sh`, `.bash` |
| Lua | `.lua` |

Tree-sitter grammars ship with the pinned parser pack; parsing does not download
additional grammars. Parsers import only when a non-Python source is extracted.
C/C++ headers use the C++ grammar. Anonymous callbacks without a discoverable
assigned name are not separate results. The layered index distinguishes same-line functions using separate entity keys and chunks. The old standalone `process_file()` adapter still groups identical line ranges for compatibility with its legacy output format.
Extraction does not compile, type-check, or execute source, and parser support
can lag newer language syntax. CodeRankEmbed remains the embedding model;
retrieval quality has not been separately benchmarked for every new language.

## Reusable extraction API

Extraction is separate from discovery, embedding inference, database writes, and
CLI argument parsing. Indexing persists the returned structure in Silver and builds Gold search representations.
`recall index` now accepts code, `.txt`, `.md`, `.markdown`, and `.pdf` files.

```python
from src.extraction import extract_document, iter_documents

# Reading notes does not load the embedding model or open the database.
document = extract_document("notes.md")
for unit in document.units:
    print(unit.name, unit.start_line, unit.end_line, unit.text)

# Mixed-format discovery uses the existing directory filters.
for document in iter_documents("./coursework"):
    print(document.path, document.format, len(document.units))
```

Documents include a SHA-256 hash, extracted units, and warnings. Code units
preserve function names, docstrings, source, and line ranges. Text units are
bounded by character count and retain offsets and lines. Markdown ATX headings
create sections; headings inside fenced code blocks are not treated as sections.
PDF units retain one-based page numbers; their character offsets and lines refer
to extracted page text, not visual coordinates. Normal indexing keeps native PDF text, selects full-page or region OCR when
needed, and merges recognized text with the native text. Visual indexing still
renders every page independently of that OCR choice. PNG, JPEG, WebP, TIFF, and BMP images also get OCR; multi-frame images
retain page numbers. Pages without recognized text still receive visual vectors.
Encrypted PDFs require an unlocked copy. The lower-level `extract_document()`
PDF helper retains its text-only default; pass `visual=True` for the indexing OCR
behavior. Image extraction always uses OCR. Missing OCR dependencies or a failed
page fail that file visibly and retain its previous published generation.

Default limits are 20 MiB per input file, 4,000 characters per text/Markdown/PDF
unit, and 1,000 PDF pages. Override them through `extract_document()` keyword
arguments. Extraction retains complete code functions; the indexing pipeline subsequently divides their source into passages of at most 3,000 characters before embedding. File reads are
bounded, but parser decompression and in-memory extraction are not hard process
memory limits. Text supports UTF-8 (including BOM) and BOM-marked UTF-16; Python
uses its declared source encoding; other source languages support UTF-8 and BOM-marked UTF-16. Other encodings raise explicit errors.

`iter_documents()` yields one document at a time and stops on extraction errors
so a future application can choose retry/skip behavior. The indexing service
accepts a `report` callback for progress messages. It does not import the CLI;
`main.py` re-exports the previous Python helpers for compatibility.

## How indexing works: layered processing

```text
Existing original file + hash (source layer, no archived copy)
                   |
Extraction -> Entities -> Chunks (Silver, persisted before inference)
                   |
Embeddings + SQLite FTS5 entries (Gold)
                   |
Atomic publication -> Search
```

1. Complete filtered discovery first. Automatic directory classification, explicit
   exclusions, and existing Git ignore rules determine the workload.
2. Read and hash a bounded byte stream. An unchanged file is skipped only if its
   active extraction, chunking version, and model configuration are current.
3. Save an extraction attempt and persist the file/class/function/section hierarchy
   and bounded chunks before calling the model. Line/page locations remain attached.
4. Embed saved chunks with file and parent context. Save each completed vector;
   retries reuse persisted Silver and already completed compatible vectors.
5. Publish the completed generation and its FTS records in a transaction. Search
   filters to active, complete extractions. Keep the previous generation visible
   if extraction or inference fails. Successful replacement removes older derived
   generations; this is not a file-history feature.
6. Commit each file independently. An interrupted run preserves completed files.
   One disk-backed index writer is allowed at a time; a second run reports that
   indexing is already active. Search can continue against published data.
7. Reconcile deletions within the requested directory, preserving sibling records
   when indexing a subfolder or single file. Directory filtering completes before
   this cleanup, so a traversal failure does not look like mass deletion.

Before publication, a detected change in source size/mtime is checked against
its current hash. Changed or missing sources fail that attempt and can be retried
on the next index command; there is no filesystem snapshot or background watcher.
Model-only rebuilds reuse saved Silver. Extractor/chunker version changes rebuild
Silver as well. Model keys identify configuration, but the current HF model's
upstream revision is not pinned; exact reproduction requires pinning it too.

This is medallion-inspired processing with originals in place, not an immutable
Bronze archive or a lakehouse. No duplicate copy of the original file is stored.

## How search works

Generate query embeddings for the available text and visual models, compare
against published vectors, and apply the requested text cosine threshold. SQLite FTS5 also admits matches containing
all meaningful query terms independently of that threshold. Text and keyword
ranks are fused. Explicit image/diagram requests fuse text and visual ranks;
ordinary questions search text and visual channels together. Their leading text
ranking gets more weight; visual channels no longer each reserve a top-result
slot. Agreement between visual models can surface OCR-free content when no
exact keyword, filename, or numbered-reference match exists. Explicit diagram queries retain text/document
rank fusion. A simple query heuristic favors
file/class overviews when those levels are explicitly requested. Results are
grouped by entity to reduce repeated hits from long functions.

When query terms identify a source line inside a retrieved passage, return nearby
lines and retain the original chunk range for provenance. This lexical refinement
is not a guarantee that the selected line semantically answers the question.
Open the saved entity to inspect more context. PDF results retain page attribution.

Legacy function records remain searchable until their files are reindexed into
the new representation. They are then replaced by published entities/chunks.
There is no approximate nearest-neighbor index; SQLite scans compatible candidate
vectors. Retrieval quality and adaptive-level selection still need evaluation
across real mixed-file queries. No LLM-generated answer is produced.

## Database storage

`src/database.py` chooses its location when imported:

- `RECALL_DB_PATH`, if set, selects a database file. Use an absolute path for consistent behavior across working directories.
- Otherwise, `platformdirs` selects the user's application data folder. On macOS this is `~/Library/Application Support/recall/index.db`.

The parent directory is created automatically. The database stores project roots, file metadata, extracted source code, and embeddings. Treat it as a copy of the indexed source when deciding what to share or commit.

**Migration configuration:** the application and Alembic both use `src.settings`, including `RECALL_DB_PATH`. Runtime migration files are included in the package. Recognized legacy layouts are validated before adoption; unfamiliar or partial schemas are rejected. Existing disk databases get a SQLite backup before an automatic upgrade/adoption.

`migrations/data/platform.py` is a one-time utility to copy the old database into the default user data location with SQLite's backup API. It refuses to overwrite an existing destination and leaves the source intact. After copying, leave `RECALL_DB_PATH` unset to use the default user data location.

## Repository layout

| Path | Purpose |
| --- | --- |
| `pyproject.toml` | Package metadata, dependencies, build configuration, and the `recall = "src.main:main"` entry point |
| `src/__init__.py` | Marks the source directory as a regular Python package |
| `src/main.py` | Argument parsing, command dispatch, and result formatting |
| `src/extraction.py` | Model-free code/text/Markdown/PDF extraction with source locations and explicit errors |
| `src/indexing.py` | Code extraction-to-embedding adapter, collection merging, incremental persistence, and progress reporting |
| `src/code_languages.py` | Source-language registry and lazy Tree-sitter function/method extraction |
| `src/discovery.py` | Filesystem traversal, directory decisions, explicit exclusions, and Git ignore checks; independent of database and model imports |
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

## Layered schema and migrations

The active pipeline uses `File -> Extraction -> Entity -> Chunk -> Embedding`.
Entities have parent relationships within an extraction. Chunks carry ordered
text, context, hashes, and line/page locations; embeddings carry model configuration,
input hashes, dimensions, and vectors. Only one complete extraction per file is
active. Failed candidates retain an error and reusable Silver; successful updates
retain only the current derived generation.

The old `Function` table remains for legacy reads and maintenance scripts. New
indexing does not write it. IDs from the new schema use the `e:` namespace in
listings; `--entity-id` provides direct access without a semantic query.

`recall index` handles fresh initialization and recognized legacy upgrades through
Alembic. It adopts unversioned schemas only after validating their layout and
backs up existing disk databases before changes. Backup files sit next to the
original database as `index.db.before-schema-<timestamp>.db`; you manage their
retention. Your original source files are not copied or migrated.

For manual maintenance from a checkout, use the same `RECALL_DB_PATH` as the app:

```bash
alembic current
alembic upgrade head
```

Manual Alembic upgrades do not run the application's automatic backup/adoption
helper. Do not stamp arbitrary databases to bypass validation. The old
`migrations.data.backfill_embeddings` helper applies only to legacy function rows;
reindex files to build Silver/Gold. No model needs to run during schema migration.

## Building a release

Update `version` in `pyproject.toml`, then build:

```bash
python -m build
```

This creates a wheel and source archive in `dist/`. Install the specific wheel produced by your build, for example:

```bash
python -m pip install --upgrade dist/recall_search-0.1.1-py3-none-any.whl
```

Package installation does not move or upgrade the database. The model stack is pinned to the tested versions of sentence-transformers, Transformers, and PyTorch. ColSmol requires Transformers 5.15 for correct adapter-weight mapping. CodeRankEmbed has a scoped compatibility helper for its legacy encoder attention-mask call; both models are tested with the pinned runtime. Pillow and PyMuPDF are included for image/PDF processing; the renderer is constrained to the tested 1.25–1.26 series.

## Current scope

Recall indexes supported code, plain text, Markdown, PDFs, and common image formats.
Code has file/class/function structure, source passages, and overviews; other
formats use sections/pages/passages. Anonymous callbacks, newer grammar features,
notebooks, Vue/Svelte components, filesystem watching, and automatic
mobile sync are not implemented. Classes and files use structural overviews,
not LLM summaries. OCR and visual models can miss handwriting, small text, and diagram details; visual embeddings do not guarantee handwriting transcription. Original-file history and lakehouse infrastructure are not
part of this pipeline. Reindex explicitly after edits. Keep the optional worker
running to avoid repeated model startup.

## Automatic OCR and visual indexing

Index as usual with `recall index -f /path/to/documents` or the UI; no OCR or
visual flag is required. Reindex existing PDF collections once after upgrading.
The pipeline detects the missing visual generation and processes unchanged PDFs
too. Future unchanged runs skip OCR and inference. OCR/model configuration
changes invalidate only the relevant saved stages.

Every PDF page/image has ColSmol token vectors anchored to its saved page entity.
The model is `vidore/colSmol-256M` at revision
`c79b633e17e060cc109b11aa2bf92a1517d3bd6f`, with base
`vidore/ColSmolVLM-Instruct-256M-base` pinned to
`99ca96f1f6b95b3a69e6abef74a2416cb738fed0`. The same trained encoder handles
queries. The base and adapter are both pinned; a temporary local configuration
selects the pinned base and PIL image processor without changing Hugging Face's
cached files. Text and visual vectors have separate model keys and storage.
Visual matching uses MaxSim: each query token finds its best document token,
and those similarities are summed. These scores are not cosine scores or
confidence percentages. Fusion compares ranks across the two channels. Results identify keyword, semantic, visual, or
hybrid matches. Original files and page numbers remain the source of truth.

Images render one page at a time, longest edge up to 2,000 pixels; OCR processes
a bounded number of page copies concurrently, and visual
inputs preserve aspect ratio with a longest edge up to 1,280 pixels before the
ColSmol processor applies the selected visual detail budget (512 pixels by default). Multi-frame images and PDFs allow at most 1,000
pages; images above 40 megapixels are rejected. Both local models stay cached in
a long-running UI process, so the first operation loads them and memory usage
includes both models. OCR defaults to English; handwriting and fine diagram
recognition remain limited. No original images or page renders are copied into
the database. A failed OCR/visual stage does not publish a partial index.

The first visual indexing operation downloads ColSmol base and adapter weights; document contents
stay local. Tesseract must be installed separately. Restart a running UI or
embedding worker after updating the source or installed package.

### PDF processing order and batches

Directory indexing handles non-PDF files first. Changed PDFs wait for a final
PDF phase: extraction/OCR is persisted for each PDF, then visual pages from the
whole PDF group are embedded in batches of up to four. Text embeddings and
publication follow, with each PDF becoming searchable only when its own stages
are complete. This groups model work instead of alternating OCR, visual
inference, and text inference for every PDF. Unchanged PDFs still skip all work.

The queue holds file IDs, paths, and hashes, not PDF bytes or full-size page
images. Rendering remains page-at-a-time, with a bounded OCR worker pool; only four bounded page images
wait for a visual model call. A batch failure retries individual pages to isolate
failures. Source changes or failed pages preserve that file's previous published
index; successful files still finish. Saved OCR and completed vectors are reused
on retry. The same ordering applies through the UI and CLI, without new flags.

### Parallel OCR

OCR automatically uses up to four page workers, limited to half the available
CPU cores (at least one). Each worker runs a Tesseract subprocess with
`OMP_THREAD_LIMIT=1` and `OMP_NUM_THREADS=1` to avoid multiplying internal threads.
Page rendering stays on one thread, with no shared PyMuPDF objects. At most one
page copy per worker is queued; results retain their original page order.

Override the worker budget when starting Recall if needed:

```bash
RECALL_OCR_WORKERS=2 recall ui
```

The override accepts 1–8 workers, capped by available CPUs. More workers can use
more RAM and make the laptop less responsive. Existing unchanged files do not
need reindexing just for this scheduling change. Restart the UI for it to apply.
An eight-page slide test on the development laptop took 4.04s with one worker,
2.18s with two, and 1.42s with four; output text matched across runs. These are
single-run local timings, not a general performance guarantee.

### ColSmol storage and acceleration

Visual embeddings are token matrices in `visual_embeddings`, stored as packed
little-endian float16 blobs with shape checks, model revision, and input hash.
Their chunk foreign key cascades on removal. Scoring streams document matrices
from SQLite and computes MaxSim in token blocks, keeping only a bounded top set.
Old single-vector text/CLIP rows are not interpreted as ColSmol embeddings.
The additive migration preserves existing text indexes; visual files must be
reindexed to generate ColSmol vectors.

ColSmol automatically selects Metal when available, otherwise CPU. It uses SDPA
attention, float16 on Metal and float32 on CPU. Inference processes two pages at
a time on Metal or one on CPU inside the final PDF group; the group queue holds at most four aspect-preserving images. The text
encoder remains CodeRankEmbed. OCR, saved-stage retries, and per-file atomic
publication continue to work with the new visual model.

### Faster ColSmol processing

The default `fast` profile uses one 512×512 visual input per page, rather than
splitting an upscaled page into many visual crops. OCR independently retains its
2,000-pixel rendering budget, and native PDF text is preserved. This keeps text
retrieval detailed while reducing the work of visual retrieval. It can lose small
handwriting or diagram details; it is not a guarantee of equal quality on all files.

Metal uses half precision, optimized SDPA attention, and two-page batches; CPU
keeps full precision and single-page inference. A visual-only configuration change
reuses saved OCR and unchanged text vectors. PDF/image text embeddings cover
actual OCR/text passages, not generic file/page placeholders. Visual vectors remain
attached to page entities. Interrupted upgrades discard only stale, unpublished
visual vectors for the old configuration.

Restart the UI after updating code and reindex once. Existing saved OCR and text
vectors are reused where compatible; your saved index is not cleared. The visual
model key includes the profile, so incompatible visual encodings are not mixed.

For extra visual detail at a substantial speed/storage cost, start with:

```bash
RECALL_VISUAL_DETAIL=balanced RECALL_OCR_WORKERS=8 recall ui
```

The `balanced` profile keeps image splitting and a 1,024-pixel processor edge.
Changing profiles requires reindexing visual files. The default fast profile
reduced typical landscape slide matrices from 870 to 75 rows; balanced produced
341 rows. Query scoring uses the same MaxSim method for all profiles. See
[evaluation/visual/FAST_RESULTS.md](evaluation/visual/FAST_RESULTS.md) for measured
speed and retrieval results, including the limits of that small evaluation.

### Conditional OCR per page

Normal indexing now inspects native words and their positions, image placement,
and text quality before OCR. It preserves native text and always generates a
visual embedding, with these OCR choices:

- Readable text pages: skip OCR and skip OCR rasterization.
- Scanned/outlined pages with no usable body text: OCR the page, even when a
  page number or footer is selectable.
- Mixed pages: OCR substantial image regions not already represented by usable
  text; merge overlapping regions and deduplicate repeated raster tiles.
- Broken text layers: OCR the page instead of indexing replacement glyphs or
  repeated `(cid:...)` sequences.
- Blank pages: retain their page identity and visual embedding without OCR.

Shallow decorative banners with existing native titles are excluded from image
region OCR. This is a conservative geometry heuristic, not perfect image/text
recognition. Tiny labels and vector handwriting added to an otherwise readable
page may be missed; the visual channel still receives the whole page. Tesseract
also remains limited for handwritten mathematics. Native and OCR lines are
merged without exact duplicate lines. `extractions.configuration` stores
`ocr_summary` and `ocr_pages` reasons for inspection and regression reports.

The OCR policy version invalidates older PDF/image extraction stages once, so
reindex after upgrading. Missing Tesseract is an error only when a page actually
needs OCR; readable native-text PDFs no longer require it. Parallel OCR and final
PDF visual batching remain bounded and unchanged.

### Photos and illustrations

Indexing PDFs and images also creates lightweight whole-page CLIP scene vectors.
Explicit requests for photos, pictures, illustrations, paintings, or screenshots
prioritize this channel alongside ColSmol and extracted text. Ordinary topic and
question searches also consider scene evidence, so an image need not contain
readable OCR text or be requested with the word “image.” Diagram-only queries
retain their text/document fusion. The first use downloads the pinned CLIP
model; subsequent calls reuse its cache.

After updating, restart Recall and reindex your folders once. Compatible saved
OCR, text embeddings, and ColSmol vectors are reused. Your index is not cleared.
See [visual retrieval experiments](evaluation/VISUAL_IMPROVEMENTS.md) for measured
results, limitations, and optional crop/reranker trials.

### Desktop app

The Electron app includes a library dashboard, a system-wide quick-search
shortcut, indexing progress, and shared original-file previews for PDFs,
Markdown, code, text, and images. From `desktop`, run `npm ci` then `npm start`.
It uses the project's Python environment and your existing index. See
[desktop setup and toolkit](desktop/README.md) for controls, preview behavior,
and Mac build instructions. `npm run dist:mac` builds a DMG with Python, model
dependencies, and OCR bundled. On Apple Silicon the output is arm64; this default
build is ad-hoc signed and not notarized. Model weights download on first use.

See [CS61A relevance checks](evaluation/CS61A_RESULTS.md) for the comparison,
filename, numbered-question, generated-file filtering, and result-grouping fixes.

### Collection-wide evaluation and indexing updates

The current collection benchmark has 100 cases per indexed collection, with
source evidence and tuning/evaluation partitions. See
[evaluation results](evaluation/collections/RESULTS.md) for before/after relevance,
latency, dataset limitations, and indexing measurements.

The desktop now shows real file-completion progress for each folder, including
nested folders, and adds published files to the library during indexing. New
unpublished files remain hidden until ready; older published versions remain
available during updates.

Text indexing uses small length-grouped batches (four on Metal/CUDA, two on CPU),
with bounded inference and per-file atomic publication. Restart a separately
running `recall serve` worker to enable its new batch protocol; older workers
remain compatible through single-item requests.

Natural-language questions without exact keyword/filename/reference evidence can
use the pinned `cross-encoder/ms-marco-MiniLM-L6-v2` reranker on at most 25 text
candidates. It downloads on first use, stays local, and is preloaded by the desktop.
Exact lookup and explicit visual paths retain their existing behavior. A failed
reranker falls back to base ranking. A bounded 64 MiB cache speeds published-vector
cosine scoring and invalidates on database changes.

Exact filename lookups bypass the embedding models, including image files with
no OCR text; bare function names retain entity/semantic retrieval.
