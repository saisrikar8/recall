# Visual retrieval experiments

Tested on the existing 20-file/132-page handwritten mathematics corpus and
10-file/540-page lecture-slide corpus. All work used disposable database copies;
the normal user index and original PDFs were preserved.

## What shipped

- Broader visual-query routing, including natural questions about a diagram.
- A complementary pinned CLIP ViT-B/32 whole-page scene channel for explicit
  photo, picture, illustration, painting, or screenshot requests. Its leading
  result is retained before the remaining results are fused by rank. ColSmol
  remains the document/diagram visual channel; factual and code queries keep
  their existing ranking.
- Scene vectors are built in bounded batches of eight and stored separately by
  model key. One reindex adds them while reusing compatible OCR, text embeddings,
  and ColSmol vectors. Publication remains atomic per file, including failures.

This is a targeted heuristic, not a learned universal router. Explicit appearance
wording prioritizes scene similarity; a misleading scene leader can still be
wrong. Diagram-only requests do not receive that priority.

## Ablations

Hit@5 means the labeled relevant result appeared among the first five. These are
small development sets (14 math queries and four slide queries), not held-out
accuracy estimates. Some labels identify files, while visual labels identify
specific pages. Individual visual failures are therefore reported separately.

| Variant | Math Hit@1 / Hit@5 | Slides Hit@1 / Hit@5 |
|---|---:|---:|
| Existing baseline | 11/14 · 13/14 | 3/4 · 3/4 |
| Broader routing | 11/14 · 13/14 | 3/4 · 3/4 |
| ColSmol region crops | 9/14 · 12/14 | 2/4 · 3/4 |
| E5 document-text experiment | 9/14 · 13/14 | 3/4 · 3/4 |
| Wide candidate union | 11/14 · 12/14 | 1/4 · 3/4 |
| Text cross-encoder reranking | 11/14 · 12/14 | 3/4 · 3/4 |

The crop trial extracted 380 math regions and 539 slide regions. Region embedding
cost about 77 and 98 seconds respectively. E5-small text windows cost about 2.9
and 5.9 seconds to embed. Text reranking added a median 0.19 seconds for math,
but did not improve overall retrieval. Timings share warmed models/caches and
are not independent end-to-end latency comparisons.

| Visual target | Existing retrieval | Scene channel | Scene + Qwen image reranking |
|---|---:|---:|---:|
| Gram–Schmidt triangle | Outside first 10 | 20 | 1 |
| Basis diagram | 1 | 31 | 7 |
| Spacecraft above icy geysers | Outside first 10 | 1 | 1 |

The scene experiments above include whole-page and cropped images. An isolation
check also ranked the spacecraft first using **whole pages alone**, across all
540 slide pages. Therefore production uses the cheaper whole-page channel.
It does not add region indexing by default.

Qwen3-VL-Reranker-2B evaluated 33–35 candidates using its pinned training chat
template and actual page images. It took 53.7–60.8 seconds per query. It rescued
the triangle but regressed the basis diagram. The earlier first attempt had a
chat-template error; those failed scores are excluded from these results.
The corrected implementation remains available for experiments. Its roughly
4 GB weights are not loaded by normal Recall searches.

## Production-path verification

A copy of the 540-page slide index upgraded in **38.04 seconds**, producing 540
scene vectors and publishing ten changed PDFs with zero failures. OCR, text
inference, and ColSmol inference were replaced with failure guards during this
check, proving that none reran. The scene leader was lecture 18, page 61, for:

> An illustration of a spacecraft flying above an icy horizon with geysers

The full production search also returned lecture 18, page 61 first: 9.30 seconds
for a cold process loading all models and 1.42 seconds for the next query in the
same process. These are two observations, not a latency distribution.

Validation: all 186 tests passed, including scene-only upgrades, failed upgrades
preserving old publications, and photo ranking. The installable wheel built
successfully. The main user database was not reset or upgraded during this test.

## Reproducing

From the project root, first prepare the disposable baseline corpora using
`python -m evaluation.pipeline_run --help`. Then run:

```sh
python -m evaluation.retrieval_lab
python -m evaluation.scene_lab --rerank
```

The scripts use `/tmp/recall-conditional-corpora` as the baseline and
`/tmp/recall-retrieval-lab` for copied databases and JSON results. Use `--help` to
change locations. The image reranker is deliberately opt-in. New models download
from Hugging Face on first use. The experimental E5, region, and reranking modules
are not enabled automatically in production.

## Follow-up: handwritten image omitted by ordinary queries

A live indexed handwritten matrix image had a complete active extraction and both
visual embedding types, but Tesseract returned no readable text. The old routing
only considered ColSmol as a text fallback, and only considered CLIP for explicit
photo/illustration requests. “linear algebra” ranked the image 22nd in ColSmol but
first in CLIP, outside the launcher's 12 visible results. “What are P and C equal
to?” ranked it first in both visual channels; unrelated text hits could previously
prevent those channels from running.

Ordinary searches now consider all compatible channels. Their leading text result
is retained, and leading visual candidates stay visible before the remaining
rank-fused candidates. Explicit diagram fusion and photo priority remain intact.
This broadens retrieval at the cost of extra visual inference and potentially
less-relevant visual suggestions. Similarity scores are not compared across models.

Read-only checks against that live index placed the image second for “linear
algebra” and first for “What are P and C equal to?” No reindexing was needed.
The original disposable regression corpora retained 11/14 math Hit@1 and 13/14
Hit@5, and 3/4 slide Hit@1 and Hit@5 (the original slide copy lacks the later CLIP
upgrade). These remain small development checks, not held-out accuracy estimates.
