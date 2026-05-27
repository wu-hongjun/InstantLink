# Local validation & CI policy

InstantLink runs validation **locally** via a Git pre-commit hook. GitHub CI is
reserved for release tagging — it does not run on every push or pull request.

## CI policy

| Workflow | Trigger |
|----------|---------|
| `ci.yml` (Audit, Check, Bridge, Linux, Rust Coverage) | release tags `v*` / `bridge-v*`, or manual `workflow_dispatch` |
| `release.yml` | tags `v*` |
| `bridge-firmware.yml` | tags `bridge-v*`, or manual |
| `docs.yml` | push to `main` touching `docs/**` or `mkdocs.yml` (docs site stays current) |

So the full CI suite acts as a release gate; everyday correctness is enforced on
your machine before each commit.

## Pre-commit hook

The hook lives at `scripts/git-hooks/pre-commit` (tracked, so it is shared) and is
activated per-machine by pointing Git at it:

```bash
git config core.hooksPath scripts/git-hooks
```

It is **path-scoped** — each suite runs only when its area has staged changes:

| Staged path | Checks |
|-------------|--------|
| `crates/`, `Cargo.toml`, `Cargo.lock` | `cargo fmt --all -- --check`, `cargo clippy --workspace -- -D warnings`, `cargo test --workspace` |
| `bridge/` | `ruff check src tests`, `mypy src`, `pytest -q` |
| `macos/` | `scripts/test-macos.sh` (swiftc build + tests) |
| any `*.sh` | `bash -n` syntax check |
| `bridge/scripts/*.py` | `python -m py_compile` |
| always | `git diff --check` (whitespace / conflict markers) |

### Bypassing

For a work-in-progress commit you can skip the hook:

```bash
SKIP_HOOK=1 git commit ...     # or
git commit --no-verify
```

Use sparingly — the next release tag will run the full CI suite regardless.

> Note: the hook calls `python`, `cargo`, and `swiftc` from your shell `PATH`.
> Run commits from a terminal where your toolchains (pyenv/venv, rustup, Xcode
> CLT) are available.
