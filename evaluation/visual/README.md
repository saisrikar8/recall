# Visual page retrieval experiment

This experiment compares Recall's CodeRankEmbed text retrieval, a small CLIP
image/text baseline, and reciprocal-rank fusion. It does not change your Recall
index or start the embedding server. PDF contents stay local; the first run
requires downloading model weights from Hugging Face.

From the repository root:

```bash
.venv/bin/python -m pip install -e '.[visual-evaluation]'
.venv/bin/python -m evaluation.visual.run --folder example_pdfs \
  --pdf '*lecture18*' --max-pages 72
```

Results, rendered pages, extracted text, rankings, timings and sampled process
memory go to `/tmp/recall-visual-evaluation`. Choose another `--output` to retain
them. Treat this folder as private: it contains readable copies of your pages.
`--reuse-pages` reruns models against that saved corpus without rendering again.
Use a fresh output folder when changing datasets. No page cache is read by the
normal application.

`queries.json` contains exploratory relevance judgments for the Europa/Enceladus
lecture. IDs use `filename.pdf#page=NUMBER` (one-based). Edit judgments and queries
for a different corpus; expected pages must be present or the run fails. Labels
never enter the encoders. This is a development set, not a held-out benchmark;
additional relevant pages may be missing from its labels.

The text channel uses embedded PDF text, split into overlapping bounded passages,
and takes the best passage score for each page. `--ocr` uses the optional system
`tesseract` executable for pages with fewer than 30 extracted characters. It does
not OCR every diagram on a page that already contains text. The default run tests
PDF text against visual retrieval, without OCR. It does not establish handwriting
accuracy: add real handwriting examples and independently judged questions first.

The text model is pinned to revision `3c4b60807d71f79b43f3c4363786d9493691f8b1`.

The visual channel uses `openai/clip-vit-base-patch32`, pinned to revision
`3d74acf9a28c67741b2f4f2ea7635f0aaf6f0268`, with its matching text encoder.
Pages are letterboxed into 224×224 inputs to retain their edges. This low
resolution is a baseline and can lose small writing and fine diagram detail.
Text and image scores belong to different spaces: combined search fuses ranks,
never their cosine scores. Hit@1, Hit@5 and MRR are page-level metrics.

Each channel runs in a separate CPU process with two Torch threads, batch size
one, and one page rendered at a time. All model memory is released before the
next channel starts. Memory reports are sampled process RSS, excluding GPU and
other processes. Timings include model loading separately from encoding; cold
downloads can affect load time. The results record the resolved model revisions.

A document-focused, higher-resolution model such as ColPali is a follow-up
candidate if this baseline misses diagrams or handwriting. Do not promote this
experimental model into the production index based on these ten queries alone.

The first measured run is summarized in [RESULTS.md](RESULTS.md).

## Selective retrieval

The experiment also reports `selective`: factual or explanatory questions retain
the original text ranking, while explicit visual requests use fused ranking.
For example, “Why can Europa have liquid water?” uses text; “An illustration of
a spacecraft above geysers” uses both channels. Ambiguous wording defaults to
text. Routing uses a small set of wording rules in `routing.py`, never query
categories or relevance judgments. Each result records its route and reason.
This conservative rule can miss visual intent phrased as a factual question.

All four methods run with the same command above. Both model channels are still
computed during evaluation to compare them fairly; the router does not yet save
model-loading time or memory. The wording router is now shared with normal Recall search. Production indexing
automatically adds OCR and CLIP vectors; the experiment still compares channels
in an isolated corpus. These development results need validation on additional documents and
natural user queries before choosing production behavior.
