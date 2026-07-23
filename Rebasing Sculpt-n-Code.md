## Updating to latest VS Code

Keep the full commit history via `rebase --onto NEW_TAG OLD_TAG`. It replays
only the `OLD_TAG..snc` commits, so it never touches the ancient common ancestor
and never drags in the upstream-vs-upstream conflicts.

```
git fetch ms --tags
# OLD_TAG = the tag snc is currently based on; NEW_TAG = target tag.
git worktree add -b snc-on-NEW_TAG ../snc-rebase-wt NEW_TAG   # optional: keep your built tree intact
cd ../snc-rebase-wt
git reset --hard snc
git rebase --onto NEW_TAG OLD_TAG
```

Resolve each conflict keeping the upstream (NEW_TAG) side and re-applying the small SNC edit, minding
the file moves/renames (git rename-detection follows most of them automatically,
but not gulpfile.vscode.js -> .ts, and it can mis-route workbench-dev.html onto a copilot test
fixture — redirect that edit to `src/vs/code/electron-browser/workbench/workbench-dev.html`).
`git config rerere.enabled true` helps with the repeated AGENTS.md conflict.

If everything still works, fast-forward the `snc` branch and push:

```
git branch -f snc snc-on-NEW_TAG
git push -f
```
