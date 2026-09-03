# Release runbook

Releases publish from immutable version tags only after the release-prep PR has
merged. Merging the PR does not publish a release.

## Prepare and verify

Run this procedure in a fresh, dedicated Bash session, keep the session's
working directory at the repository root, and leave fail-fast mode enabled for
the entire procedure (including recovery):

```bash
set -euo pipefail
release_version=0.3.0
release_tag="v${release_version}"
release_branch=chore/release-0.3.0
plugin_id=me_tysmith_LgMonitorControls
release_dir=dist/release
archive_name="${plugin_id}-${release_version}.zip"
checksum_name="${archive_name}.sha256"
```

The release-prep PR must set the same version in `manifest.json`, `pyproject.toml`,
and the root project package entry in `uv.lock`; `CHANGELOG.md` must contain a
non-empty section for the version. Run the lock check and the same CI commands
used by the workflows:

```bash
uv lock --check
uv run --locked --only-group ci ruff check .
uv run --locked --only-group ci ruff format --check .
uv run --locked --only-group ci pyright
uv run --locked --only-group ci pytest tests/ -v
uv run --locked --only-group ci python scripts/build_release.py --version "$release_version" --output-dir "$release_dir"
```

## Inspect the artifacts

Inspect the archive listing, verify its checksum from the directory containing
the archive, and assert that the ZIP has exactly one top-level directory:

```bash
unzip -l "$release_dir/$archive_name"
(cd "$release_dir" && sha256sum -c "$checksum_name")
top_levels=$(unzip -Z1 "$release_dir/$archive_name" | awk -F/ 'NF {print $1}' | sort -u)
test "$(printf '%s\n' "$top_levels" | sed '/^$/d' | wc -l)" -eq 1
test "$top_levels" = "$plugin_id"
test -f "$release_dir/$checksum_name"
test -f "$release_dir/RELEASE_NOTES.md"
```

## Tag and publish after merge

Resolve the exact merge commit from the merged release-prep PR before switching
branches. Then update `main`, verify that commit is included and its metadata is
correct, and tag that explicit commit:

```bash
release_commit=$(gh pr view "$release_branch" --json state,mergeCommit --jq 'select(.state == "MERGED") | .mergeCommit.oid')
test -n "$release_commit"
git checkout main
git pull --ff-only origin main
test -z "$(git status --porcelain)"
git merge-base --is-ancestor "$release_commit" origin/main
printf 'release commit: %s\n' "$release_commit"
manifest_version=$(git show "$release_commit:manifest.json" | jq -r '.version')
pyproject_version=$(git show "$release_commit:pyproject.toml" | sed -nE 's/^version = "([^"]+)"$/\1/p' | head -n 1)
lock_version=$(git show "$release_commit:uv.lock" | awk -v project="streamcontroller-lg-monitor-control" '
  $0 == "name = \"" project "\"" { found=1; next }
  found && /^version = / { gsub(/version = \"|\"/, ""); print; exit }
')
test "$manifest_version" = "$release_version"
test "$pyproject_version" = "$release_version"
test "$lock_version" = "$release_version"
git tag -a "$release_tag" "$release_commit" -m "Release $release_version"
git push origin "$release_tag"
```

Pushing only the quoted version tag starts the `Release` workflow. It reruns the
tag-version gates, validation, and build, then publishes the ZIP and checksum as
the GitHub release with generated release notes. Identify and watch the run for
the exact tagged commit, then verify the published release and assets:

```bash
run_id=""
for attempt in {1..12}; do
  run_id=$(gh run list --workflow Release --event push --limit 20 --json databaseId,event,headBranch,headSha --jq 'first(.[] | select(.event == "push" and .headBranch == "'"$release_tag"'" and .headSha == "'"$release_commit"'") | .databaseId) // empty')
  if [[ -n "$run_id" ]]; then
    break
  fi
  sleep 5
done
test -n "$run_id"
gh run watch "$run_id" --exit-status
verify_published_release() {
release_info=$(gh release view "$release_tag" --json isDraft,isPrerelease,assets,url)
test "$(printf '%s' "$release_info" | jq -r '.isDraft')" = false
test "$(printf '%s' "$release_info" | jq -r '.isPrerelease')" = false
asset_names=$(gh release view "$release_tag" --json assets --jq '.assets[].name' | sort)
expected_assets=$(printf '%s\n' "$archive_name" "$checksum_name" | sort)
test "$asset_names" = "$expected_assets"
verify_dir=$(mktemp -d)
trap 'if [[ -n "${verify_dir:-}" && "$verify_dir" != "/" ]]; then rm -rf -- "$verify_dir"; fi' EXIT
gh release download "$release_tag" --dir "$verify_dir" --pattern "$archive_name" --pattern "$checksum_name"
test -f "$verify_dir/$archive_name"
test -f "$verify_dir/$checksum_name"
test "$(find "$verify_dir" -maxdepth 1 -type f | wc -l)" -eq 2
(cd "$verify_dir" && sha256sum -c "$checksum_name")
published_top_levels=$(unzip -Z1 "$verify_dir/$archive_name" | awk -F/ 'NF {print $1}' | sort -u)
test "$(printf '%s\n' "$published_top_levels" | sed '/^$/d' | wc -l)" -eq 1
test "$published_top_levels" = "$plugin_id"
gh release view "$release_tag"
}
verify_published_release
```

## Recovery

`gh release create` may leave a partial draft if publishing fails. Because
fail-fast mode exits the prior session, start recovery in a fresh dedicated Bash
session and keep it enabled:

```bash
set -euo pipefail
release_version=0.3.0
release_tag="v${release_version}"
release_branch=chore/release-0.3.0
plugin_id=me_tysmith_LgMonitorControls
release_dir=dist/release
archive_name="${plugin_id}-${release_version}.zip"
checksum_name="${archive_name}.sha256"
if ! git show-ref --verify --quiet "refs/tags/$release_tag"; then
  git fetch origin "refs/tags/$release_tag:refs/tags/$release_tag"
fi
git show-ref --verify --quiet "refs/tags/$release_tag"
verify_published_release() {
  release_info=$(gh release view "$release_tag" --json isDraft,isPrerelease,assets,url)
  test "$(printf '%s' "$release_info" | jq -r '.isDraft')" = false
  test "$(printf '%s' "$release_info" | jq -r '.isPrerelease')" = false
  asset_names=$(gh release view "$release_tag" --json assets --jq '.assets[].name' | sort)
  expected_assets=$(printf '%s\n' "$archive_name" "$checksum_name" | sort)
  test "$asset_names" = "$expected_assets"
  verify_dir=$(mktemp -d)
  trap 'if [[ -n "${verify_dir:-}" && "$verify_dir" != "/" ]]; then rm -rf -- "$verify_dir"; fi' EXIT
  gh release download "$release_tag" --dir "$verify_dir" --pattern "$archive_name" --pattern "$checksum_name"
  test -f "$verify_dir/$archive_name"
  test -f "$verify_dir/$checksum_name"
  test "$(find "$verify_dir" -maxdepth 1 -type f | wc -l)" -eq 2
  (cd "$verify_dir" && sha256sum -c "$checksum_name")
  published_top_levels=$(unzip -Z1 "$verify_dir/$archive_name" | awk -F/ 'NF {print $1}' | sort -u)
  test "$(printf '%s\n' "$published_top_levels" | sed '/^$/d' | wc -l)" -eq 1
  test "$published_top_levels" = "$plugin_id"
  gh release view "$release_tag"
}
release_commit=$(git rev-parse "$release_tag^{}")
test -n "$release_commit"
run_id=""
for attempt in {1..12}; do
  run_id=$(gh run list --workflow Release --event push --limit 20 --json databaseId,event,headBranch,headSha --jq 'first(.[] | select(.event == "push" and .headBranch == "'"$release_tag"'" and .headSha == "'"$release_commit"'") | .databaseId) // empty')
  if [[ -n "$run_id" ]]; then
    break
  fi
  sleep 5
done
test -n "$run_id"
run_state=$(gh run view "$run_id" --json status,conclusion)
run_status=$(printf '%s' "$run_state" | jq -r '.status')
run_conclusion=$(printf '%s' "$run_state" | jq -r '.conclusion // empty')
case "$run_status" in
  queued|in_progress|requested|waiting|pending)
    gh run watch "$run_id" --exit-status
    verify_published_release
    exit 0
    ;;
  completed)
    ;;
  *)
    printf 'Unknown, empty, or malformed run status: %s\n' "$run_status" >&2
    exit 1
    ;;
esac
case "$run_conclusion" in
  success)
    verify_published_release
    exit 0
    ;;
  failure|cancelled|timed_out|action_required|stale)
    ;;
  *)
    printf 'Unknown or non-rerunnable run conclusion: %s\n' "$run_conclusion" >&2
    exit 1
    ;;
esac
probe_dir=$(mktemp -d)
trap 'if [[ -n "${probe_dir:-}" && "$probe_dir" != "/" ]]; then rm -rf -- "$probe_dir"; fi' EXIT
probe_out="$probe_dir/release.json"
probe_err="$probe_dir/error.txt"
```

Probe the release by tag and do not assume that an API failure means it is
absent:

```bash
if gh api "repos/tyvsmith/streamcontroller-lg-monitor-control/releases/tags/$release_tag" >"$probe_out" 2>"$probe_err"; then
  jq '{isDraft: .draft, isPrerelease: .prerelease, assets: [.assets[].name], html_url}' "$probe_out"
  is_draft=$(jq -r '.draft' "$probe_out")
  test "$is_draft" = true -o "$is_draft" = false
  if [[ "$is_draft" == true ]]; then
    read -r -p "Confirm draft $release_tag belongs to failed run $run_id; type DELETE: " confirmation
    test "$confirmation" = DELETE
    gh release delete "$release_tag" --yes
    gh run rerun "$run_id"
    gh run watch "$run_id" --exit-status
    trap - EXIT
    if [[ -n "$probe_dir" && "$probe_dir" != "/" ]]; then rm -rf -- "$probe_dir"; fi
    verify_published_release
  else
    trap - EXIT
    if [[ -n "$probe_dir" && "$probe_dir" != "/" ]]; then rm -rf -- "$probe_dir"; fi
    verify_published_release
  fi
else
  if rg -q 'HTTP 404|404 Not Found' "$probe_err"; then
    printf 'Confirmed HTTP 404; rerunning failed workflow.\n'
    gh run rerun "$run_id"
    gh run watch "$run_id" --exit-status
    trap - EXIT
    if [[ -n "$probe_dir" && "$probe_dir" != "/" ]]; then rm -rf -- "$probe_dir"; fi
    verify_published_release
  else
    cat "$probe_err" >&2
    exit 1
  fi
fi
```

A draft may be deleted only after the exact `isDraft == true` guard and typed
confirmation above; the delete command removes the unpublished release only and
does not clean up the immutable tag. A published release is never deleted, and
a tag is never moved or recreated. After either permitted recovery rerun path,
repeat the full published release verification above: draft/prerelease status,
exact asset-name comparison, download into a fresh verification directory,
checksum validation, and ZIP top-level-directory assertion. Defective tagged
source or workflow still requires a correction PR and a new patch version.

## StreamController Store

The Store uses the commit pinned in `StreamController-Store/Plugins.json`, not
the GitHub Release artifact. Resolve the released commit, then fork and update
`https://github.com/StreamController/StreamController-Store`:

```bash
git rev-parse "$release_tag^{}"
```

Fork the repository above on GitHub, then in the fork find the entry whose
repository URL is
`https://github.com/tyvsmith/streamcontroller-lg-monitor-control` and replace
only its commit SHA with the output of `git rev-parse "$release_tag^{}"`. Open a
Store PR linking the release URL shown by `gh release view "$release_tag"`.
There is no secret-based Store automation.
