# oz-shared

Shared utilities package installed as a dependency across Oz's Python projects.

## Module Structure

Each file in `oz_shared/` must have a single, focused concern. Never put unrelated utilities in a catch-all `utils.py`.

| File | Responsibility |
|------|---------------|
| `oz_shared/onepassword.py` | 1Password CLI integration — loading secrets at local dev time |
| `oz_shared/types.py` | Shared Pydantic types and validators (e.g. `OptStr`) |

**Rule:** When adding a new utility, place it in the file that matches its concern. If no existing file fits, create a new focused module (e.g. `logging.py`, `http.py`) rather than adding to an existing one.

## Public API

`oz_shared/__init__.py` re-exports everything that downstream projects should import. Always update it when adding new public symbols.

## Adding Dependencies

```
uv add <package>
```

Downstream projects pin to this package via git URL. Breaking changes require a version bump in `pyproject.toml`.
