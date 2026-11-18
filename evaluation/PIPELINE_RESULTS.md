# Conditional OCR pipeline regression

Real-model run against both local PDF folders and the Recall source. All indexes were isolated under `/tmp/recall-conditional-corpora`; the normal saved index and original files were not modified. ColSmol used the fast Metal profile, OCR allowed eight workers, and CodeRankEmbed handled text. Model files were cached locally; models were shared across the three corpus runs.

| Corpus | Files | PDF pages | Initial index | Unchanged repeat | Functional checks | Relevant result in top 5 |
|---|---:|---:|---:|---:|---|---:|
| Math notes (`example_pdfs_2`) | 20 | 132 | 214.17s | 0.89s | Pass | 13/14 |
| Astrobiology (`example_pdfs`) | 10 | 540 | 250.70s | 0.56s | Pass | 3/4 |
| Recall codebase | 65 | — | 57.61s | 1.37s | Pass | 9/12 |

Functional checks cover: zero failed files; discovered versus indexed file counts; one active visual matrix per PDF page; unchanged source hashes; and repeat indexing with only unchanged skips. All 30 PDFs / 672 pages and 65 source/document files passed these checks. Software suite: 175 tests passed.

## OCR decisions

| Corpus | Native text (no OCR) | Full-page OCR | Region OCR |
|---|---:|---:|---:|
| Math notes (`example_pdfs_2`) | 14 | 118 | 0 |
| Astrobiology (`example_pdfs`) | 147 | 193 | 200 |

The math notes test the misleading-footer case: many pages have only a small selectable page label over rasterized/handwritten content. Those pages receive full OCR. Readable native pages skip OCR without rasterization. Mixed slide pages crop substantial images that lack usable text; decorative banners with native titles and repeated raster tiles do not force repeated OCR. Every page still receives a visual embedding.

## Retrieval findings

These are exploratory relevance judgments, not held-out tests or a universal accuracy score. Math questions mostly judge matching files; two visual questions also require page matches. Slide questions require labeled pages. Code questions require labeled file/function pairs. Related valid results may be absent from the labels.

- Math notes (`example_pdfs_2`): 79% Hit@1; 93% Hit@5.
- Astrobiology (`example_pdfs`): 75% Hit@1; 75% Hit@5.
- Recall codebase: 33% Hit@1; 75% Hit@5.

Misses within the first ten results:

- math: A triangle diagram subtracting the projection of x2 onto x1
- slides: An illustration of a spacecraft flying above an icy horizon with geysers
- code: display a short code preview with its similarity score
- code: retrieve similar code from a selected project
- code: turn a natural language search request into a vector

The visual misses were diagnosed separately: the expected spacecraft page ranked 126th using raw visual scores over all 540 slides; the expected Gram–Schmidt triangle page ranked 44th over the math notes. They are fast-model/detail limitations, not missing page vectors or OCR-skipping failures. Increasing visual detail or adding targeted reranking remains future retrieval work. No query-specific ranking adjustments were made to inflate these results.

The three unrelated code queries returned no results. This does not establish calibrated no-match behavior for PDF/image retrieval. Printed math prose often extracts well, but Tesseract is not reliable handwriting/formula transcription. The notes also include two exact binary-duplicate file groups, so the 20-file set is not 20 independent documents.

## Reproduction and limits

Run `RECALL_OCR_WORKERS=8 python -m evaluation.pipeline_run --output /tmp/recall-corpus-check` from the project root. Use a fresh output directory for a new indexing measurement. `--corpora math`, `slides`, or `code` selects a subset. The code run excludes both PDF folders, backups, build and distribution outputs.

Per-corpus JSON files include query hits, page-level OCR reasons, source-integrity checks, counts, timings and process RSS. Those files and the databases may contain private extracted content and should remain local. RSS excludes Metal allocation. Timings are laptop-specific, use cached weights and shared loaded models, and are not hardware-independent benchmarks.

The pipeline mechanics are a usable foundation for the next UI work: indexing progress, browsing, source/page previews and result actions. Retrieval precision—especially visual distinctions and a few code queries—remains a separate measured limitation.

## Open the math test index in the current UI

From the project directory:

```bash
RECALL_DB_PATH=/tmp/recall-conditional-corpora/math.db .venv/bin/python -m src.main ui
```

This uses the already-built test index, so there is no need to reindex to inspect
these results. The normal index stays separate. Temporary files may be removed
by the operating system; rerun the corpus command to regenerate them.
