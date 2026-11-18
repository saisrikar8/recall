# Exploratory PDF retrieval results

Tested November 14, 2026 on 72 pages from lecture 18 (Europa and Enceladus), with ten development questions. Five factual questions and five visual descriptions. Judgments were checked against selected rendered slides, but may omit relevant alternatives. These are not held-out or handwriting results.

| Channel | Hit@1 | Hit@5 | MRR | Load (s) | Encode pages + queries (s) | Peak process RSS (MiB) |
|---|---:|---:|---:|---:|---:|---:|
| text | 70% | 90% | 0.800 | 5.29 | 2.96 | 1450 |
| visual | 40% | 80% | 0.535 | 2.12 | 3.94 | 936 |
| combined | 70% | 80% | 0.756 | — | — | — |
| selective | 80% | 90% | 0.850 | — | — | — |

CPU, two Torch threads, batch size one; model weights already cached. Loading/encoding excludes initial downloads and page rendering. Channels ran in separate processes. Combined timing/RSS is not separately measured; it requires both channels.

The visual encoder moved the spacecraft/geysers image query from rank 2 to rank 1. Equal rank fusion moved the liquid-water factual question from rank 1 to rank 18. This argues for testing selective visual retrieval or a document-focused model before production integration. No fusion weights were tuned on this set.

Reproduce with the command in [README.md](README.md). Full local rankings, private page images/text, and profiles are in `/tmp/recall-visual-evaluation/results.json` and adjacent files. Temporary outputs may be removed by the system.

Text model revision: `3c4b60807d71f79b43f3c4363786d9493691f8b1`.
Visual model revision: `3d74acf9a28c67741b2f4f2ea7635f0aaf6f0268`.

## Selective retrieval follow-up

Wording rules preserve text ranking for factual/explanatory questions and use
fusion for explicit requests for images, diagrams, and similar visual content.
On the same development questions, this improves Hit@1 from 70% to 80%, preserves
Hit@5 at 90%, and raises MRR from 0.800 to 0.850. All five visual-description
queries rank a judged page first; factual queries retain the text baseline.

These rules were added after examining the initial experiment, so this result
is not independent validation. No evaluation category or relevance label is
available to the router. Six software tests cover ranking, corpus preparation,
routing examples, ambiguous/factual wording, and separation from judgments.
The experiment still computes both channels, so no runtime/memory savings have
been measured for selective retrieval. Production search is unchanged.

| Query | Chosen channel | Relevant-page rank |
|---|---|---:|
| q1 | text | 6 |
| q2 | text | 1 |
| q3 | text | 1 |
| q4 | text | 3 |
| q5 | text | 1 |
| q6 | combined | 1 |
| q7 | combined | 1 |
| q8 | combined | 1 |
| q9 | combined | 1 |
| q10 | combined | 1 |
