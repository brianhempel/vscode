# Read Project Description First

The description of the project is in `Sculpt-n-Code README.md`. Read this first.

## TDD the Visualizers

When working on a *_visualizer.py file, first write failing tests in *_visulizer_tests.py. Do not TDD the typescript front-end.

If you git stash (e.g. to check for pre-existing test failures), don't forget to pop the stash afterward.

## Cursor

If you are an agent in Cursor, know that I've turned off automatic Typescript language server diagnostics etc. Was eating too much resident memory. Have to rely on the build process to surface errors.

## UI Testing

In general, ask the human to test UI features. If specifically asked by the user to test a UI feature yourself, follow the directions in UI_TESTING.md.

## Type-checking

Use `npm run typecheck-snc` to type-check TypeScript changes. It checks only the Sculpt-n-Code entry points and what they import (`src/tsconfig.snc.json`), in about a second and ~300MB. `npm run typecheck-client` walks all of `src/` and needs ~5GB of memory; only reach for it when you've touched something outside `snc/`. If you add a new SNC entry point (a file nothing in the list imports), add it to `src/tsconfig.snc.json`.
