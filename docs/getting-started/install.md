# Install

cass ships on PyPI as `cassroom` and installs as a global `cass` command.

## Prerequisites

- [uv](https://docs.astral.sh/uv/) (Python package and tool manager). Python 3.11 or newer; uv fetches one if needed.

## Stable release

```bash
uv tool install cassroom
```

Upgrade later with:

```bash
uv tool install cassroom --upgrade
```

## Latest from GitHub

```bash
uv tool install git+https://github.com/ejolly/cass.git
```

Refresh with:

```bash
uv tool install git+https://github.com/ejolly/cass.git --reinstall
```

## Check

```bash
cass --version
```
