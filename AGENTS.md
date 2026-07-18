# VS Code Agents Instructions

This file provides instructions for AI coding agents working with the VS Code codebase.

For detailed project overview, architecture, coding guidelines, and validation steps, see the [Copilot Instructions](.github/copilot-instructions.md).

## Read Project Description First

The description of the project is in `Sculpt-n-Code README.md`. Read this first.

### TDD the Visualizers

When working on a *_visualizer.py file, first write failing tests in *_visulizer_tests.py. Do not TDD the typescript front-end.

If you git stash (e.g. to check for pre-existing test failures), don't forget to pop the stash afterward.

### UI Testing

In general, ask the human to test UI features. If specifically asked by the user to test a UI feature yourself, follow the directions in UI_TESTING.md.
