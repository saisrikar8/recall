# Recall desktop

A working Electron interface and shared UI toolkit for Recall. The dashboard,
quick search, and full preview windows use the same components and local index.

## Run on this laptop

From the repository root, with Recall's Python dependencies already installed in
`.venv`:

```sh
cd desktop
npm ci
npm start
```

The app starts its own persistent Python engine; a separate `recall ui` or
`recall serve` process is not needed. It uses your existing Recall database.
Recall starts at login in the menu bar without opening a window. Close the dashboard to leave quick search available. Choose **Recall → Quit
Recall** to stop the app and engine.

If your environment lives elsewhere, set `RECALL_PYTHON` to the Python executable
that has Recall's dependencies installed. `RECALL_DB_PATH` selects a different
index, just as in the CLI.

## The interaction

- **⌘ Shift Space** (Ctrl Shift Space elsewhere) toggles quick search while the
  app is running. If another app owns the shortcut, the dashboard explains that
  it is unavailable; quick search remains accessible from Recall's menu.
- Quick search starts with recent files, searches after a short typing pause,
  and includes a compact original-file preview. Arrow keys select a result;
  Enter opens it in a separate Recall window. Escape hides quick search.
- The dashboard supports file/folder selection through native dialogs, collection
  browsing, file-type filters, and search. Click the dashboard search field and press Enter to run it. Select a result for an inline preview, or double-click/open
  the expand button for a full preview window.
- Indexing displays actual processing messages and file-check counts. Later OCR
  and embedding stages remain indeterminate because the backend does not report
  an honest overall percentage. Search/index work is serialized in the engine.
- Preview windows open originals through the operating system when requested.

## Preview coverage

| Accepted format | Preview |
| --- | --- |
| Python and all other supported code languages | Source in monospace, line numbers, lightweight syntax colors, matched line and query words |
| PDF | Actual rendered page, previous/next navigation, exact text-position highlights |
| Markdown | Safe headings, paragraphs, lists, quotes, code fences, inline code and bold |
| Plain text | Numbered text with query-word highlights |
| Supported images | Bounded, orientation-corrected image preview |

Semantic matches can use different wording. The UI labels their provenance and
highlights actual matching words, or the retrieved code line. Visual results are
page-level; the UI does not fabricate bounding boxes for visual similarity.
PDF highlights use searchable native text; OCR-only PDF text cannot yet be
positioned over the raster because extraction does not retain OCR coordinates.
Large text previews show up to 1,200 lines around the retrieved location.
Markdown intentionally does not execute HTML, scripts, or remote assets and does
not attempt to implement every Markdown extension.

## The toolkit

Shared interface components live in the renderer files; there is no separate
Design toolkit page in the app.

- `renderer/tokens.css`: semantic color, type, spacing, radius, and shadow tokens;
  shared controls, badges, focus styles, reduced-motion support.
- `renderer/app.css`: reusable file rows, split previews, document/code viewers,
  progress cards, navigation, launcher and dashboard layouts.
- `renderer/app.js`: shared rendering and interaction for the three window modes.
- `main.cjs`: native windows, global shortcut, tray/menu, dialogs, private IPC and
  the persistent engine process.
- `preload.cjs`: the narrow bridge exposed to the isolated renderer.
- `../src/desktop_bridge.py`: real index/library/search/jobs and original-file
  previews. Access is restricted to indexed files. No localhost HTTP server is
  opened by this app.

The design uses warm ivory, moss green, editorial serif headings, and system
sans controls. No remote font or UI service is required.

## Verify

```sh
npm run check
npm test
```

The desktop test launches real Electron windows against a disposable synthetic
library. It exercises code, Markdown and PDF previews, page navigation, quick
search, keyboard navigation, dashboard word highlighting, file addition, and handoff to a separate preview window. It uses
cached Recall text-model weights for the search check. Screenshots are written
to `/tmp/recall-desktop-*.png`. Run `python -m unittest tests.test_desktop_bridge`
from the repository root for preview/backend checks.

## Distribution status

This is the runnable desktop foundation, not a signed installer. It currently
requires the repository and a working Python environment. Bundling the Python
runtime/models, creating a macOS app/DMG, signing/notarization, and updates remain
separate shipping work. Model downloads still follow Recall's existing behavior.
The shortcut and window lifecycle were implemented for macOS; other platforms
need native testing before distribution.

The renderer follows Electron's [context isolation](https://www.electronjs.org/docs/latest/tutorial/context-isolation)
and [IPC security guidance](https://www.electronjs.org/docs/latest/tutorial/security).

## Background search and preloading

The quick-search window is frameless on macOS, including explicitly hidden traffic
lights. Closing the library hides it; the menu bar app and shortcut keep running.
The Dock icon disappears when only quick search (or no window) is visible.
**Quit Recall** stops the engine and shortcut until Recall is started again or
you next log in. There cannot be a global hotkey without a running background
process.

**Start at login** is enabled on the next normal launch and can be turned off in
the menu bar. Packaged builds use the operating system login-item registration.
The current macOS development build writes an app-specific LaunchAgent at
`~/Library/LaunchAgents/app.recall.desktop.plist`, pointing at this checkout and
its Python environment. Moving/deleting the checkout requires disabling and
reenabling login startup from the new location. `npm run background` starts only
the menu bar app. Test runs disable startup registration and never modify login
settings. Explicitly quitting is respected; the agent does not use KeepAlive.

The Python engine warms the text search model automatically at startup. If the
active library has compatible ColSmol/scene vectors, those search models are also
warmed. The work runs in the same serialized inference queue used by search and
indexing, keeping model objects alive without competing inference threads.
Metadata browsing and previews remain available during warmup. Failed warmup
channels are logged and retried through normal search rather than blocking the
entire application. A new library does not preload unused visual channels.

Preloaded models consume real memory. Python RSS is recorded in the engine's
warmup status for diagnostics; it is not a complete measurement of Metal/unified
memory. No experimental large rerankers are preloaded.

The interface uses proportional type for controls and prose, and monospace for
source previews, fenced code, and inline code. It
omits the sidebar marketing card, duplicate filename/path rows, redundant type
badges, file-size labels, and routine preview explanations. Original PDF/image
content is displayed as-is.

Measured in the isolated four-file desktop test: all three search channels warmed
in 8.96 seconds, and Python worker RSS was 1,023 MiB at the end of warmup. This
excludes a complete accounting of GPU/unified-memory use and the Electron windows.

Indexing status updates keep the progress animation mounted, so polling does not
restart it. The status line shows the current file/stage rather than internal
embedding logs. Discovery excludes a Gleam project's generated `build` directory
when its parent contains `gleam.toml`; ordinary directories named `build` remain
eligible. Gleam source extraction (`.gleam`) is not implemented yet.

## Appearance

The sidebar's icon switch offers System (monitor), Light (sun), and Dark (moon),
with a sliding selection indicator. It supports arrow keys, Home, and End.
The preference is saved and shared with quick search and preview windows.
System mode follows live macOS appearance changes. Dark mode includes navigation,
search, progress cards, document/code viewers, and syntax colors; original PDFs
and images retain their original colors. Code remains monospace in both themes.
Search has one global shortcut, **⌘ Shift Space**; ⌘K is not bound.

## Remove a collection

Hover a collection in the sidebar (or focus it with the keyboard) and click its
trash icon. Confirm **Remove from Recall** to remove its files and embeddings
from the index. Original files remain on disk. Other windows refresh immediately,
and removing the currently selected collection returns to Overview. Removal is
blocked while another indexing operation holds the database lock.

Search results group repeated code/note chunks into a single file row. Numbered
question searches can follow test references to implementations, and old generated
records are filtered using current discovery policy. See
[CS61A relevance checks](../evaluation/CS61A_RESULTS.md) for measured results and
limits; this is retrieval, not an assignment-answer generator.

## Folder progress and live indexing

During indexing, the main progress bar counts files that have finished processing,
not just files discovered or checked. Expand **Folder progress** for nested-folder
counts and failure counts. Preparing a PDF does not mark it complete before its
embeddings have been published.

Newly published files appear in the library while the operation continues. Updates
are throttled, keep the selected preview stable, and refresh other open windows.
The sidebar counts and recent-file list update together. Search and index mutations
still share the serialized inference queue.

The desktop also warms the small text reranker used for ambiguous natural-language
questions. This adds memory and initial model loading; exact file/keyword lookups
stay on the faster base-ranking path. See
[the 300-case collection evaluation](../evaluation/collections/RESULTS.md) for the
measured relevance, warm latency, and resource tradeoffs.

By default the desktop owns its model instances rather than attaching to a
possibly older CLI embedding worker. An explicit RECALL_EMBEDDING_SOCKET override
is still respected. This keeps preloading and batch support consistent in the app.

## Native menu bar

- **Recall:** About, Settings (`⌘,`), Start at Login, Open Library, standard hide
  actions, and Quit.
- **File:** Add Files (`⌘O`), Add Folder (`⌘⇧O`), Reindex Selected Collection,
  Remove Selected Collection, and Close Window.
- **Search:** Quick Search (`⌘⇧Space`) and Search This Collection. Collection
  search focuses the dashboard input while retaining the selected collection.
- **View:** System/Light/Dark appearance, Show Indexing Progress, zoom, and full
  screen. Indexing progress opens its folder breakdown without interrupting work.
- Standard **Edit** and **Window** menus remain available.

Collection-dependent actions disable without a selected collection; file mutations
also disable during a search/index operation. Reindexing reuses the same live
progress and publication flow as import. Removal uses the same confirmation and
index-only deletion as the sidebar.

Settings opens in its own window, shares appearance with other windows/menu items,
and keeps Start at Login synchronized with the tray and application menu. The
About panel identifies Recall and its version. The package declares Recall as its
product name; the development Electron binary may still use its own macOS bundle
name until the app is packaged.

## First-launch setup

An empty library opens a skippable onboarding flow: choose folders or files,
set appearance and startup preferences, then watch real indexing progress and
try a first search. Files appear as they become searchable. You can leave setup
while indexing continues in the library.

Setup completion is remembered on this device. Existing libraries continue
straight to the dashboard. Reopen setup with **Recall → Welcome to Recall…**.
