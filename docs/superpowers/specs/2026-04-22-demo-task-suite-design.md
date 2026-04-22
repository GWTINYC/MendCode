# Demo Task Suite Design

## 1. Purpose

This spec defines the next narrow slice on the MendCode mainline after runner-side tool authorization and stage tracking landed:

- establish a stable demo task suite under `data/tasks/demos/`
- remove the old single-entry demo at `data/tasks/demo.json`
- align README and tests with the new demo layout

The scope is intentionally narrow. This spec does **not** introduce batch eval, task discovery manifests, new runner behaviors, or planner logic.

---

## 2. Current Context

As of 2026-04-22, the repository already has:

- a working fixed-flow `task run` path
- per-run git worktree execution
- tool-level trace events
- runner-enforced `allowed_tools`
- `current_step` that now reflects the real failing stage

The current weakness is no longer "can the system run one demo task at all?" The weakness is that the project still exposes only a loosely defined single demo entrypoint. That makes it harder to:

- demonstrate the real supported behavior surface
- explain failure modes clearly
- prepare the next batch-eval step on top of stable examples

The correct next step is therefore to stabilize a **small, explicit demo suite** rather than add more runtime machinery.

---

## 3. Goal

Create a minimal but stable demo suite that proves four key MendCode behaviors:

1. successful fixed-flow repair
2. unauthorized tool rejection
3. ambiguous search failure during `locate`
4. verification failure during `verify`

The result should be a set of repository-native sample tasks that can be used in README examples, CLI checks, and future eval work.

---

## 4. Non-Goals

This slice does not include:

- batch eval runner
- demo manifest or discovery index
- new task types
- changes to planner/orchestrator strategy
- richer patch engine behavior
- service/API work

If a change does not directly improve the clarity and stability of the demo task suite, it is out of scope.

---

## 5. Approaches Considered

### Approach A: Stable demo suite in `data/tasks/demos/` with direct file references

Create four explicit task files under `data/tasks/demos/`, update README to reference them directly, and move tests to the new paths.

Pros:

- smallest change that still creates a real demo suite
- easiest to explain to users and future contributors
- no premature abstraction

Cons:

- no built-in discovery metadata
- later batch-eval work will still need a lightweight selection layer

### Approach B: Demo suite plus `manifest.json`

Create the same four demos but also add a manifest that acts as the source of truth for README and future eval selection.

Pros:

- smoother path to later task discovery
- tighter explicit grouping

Cons:

- adds a structure the project does not need yet
- increases this slice's scope without immediate product value

### Approach C: Migrate only the current main demo

Move the existing success demo under `data/tasks/demos/` and leave failure cases only in tests.

Pros:

- lowest immediate editing cost

Cons:

- does not actually create a stable demo task suite
- keeps product-facing examples lagging behind supported failure behavior

### Recommendation

Choose **Approach A**.

It is the narrowest approach that still moves the mainline forward. It gives the project a real demo suite now, without prematurely introducing a task registry or batch-eval scaffolding.

---

## 6. File Structure

### Create

- `data/tasks/demos/success.json`
- `data/tasks/demos/unauthorized-tool.json`
- `data/tasks/demos/ambiguous-search.json`
- `data/tasks/demos/verification-fail.json`

### Modify

- `README.md`
- `tests/integration/test_cli.py`
- `tests/unit/test_task_schema.py`

### Delete

- `data/tasks/demo.json`

No runner or tool implementation changes are required for this slice unless tests reveal a true bug in already-supported behavior.

---

## 7. Demo Definitions

### 7.1 `success.json`

Purpose:

- prove the full fixed-flow happy path

Required behavior:

- uses structured `entry_artifacts` for `search -> read -> patch -> verify`
- declares `allowed_tools` explicitly as:
  - `read_file`
  - `search_code`
  - `apply_patch`
- verification checks the expected replacement directly

Content choice:

- continue using the most stable existing README text anchor
- do not change the anchor casually in README edits

Reasoning:

- this keeps the success demo lightweight and repository-native
- the project already has a proven stable path here

### 7.2 `unauthorized-tool.json`

Purpose:

- prove that `allowed_tools` is enforced in execution, not only declared in schema

Required behavior:

- keep task content as close as practical to `success.json`
- deliberately omit the required `search_code` authorization
- fail for exactly one reason: unauthorized tool use

Reasoning:

- this isolates the authorization contract
- the sample should not fail because of missing files, ambiguous search, or verification drift

### 7.3 `ambiguous-search.json`

Purpose:

- prove that the system fails in `locate` when search returns more than one candidate file

Required behavior:

- point to a dedicated repository fixture file set rather than README
- create a stable situation where two files match the same `search_query`
- surface the failure as a locate-stage error

Reasoning:

- README is a poor anchor for deliberate ambiguity
- a dedicated fixture gives a stable and intentional multi-match setup

### 7.4 `verification-fail.json`

Purpose:

- prove that `verify` failure is stable and user-visible

Required behavior:

- use a task whose final failure reason is verification, not authorization and not locate/inspect failure
- prefer a minimal verification-only failing command over a more complex patch-plus-fail setup

Reasoning:

- a pure verification failure keeps the sample easy to understand
- this cleanly isolates the `verify` stage for CLI and README examples

---

## 8. README Design

README should be updated conservatively.

It should do exactly three things:

1. explain that demo tasks now live under `data/tasks/demos/`
2. show one direct command example per demo
3. state in one sentence what each demo proves

README should **not** in this slice:

- document trace internals in depth
- introduce batch demo execution
- describe future eval workflow
- imply wider task coverage than the repository currently supports

The README goal is clarity, not completeness.

---

## 9. Test Design

### 9.1 Schema / fixture coverage

Update `tests/unit/test_task_schema.py` to:

- load the new demo paths
- assert the demo fixture structure still matches expectations
- remove dependency on the deleted `data/tasks/demo.json`

### 9.2 CLI integration coverage

Update `tests/integration/test_cli.py` to:

- reference the new demo paths
- keep direct assertions for:
  - success
  - unauthorized tool
  - verification fail
- add CLI coverage for `ambiguous-search`

### 9.3 Demo suite presence coverage

Add a lightweight assertion that all four expected demo files exist.

This is not a discovery framework. It is only a guard against README/test drift.

---

## 10. Error Handling and Stability Rules

The demo suite should obey these stability rules:

- each demo proves one main behavior only
- failure demos must fail for the intended reason, not incidental environment issues
- verification commands should remain deterministic and local
- demo files should not depend on network access
- fixture text anchors should be treated as protected inputs once adopted by sample tasks

If a demo becomes fragile because it relies on mutable product prose, move its anchor to a dedicated fixture file rather than keep patching around instability.

---

## 11. Acceptance Criteria

This slice is complete when all of the following are true:

1. `data/tasks/demos/` contains exactly the intended demo suite entries for this slice
2. the old `data/tasks/demo.json` entry is removed
3. `task validate` works against each new demo file
4. `success.json` completes successfully
5. `unauthorized-tool.json` fails on authorization rejection
6. `ambiguous-search.json` fails in `locate`
7. `verification-fail.json` fails in `verify`
8. README points to the new demo paths and explains them accurately
9. unit and CLI integration tests no longer reference the removed old demo path

---

## 12. Compressed Context for Implementation

Use this as the minimal handoff context for the next implementation session:

- current branch/worktree: `phase-2c-tool-policy-state`
- previous slice already landed in this worktree:
  - runner-enforced `allowed_tools`
  - real `current_step` progression
- next slice is documentation + fixtures + test-path migration only
- do not expand scope into batch eval
- do not change runner logic unless a demo test reveals a real bug
- target output is a stable four-demo suite:
  - success
  - unauthorized-tool
  - ambiguous-search
  - verification-fail
