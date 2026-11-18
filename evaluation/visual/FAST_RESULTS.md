# Fast ColSmol comparison

Same 72 lecture-18 pages and ten exploratory questions as the original comparison. This is a development set with incomplete judgments, not a held-out handwriting benchmark.

| Configuration | Hit@1 | Hit@5 | MRR | Visual encoding time |
|---|---:|---:|---:|---:|
| Original detailed ColSmol | 60% | 80% | 0.724 | Not isolated (224.25s overall experiment) |
| Fast default | 70% | 80% | 0.767 | 37.80s |
| Balanced option | 80% | 90% | 0.844 | 161.17s |

The faster profiles ran on Metal in float16 with SDPA and two-page batches. Image encoding times include image preprocessing and GPU synchronization, but exclude model loading, PDF rendering, OCR, text embedding, and query scoring. The two new profiles were interleaved in one run; the earlier experiment used a different run. These are indicative local timings, not a controlled end-to-end indexing speed comparison.

Fast uses a single 512×512 input (75 vectors per landscape page). Balanced uses a 1,024-pixel edge with image splitting (341 vectors). Original detailed processing produced 870 vectors per page. OCR resolution is unchanged by these visual settings.

Fast is now the default because it kept the original top-five hit rate on this set and was much quicker. Balanced improved top-five retrieval but costs substantially more. Other documents, especially dense diagrams and handwriting, may behave differently.

A separate real pipeline check verified rebuilding changed visual configurations without invoking OCR or text inference. The final Metal loader produced 75×128 matrices in float16 and ranked the spacecraft/geysers image above a cutaway diagram for the corresponding question. Software suite: 167 tests passed.

| Query | Fast relevant-page rank | Balanced relevant-page rank |
|---|---:|---:|
| q1 | 1 | 1 |
| q2 | 1 | 1 |
| q3 | 1 | 1 |
| q4 | 10 | 9 |
| q5 | 1 | 1 |
| q6 | 14 | 3 |
| q7 | 2 | 1 |
| q8 | 1 | 1 |
| q9 | 1 | 1 |
| q10 | 1 | 1 |
