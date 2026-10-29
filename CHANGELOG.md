# Changelog

## 0.1.1

- Pin the tested model dependency versions to prevent CodeRankEmbed failures with newer Transformers releases.
- Add `recall serve` on macOS/Linux to retain the embedding model between index and search commands.
- Import model dependencies only when needed so help and argument validation start quickly.
- Test worker reuse across separate processes, fallback without a worker, and startup without model imports.

Start `recall serve` in one terminal and wait for the ready message. Run normal
Recall commands in another terminal. Stop the worker with Ctrl-C. The first
startup still loads the model; commands without a worker continue to run locally.
