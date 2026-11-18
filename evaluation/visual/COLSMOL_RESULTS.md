# ColSmol trial

Compared on the same 72 lecture-18 pages and ten exploratory questions used for the original CLIP evaluation. These judgments are incomplete and not held out.

| Visual channel | Hit@1 | Hit@5 | MRR |
|---|---:|---:|---:|
| CLIP baseline | 40% | 80% | 0.535 |
| ColSmol-256M | 60% | 80% | 0.724 |

ColSmol ran on Metal with aspect-preserving page inputs up to 1,280 pixels. It took 224.25 seconds for model loading, encoding ten queries and 72 pages, and scoring all query/page pairs. This is a much heavier pipeline than the earlier low-resolution CLIP baseline; timings were not collected in controlled identical hardware conditions. Peak sampled process RSS was about 1,572 MiB, excluding Metal allocation. Do not interpret the accuracy gain as universal or the timing as a production throughput guarantee.

The base and adapter revisions are pinned in src/visual.py. Production stores normalized token matrices in packed float16 and uses blockwise MaxSim. The evaluation scored float32 matrices before storage, so small score differences from production quantization are expected. It does not establish handwriting accuracy.

| Query | Relevant page rank |
|---|---:|
| q1 | 2 |
| q2 | 1 |
| q3 | 1 |
| q4 | 8 |
| q5 | 1 |
| q6 | 9 |
| q7 | 2 |
| q8 | 1 |
| q9 | 1 |
| q10 | 1 |
