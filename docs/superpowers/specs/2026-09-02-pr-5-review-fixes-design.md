# PR 5 Review Fixes Design

## Scope

Address the three unresolved inline review comments on PR 5:

1. Track Dual Mode state independently for each configured display.
2. Prevent incomplete Dual Mode profiles from issuing unintended VCP writes.
3. Remove the duplicated `has_dual_mode` assertion.

The optional CodeRabbit docstring sweep and the pre-existing global
`last_input` behavior are outside this change.

## Per-display state

`LgMonitorControls` will persist Dual Mode state as a mapping keyed by the
resolved ddcutil display number. JSON object keys are strings, so the in-memory
and persisted representation will use `dict[str, bool]`.

The plugin will expose display-aware read and write methods. `DualMode` will
resolve its effective display number once for each refresh or toggle and pass
that number to both methods. This keeps multiple keys for the same display in
sync through the existing `refresh_all()` path while preventing a write to one
display from changing another display's visual state.

The previous `dual_mode_active` boolean was introduced only on the unmerged PR
branch. Loading will nevertheless tolerate non-dictionary data by treating it
as an empty mapping, avoiding a startup failure for anyone who tested the
branch.

## Profile validation

`DualModeConfig.on` and `DualModeConfig.off` will be optional integers whose
default is `None`. `_load_toml()` will preserve the distinction between an
explicit value (including zero) and a missing key. `has_dual_mode` will require
a nonzero VCP code and both mode values.

An incomplete Dual Mode section will disable only Dual Mode; it will not reject
the entire monitor profile or disable unrelated controls. `set_dual_mode()`
will also check the selected value before calling `setvcp()`, providing a
defensive boundary even if a profile object is constructed directly.

## Tests

Tests will be written before implementation and observed failing for the
reviewed behavior:

- state written for display 1 remains independent from display 2;
- a complete display-state mapping persists with string keys;
- TOML profiles missing `on` or `off` report Dual Mode as unsupported;
- directly constructed incomplete profiles never call `setvcp()`;
- the existing complete LG profile continues to load and write both values.

The redundant assertion in `tests/test_monitor_profile.py` will be removed.
After the focused tests pass, the full pytest, Ruff lint/format, Pyright, and
`git diff --check` suites will be run.
