# Documentation

Documentation comes in two kinds. They have different audiences and different
languages, and they are never mixed.

| Directory | Audience | Language | Content |
|---|---|---|---|
| **[guide/](guide/)** | Outside readers and users | English only | What the project is, what it can do, how to run it |
| **[dev/](dev/)** | Developers | Chinese permitted | Requirements, decisions (ADRs), designs, measured evidence |

The root [README.md](../README.md) links to `guide/`, plus the data-source page
as the evidence for its headline numbers.

---

## guide/ — learn and use the project

| Document | Content |
|---|---|
| [Overview](guide/overview.md) | The question, the approach and the current scope |

Pages such as Getting Started, Results and Architecture are added when there is
something real to describe; the guide never documents a capability that does not
run yet.

## dev/ — developer documentation

Documents have one of two natures. **Evergreen** documents describe how things
are now and are rewritten in place. **Event** documents record something that
happened once and are frozen once written: corrections are appended, never
rewritten. Directories exist only for things that grow. The decision procedure
and the writing contract are in [dev/README.md](dev/README.md).

**Evergreen — what the project is now**

| Document | Content |
|---|---|
| [roadmap.md](dev/roadmap.md) | Capability phases and what each one must prove |
| [requirements/project-overview.md](dev/requirements/project-overview.md) | Positioning, the boundary with real-time apps, MVP scope |
| [requirements/business-objectives.md](dev/requirements/business-objectives.md) | BO-1 … BO-3, the prediction target, evaluation protocol, known constraints |
| [requirements/data-sources.md](dev/requirements/data-sources.md) | Measured structure of the primary source, the schedule join, candidate external factors |

**Event — what happened (frozen once written)**

| Directory | Content |
|---|---|
| [adr/](dev/adr/README.md) | The trade-off behind one decision; never renamed, never deleted |
| [design/](dev/design/README.md) | How one change is intended to be carried out |

`launch/` (how a change actually went live) and `postmortem/` are created with
their first document.

---

## Writing rules

- Directory names are semantic, never numeric prefixes. Numbers are only for ADR
  numbering.
- File names are always English kebab-case. Language differences show up in the
  body text, never in the path.
- Every document must be linked from this index exactly once.
- Prefer merging over splitting.
- Images go in `images/`, created with the first image.
- Every measured number carries when it was measured, how (a command or query
  that can be rerun) and against what (the live source, a file, a build).
- 🔴 **This repository is public-facing; private notes are not. The dependency
  runs one way only.** A private knowledge base may cite this repository; this
  repository never cites it: no titles, paths or links to private documents, and
  no context that only holds there (correspondence, course or career plans,
  personal schedules). The test: could a reader with this repository and nothing
  else verify the reference?

### Content that does not belong in this repository

| Content | Where it goes |
|---|---|
| Which files a change touched and how it was verified | Pull request description |
| Why a line is written a certain way | Code review |
| What a change did and why | Commit message |
| Progress, schedules, temporary blockers, status updates | Outside the repository |
