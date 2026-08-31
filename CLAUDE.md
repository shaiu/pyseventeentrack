# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`pyseventeentrack` is an async Python client for **17track.net's unofficial web API** — the same endpoints the 17track website itself calls, not a documented public API. Fields can disappear, response shapes can change, and endpoints can break without notice. When something stops working, the first suspicion should be "17track changed their API," and the fix is usually re-deriving the request/response shape from live traffic (see `examples/test_api.py`).

## Commands

```bash
script/setup                  # poetry lock + install, then pre-commit install
script/test                   # pytest with coverage (term-missing + coverage.xml)
script/release                # version bump + tag + merge dev→master (dev branch only)

# Single test / single file (needs the venv active, or prefix with .venv/bin/)
.venv/bin/pytest tests/test_profile.py -q
.venv/bin/pytest tests/test_profile.py::test_add_new_package_with_friendly_name -q

pre-commit run --all-files    # ruff (lint+format), bandit, codespell, mypy, pylint
```

Two dependency sources exist and they are **not** kept in sync:

- `pyproject.toml` (poetry) — what `script/setup` and the published package use.
- `requirements_test.txt` — fully pinned; what **CI actually installs**. `mypy` and `pylint` only live here, so the pre-commit local hooks need this file installed to run.

CI (`.github/workflows/ci.yaml`) runs ruff-format via pre-commit, then pytest on Python 3.11 and 3.12, then a coverage job that uploads to Codecov. The README asks for 100% coverage on new code; `.coveragerc` measures `pyseventeentrack` and omits `track.py`.

## Architecture

### Request injection

`Client` owns all HTTP concerns and nothing else. It builds `Profile` by passing its own bound `_request` coroutine in (`client.py:27`), so `Profile` never touches `aiohttp` and is trivially testable. Add new API surfaces the same way: a class taking `request: Callable[..., Coroutine]`, wired up in `Client.__init__`.

`Client._request` also decides session ownership: an externally supplied `ClientSession` is reused and left open; otherwise a throwaway session is created per call with a 10s timeout and closed in `finally`.

### Two hosts, one cookie jar

Auth spans two domains:

- `API_URL_USER` = `user.17track.net/user-api/v1/sign-in-by-password` — login only.
- `API_URL_BUYER` = `buyer.17track.net/orderapi/call` — everything else, dispatched by a `"method"` field in the JSON body (`GetTrackInfoList`, `GetIndexData`, `AddTrackNo`, `SetTrackRemark`, `SetTrackCarrier`, `SetTrackArchived`).

The login endpoint sets cookies with no `Domain` attribute, so per RFC 6265 aiohttp will only replay them to `user.17track.net`. `Client._copy_cookies_to_buyer_domain` runs after any request to `API_URL_USER` and copies the jar across to the buyer host (`client.py:31`). **Without this, every post-login call returns a non-zero `Code` and raises `NotLoggedInError`.** Any change to the login flow or session handling must preserve this hop.

Passwords are RSA-encrypted client-side before being sent (`encrypt.py`) with a hardcoded 17track public key, PKCS1v15 padding, base64-encoded. This mirrors what the website's JS does; it is not a security boundary of ours.

### Inconsistent response envelopes

The two hosts disagree on casing and on how they report failure — do not unify them without checking real responses:

- **User (login):** lowercase `code`, payload under `data`. `Profile.login` ignores `code` entirely and returns `True`/`False` purely on whether `data.gid` is present (`profile.py:39`).
- **Buyer:** capitalized `Code` / `Json` / `Message`. Non-zero `Code` means "not logged in" for reads (`NotLoggedInError`) and a generic `RequestError` for writes.

Reads defensively treat a `None` body as `{}` and default `Code` to `0`, because the API has been observed returning nulls (`4143ee1`).

Package rows are opaque `F`-prefixed keys, and the latest event arrives as a **JSON string inside the JSON** under `FLastEvent`, with single-letter keys (`a` timestamp, `c`/`d` location parts, `z` description) — parsed in `Profile.packages`.

`Profile.packages` latches the first positive `pageInfo.TotalCount`, but only lets it end a partial page because the API may report either package or page counts. Full pages always trigger another request. Empty pages, repeated page signatures, and the 100-page cap bound pagination when the response metadata is missing or ambiguous.

### Package: int codes → human strings

`Package` is a frozen `attrs` class whose `__attrs_post_init__` rewrites fields in place via `object.__setattr__`, converting integer API codes into display strings through `COUNTRY_MAP`, `PACKAGE_TYPE_MAP`, `PACKAGE_STATUS_MAP` (`package.py`). Consequence: the declared type annotations (`destination_country: int`) describe the *input*, not what a caller reads back.

- `status` and the summary lookup use `.get(..., "Unknown")`, so unmapped states degrade gracefully. **`COUNTRY_MAP` and `PACKAGE_TYPE_MAP` use direct subscripting and will `KeyError` on a code 17track adds later.**
- `Profile.summary` folds multiple raw state codes onto the same label, so counts are summed rather than overwritten.
- Timestamps are tried as `%Y-%m-%d %H:%M`, then `%Y-%m-%d %H:%M:%S`, then fall back to the Unix epoch; they are localized to the caller's `tz` and converted to UTC.

### Two-step operations

`add_package` (with a friendly name) and `archive_package` need the internal `FTrackInfoId`, which the add/archive request doesn't return usefully — so they call `packages()` first and match on tracking number, raising `InvalidTrackingNumberError` on no match. That means these methods issue **multiple HTTP requests**, which matters for mocking (below).

### Disabled code

`track.py` (anonymous tracking by number, no login) is commented out in `Client.__init__` and excluded from coverage — the endpoint stopped working. Leave it alone unless reviving it deliberately.

## Testing

There is no `conftest.py` and no pytest config block anywhere — asyncio mode comes from the `pytest-aiohttp` plugin, and tests are individually marked `@pytest.mark.asyncio`.

`tests/common.py` defines what looks like an autouse `aresponses` fixture, but **it is dead code**: `common.py` is a plain module, not a conftest, and test modules only import `TEST_EMAIL` / `TEST_PASSWORD` / `load_fixture` from it — so pytest never collects that fixture. The `aresponses` argument in every test actually resolves to the fixture shipped by the `aresponses` package itself. (Confirm with `pytest tests --fixtures | grep aresponses`.) It also depends on a `loop` fixture that no installed plugin provides any more, so promoting `common.py` to a conftest would break the suite rather than fix it. Delete it or repair it deliberately; don't assume it's running.

Mocks are a **FIFO queue matched by (host, path, method)**, so register one `aresponses.add(...)` per HTTP call, in call order. Practical consequences:

- Nearly every test starts with a login mock against `user.17track.net`.
- `add_package(number, friendly_name)` needs four: login → `AddTrackNo` → `GetTrackInfoList` → `SetTrackRemark`. Adding both a friendly name and carrier needs five, with `SetTrackCarrier` after `SetTrackRemark` so a rejected carrier does not prevent naming the package. `archive_package` needs three. All buyer-host mocks look identical (`buyer.17track.net` / `/orderapi/call` / `post`), so **order is the only thing distinguishing them** — a missing or extra mock surfaces as a confusing failure several calls later.

JSON fixtures live in `tests/fixtures/` and are loaded by name with `load_fixture()`. Prefer adding a fixture file over inlining response bodies.

## Branching and release

`dev` is the default and integration branch; `master` tracks releases. A pre-commit `no-commit-to-branch` hook blocks direct commits to both — work on a feature branch.

`script/release` (run from `dev` only) generates a `YEAR.MONTH.N` version, rewrites `version` in `pyproject.toml`, commits, tags, pushes, and merges `dev` into `master`. It temporarily uninstalls pre-commit to get past the branch guard. Publishing to PyPI is triggered separately by creating a **GitHub Release** (`ci-cd.yml`).

Note the version scheme in `pyproject.toml` is currently semver-ish (`1.1.3`), which `script/release` will overwrite with the date-based scheme on the next run.
