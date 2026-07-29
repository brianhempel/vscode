# Read Project Description First

The description of the project is in `Sculpt-n-Code README.md`. Read this first.

## TDD the Visualizers

When working on a *_visualizer.py file, first write failing tests in *_visulizer_tests.py. Do not TDD the typescript front-end.

If you git stash (e.g. to check for pre-existing test failures), don't forget to pop the stash afterward.

## Cursor

If you are an agent in Cursor, know that I've turned off automatic Typescript language server diagnostics etc. Was eating too much resident memory. Have to rely on the build process to surface errors.

## UI Testing

In general, ask the human to test UI features. If specifically asked by the user to test a UI feature yourself, follow the directions in UI_TESTING.md.
