# Changelog

## 0.2.0-alpha.2

- Search installed applications in quick search, with prefixes, abbreviations, and typo matching.
- Launch matching apps with Enter, a double-click, or the preview button.
- Remove individual files from Recall without deleting originals.
- Refresh open library and preview windows after removal. Reindexing a folder adds removed files back.
- Package versioned macOS and Windows desktop installers.

## 0.1.1

- Pin the tested model dependency versions to prevent CodeRankEmbed failures with newer Transformers releases.
- Add `recall serve` on macOS/Linux to retain the embedding model between index and search commands.
- Import model dependencies only when needed so help and argument validation start quickly.
- Test worker reuse across separate processes, fallback without a worker, and startup without model imports.

Start `recall serve` in one terminal and wait for the ready message. Run normal
Recall commands in another terminal. Stop the worker with Ctrl-C. The first
startup still loads the model; commands without a worker continue to run locally.
