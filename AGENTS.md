# Working on the OpenH3-IR node pack

**This document is for changing the node pack.** Read it before changing anything. It is the set of
rules that are not preferences, a map of which file owns what, the ComfyUI frontend behaviour that
was measured rather than assumed, and how to prove a change is really live in a running ComfyUI.
There is no install path here, on purpose: that is README.md beside this file.

The compiler is the other half and it is another repository, `open-h3-ir`. This pack depends on the
published package and carries no copy of it: a compiler bug is fixed and released there, and nothing
here changes for it. Its own maintainer document is `AGENTS.md` in that repository, and the rules
about writing briefs, prompts, validators and evaluation all live there.

## The two things to hold your work against

```bash
pytest tests                                   # from the repository root, and the path matters
.venv/bin/python research/contract_falsification.py
```

**`pytest tests`, never a bare `pytest`.** This repository's root IS the pack, so it holds an
`__init__.py`, and ComfyUI Manager clones it into `custom_nodes` under a name with hyphens in it.
pytest turns any directory holding an `__init__.py` into a Package and imports that file before
running anything below it, and it names the module by walking up while each folder is a Python
identifier -- which `ComfyUI-OpenH3-IR` is not. So it imports as a bare `__init__` with no parent
package and the first relative import raises, in every test. `tests/pytest.ini` puts the rootdir
inside `tests`, which only takes effect when the path handed to pytest is inside it, and
`conftest.py` at the root turns the other invocation into one sentence. Measured on pytest 9.1.1;
neither `--import-mode=importlib` nor `consider_namespace_packages` nor `--ignore` avoids it.

The test count is not pinned here, because it moves every time anyone adds a test and a stale number
reads as a regression.

**The tests need `open-h3-ir` installed**, at or above the release `requirements.txt` names. Some of
them read the contract that package publishes and compare it to the copies this pack ships, which is
the whole point: it holds this pack against the released compiler rather than against a working tree
nobody has.

## Where things are

The repository root is the pack. That is not a layout preference: ComfyUI Manager clones a repository
straight into `custom_nodes` and imports the cloned directory's top level, so anything one folder
deeper produces zero nodes and no error anybody can act on.

The ComfyUI pack in the repository root is seven Python files plus a `web/` folder of five JS files, and imports nothing from `h3ir`. Two of those files are generated; both say so at the top:

| file | what it owns |
|---|---|
| `h3ir_client.py` | the service protocol, the option lists, the report. No ComfyUI, no torch, no third-party packages. |
| `media.py` | tensors and mappings to files on disk, content-addressed. No ComfyUI at module scope. |
| `nodes.py` | the four node schemas -- Main, Media, Setup and the optional Director -- the model loaders and the socket-to-file mapping. This is the only file that needs a canvas. |
| `contract.py` | the snapshot of the contract this pack was built against, and the decision about what a difference costs: what stops a queue, what is a line in the report. Imports nothing from `h3ir`. |
| `contract.json` | GENERATED. `h3ir contract` wrote it. The snapshot the file above reads. |
| `web/contract.data.js` | GENERATED. `h3ir contract --js` wrote it. The seven profiles, the camera table and the cap, for a panel that has to draw with nothing running. |
| `web/director.js` | the Director panel. It imports the three above rather than declaring them. See below. |

**Media and Director each carry a DOM board; Main and Setup are widget nodes** the theme draws, with
`prompt.js` putting an @ picker over Main's sentence. All of it is decoration in the strict sense:
each node's real state is ordinary widget values, and the two boards edit ONE string each -- the
tray's JSON on Media, the direction's on Director. Delete `web/` and every node still works, still
API-drives and still restores from a saved workflow, with the strings visible as themselves.

**The Director's stored directions are the pack's only piece of state outside a graph, and they are
deliberately outside the compiler.** They are files in ComfyUI's own per-user store,
`user/default/openh3ir/directors/<name>.json`, each holding exactly the two keys the node's field
holds, written and deleted through the `/userdata` routes ComfyUI already serves. The compiler's
service was the other candidate and it lost on three counts: it may be on another machine or down,
which would empty the list exactly when somebody is writing in it; it would have needed new write
routes on a service that binds `0.0.0.0`; and none of it buys anything a graph needs, because **a
graph carries the words, never a pointer to a name**. Nothing in `nodes.py`, `h3ir_client.py` or the
service knows the store exists, and that is the property to keep: delete `web/` and every stored
direction becomes irrelevant rather than missing.

**The seven that ship are a SEED, not a menu**, and that is the owner's shape: "just preload the
list with them, they should be able to be removed too." On first use `director.js` writes them into
that store as ordinary directions, and from then on the list is simply what the store holds. There
is no shipped category, no protected name, and no branch anywhere that recognises one — which is
what makes rename and delete work on them with no special case, and `tests/test_director_panel.py`
pins `DIRECTORS` to exactly two readings in the file, its declaration and the seed. **Seeding is
keyed on the FOLDER not existing**, because that is the only state meaning "never used": deleting
every direction leaves the folder, so a removed one stays removed. Deleting the folder by hand is
therefore the documented way to get the seven back, and the only way, on purpose.

`OpenH3IRDirector` takes one input, `profile`, and hands down one `H3IR_DIRECTOR` bundle. Main's
`director` socket is optional, and a graph without the node steers exactly as it always has. **That
absence is the default and it is load-bearing**, so anything that makes the node's presence matter to
a graph that does not have one is a bug. There is no `none` on it for the same reason: the node IS
the choice, and unplugging it is the absence of the only one rather than a third state.


## What crosses to the compiler, and how drift is made loud

The compiler publishes a contract and this pack holds a snapshot of the one it was built against.
The section below is the shared half of both maintainer documents: the compiler's copy says the same
things from the other side, and neither repository can test the other's. Read it before changing
anything either half can see.

the compiler's `h3ir/contract.py` is the compiler's statement of everything a client has to agree with it about,
and it is the answer to a problem the two halves of this repository are about to have: they ship to
two audiences, they are two repositories, and a test that opens the other half's source file and
reads it as text cannot exist.

**The pack becomes an all-in-one, so IN-PROCESS is the ordinary case.** A ComfyUI user installs the
pack, points it at their own language model, and works: no service to start, no port, no second
process. The compiler runs in the same Python ComfyUI runs, out of the installed `open-h3-ir`. HTTP
stays for a compiler on another machine and stops being the normal way in. The two are still
installed separately and still drift, which is exactly why the contract is not an HTTP thing --
in-process there is no round trip to reveal a mismatch at all.

**Read off the authority wherever there is one.** The roles come from `Role`, the profiles and the
camera table from `director.py`, the ceilings from `grid.py` and `shots.py`. Two lists are literals
and both are pinned by `the compiler's `tests/test_contract.py`` from this side, where the thing they describe is
importable: the wire field names, which live on pydantic models `contract.py` may not import because
a client runs it inside ComfyUI's Python; and the refusal codes, which are raised across two files.

**`CONTRACT_VERSION` is not the package version**, and `test_the_version_moves_when_any_part_of_the_contract_moves`
holds a digest of every section against it. Changing a director's prose without bumping it is a red
test. That is the whole ceremony and it is what stops the number becoming one nobody maintains.

**An unknown field is refused, never dropped.** `AssetIn` and `BriefIn` set `extra="forbid"` and a
handler turns that into `code: unknown-field` naming the key. pydantic's default is to ignore it,
and that default cost this project a real bug: see below.

#### The seven directors are still written down twice, and the copy is now generated

`h3ir/director.py` is the authority. `web/contract.data.js` carries the copy, for the reason
it always did -- the pack may be talking to another machine, and a text box that needs a running
service before it can show you a paragraph is empty exactly when somebody is trying to write in it.

What changed is that nobody types the copy. `h3ir contract --js` writes that file, `director.js`
imports `DIRECTORS`, `CAMERA_MOVES` and `MAX_NOTES` from it, and
`tests/test_contract_drift.py::test_the_generated_copies_are_what_this_compiler_publishes`
regenerates both copies and compares them byte for byte. So the instruction that used to be here --
*editing `h3ir/director.py` is not finished until `director.js` says the same words* -- is now:

```bash
h3ir contract       > contract.json
h3ir contract --js  > web/contract.data.js
```

Eleven thousand characters of prose maintained by hand in two languages is drift with a schedule.
That test runs here, against the `open-h3-ir` this pack depends on, which is a better comparison
than a sibling working tree: it holds this pack against the released compiler. Regenerating means
having a compiler installed and running the two commands above from the repository root.

#### Assert about the payload, never about the source text

Two of the three cross-boundary tests were guarding the wrong hop, and one of them had been wrong
for its whole life. a test in the compiler's suite asserted that `nodes.py` contains the line
`extra["replaces"] = slot.replaces` and that `AssetIn` declares a field called `replaces`. Both were
true. In between them, `h3ir_client._asset_facts` copied four keys out of `extra` into the request
and this was not one of them.

So the words a user typed to say who a picture takes over from never left the machine. The panel
collected them, `check_swaps` refused a swap that named nobody, the service declared the field, and
the compiler knew what to do with it -- and what the user got was the compiler refusing a question
they had already answered, or a swap bound to whoever the analyser happened to find in three sampled
frames. The test was green throughout, because it compared two pieces of source text and never
looked at the request.

`h3ir_client.payload_shape` runs the very functions that build the request and reports what comes
out. Anything asserting about what crosses uses that. A description of a payload taken from anywhere
else can be true while the payload is wrong.

#### Asking the compiler that is actually going to do the work

Two ways to get the live contract, and the choice is the caller's:

| where the compile happens | how to ask |
|---|---|
| the same Python, from the installed package | `contract.installed_contract()` |
| a service on another machine | `h3ir_client.fetch_contract(server)` |

**Never merge them or fall back from one to the other.** Reading the local package's contract while
compiling against a remote service compares this machine's version to another machine's work, and
refuses graphs that are fine. The compile node talks HTTP today, so it asks over HTTP, and a test
fails if it starts reading the local one.

**The compiler import is lazy, and stays lazy.** The old rule was "the pack imports nothing from
`h3ir`", which was right while the nodes only spoke HTTP and is wrong for an all-in-one. What
replaces it is narrower and still load-bearing: no `h3ir` import at module scope anywhere in the
pack, and exactly one function that does it at all. ComfyUI takes a pack whose import raises off the
menu entirely; a pack driving a remote compiler needs no local package; and the compiler brings
fastapi, uvicorn, pydantic and tiktoken, which have no business being pulled into ComfyUI's Python
on every start for a graph that may never compile. `installed_contract` answers None for absent,
broken and half-installed alike, because a client never fails on the CHECK.

#### What an in-process caller does NOT get for free

Measured, with fastapi and pydantic blocked: every compiler module imports except `service.py`.
That one holds `_to_brief`, the only conversion from a request into a `Brief`, and the eleven
refusals it raises along the way -- role resolution, the unknown-role message, the soundtrack
pairing, the upload checks.

So an in-process caller has two options and both cost something. Reuse that conversion and fastapi
comes into ComfyUI's Python with it. Build `models.Brief` and `models.AssetRef` directly and the
field names are checked by Python at call time, which is loud and free, but `role_stated` and the
pairing rules become the caller's to get right -- and `role_stated` is silent when it is wrong,
because mode inference reads it.

This pack is well placed for the second option: it states every role explicitly and never infers
one, so `role_stated` is always true for it and the unknown-role refusal is pre-empted by the
contract check. A caller that under-specifies is not. **`ROLE_OF_THE_FIELD_LISTS` is published in
the contract for this reason**: the field lists describe a `POST /v1/briefs` request and NOT the
dataclasses, and the two are similar enough to be mistaken for each other by somebody building the
all-in-one.

#### Two halves at different versions have to keep working

`contract.py` decides what a difference costs, and it decides it against **what this graph is
sending**, not against everything the pack can do. A pack that knows about `replaces` talking to a
compiler that does not is perfectly good for every brief that replaces nobody, and refusing those
would be breaking working setups to protect a feature they are not using.

    stop      the compiler cannot do what this graph is asking. Refused before any media travels,
              naming the field or the slot and which half to update.
    note      something differs and this graph does not depend on it. One line in the report.
    silence   nothing differs, or nothing either half can see.

A drifted director copy is never a stop: the Director node sends the prose in its box, so what
compiles is always what the canvas showed. A service too old to publish a contract is one note, not
a failure.

#### The scan that saw one refusal out of twelve

`compile.py` raises twelve refusal codes as a `BriefRefused`. The test that was supposed to prove
every refusal reaches the node pack with a sentence attached scanned for `super().__init__("...")`,
which is how exactly one of them is raised. The other eleven -- every refusal about a contradictory
request, including all four about who a picture replaces -- were invisible to it, and reached the
user through a branch that says "the service rejected the request".

They are published now, `h3ir_client.REFUSED_AS_ASKED` gives the class one branch, and
`tests/test_comfyui_node.py` reads its list from the shipped contract instead of from the
compiler's source, which is what carried it across the split.


## ComfyUI frontend mechanics, measured rather than assumed

Four of these cost a rebuild of the node surface to discover. They are recorded so nobody re-derives
them, and each has a test in `tests/test_comfyui_schema.py` that fails if the surface stops respecting
it. Measured against `comfyui_frontend_package 1.48.7` and `comfy_api/latest/_io.py`.

- **`advanced` is not a hide.** The per-node expander exists only under Nodes 2.0 and is gated on the
  setting `Comfy.Node.AlwaysShowAdvancedWidgets`. Under the legacy canvas renderer it does nothing at
  all. Design as if every input is visible; treat the collapse as a bonus.
- **A label and its value share one row of about 38 characters.** So a long display name makes both
  unreadable. This is why every label in the pack is one or two words.
- **A multiline STRING with no placeholder prints its own input id** on the canvas:
  `addMultilineWidget` calls `createMultilineInputElement(default, placeholder || name)`. On a
  multiline widget the placeholder is the only label there is, so it has to be the label and the
  example at once and its first line has to stand alone under truncation. A **single-line** STRING's
  placeholder is not drawn at all on the legacy canvas, so there the display name carries everything.
- **Autogrow socket labels come from `names[ordinal]`, or from `prefix + ordinal` zero-based, and they
  overwrite whatever the template declared.** `autogrowOrdinalToName` returns
  `{name, display_name: s}` and `s` wins. So `TemplatePrefix` gives you `reference_0` on the canvas no
  matter what the template's `display_name` says, and `TemplateNames` is the only way to get one-based
  readable labels. Ids with a space in them (`pictures.picture 1`) round-trip through the API format
  and the workflow save without trouble; verified by running one.
- **The frontend already supports several inputs per grown item** (`inputSpecs` is a list and
  `ensureWidgetForInput` runs when its length is not 1), but the Python side takes a single template
  input and `_expand_schema_for_dynamic` reads only the first. That is the mechanical reason the
  picture notes are one positional block and a clip's role lives on a satellite node, not a preference.
- **An AUDIO is a Mapping, not necessarily a dict.** Load Video (Upload) hands out a `LazyAudioMap`
  that shells out to ffmpeg on first key access. `isinstance(audio, dict)` refuses it.
- **A DOM widget's wrapper follows `widget.width`, and the frontend rewrites that on every value
  change.** The Vue side patches the wrapper's inline style each render from a node layout pass, and
  what that pass computes is the node's *content* width, not the node box. Measured: choosing a
  director set `width` to 238 on a node that was still 480 wide, the panel's wrapper went to 218px,
  and the name field was squeezed to eleven pixels -- `Denis Villeneuve` drawn as `De`. It never
  recovered at any node size, and no `computeSize` on either the widget or the node changes it,
  because neither is what the wrapper reads. `width` unset is the state a widget starts in and the
  one that renders full-bleed, so a board that fills its node holds it there:
  `Object.defineProperty(w, "width", { get: () => null, set: () => {} })`. The media tray never hit
  this because it pins its node to one size; anything resizable has to say it.


## Proving a change is live in a running ComfyUI

**A ComfyUI install holds a COPY of this pack, not this checkout.** `custom_nodes/openh3ir` is a
directory somebody copied there; nothing links it to the tree you are editing unless somebody made a
link, and `dir /AL` (or `ls -l`) is how you find out rather than assuming. So a change you make here
is live in a running ComfyUI only after you have put it there.

The two halves fail differently, and the difference is what makes this a trap rather than an
inconvenience:

- **`web/*.js` is served from that copy on every page load.** So fetching
  `/extensions/openh3ir/tray.js` and diffing it against the tree is a real check of what the browser
  is running -- but a match proves only that the two files are equal right now, which is also what
  you see when somebody synced it an hour ago. It is evidence about the file, never about a link.
- **The `.py` files are imported once, at ComfyUI startup.** A copied-in change does nothing until
  the server restarts. This is the half that goes stale silently: the panel offers a new option
  because the JavaScript is current, the user picks it, and the queue refuses it because the Python
  is five days old.

Measured on 2026-08-20: the served `tray.js` matched this checkout byte for byte while `tray.py` in
the same install was five days behind, and the conclusion drawn from the first fact was that the
whole pack was live.

**The cheap read-out is the pack's own refusal.** Set the tray to whatever the change makes possible
and queue the graph. If the running Python predates the change, the node refuses it with the OLD
table's own sentence, naming the options it still believes in, and the failure lands on the Media
node before a model is loaded, so it costs no GPU and no minutes. A refusal quoting the state you
just left is the running process telling you which file it is holding, which is the same discipline
as reading the artifact back instead of trusting the code that wrote it.

**And there is one that costs no queue at all: ask the server for its own node table.**
`GET /object_info/<NodeId>` is built from the `.py` the process imported at startup, so it is the
schema the canvas is actually drawing. Diff it against `define_schema` in the tree and a stale import
is one read away, before anybody opens a browser.

Measured on 2026-08-21, and it is the same trap from the other end: `nodes.py` in the install
was byte-identical to this checkout -- every file was, `web/` included -- while
`/object_info/OpenH3IRDirector` answered with a twelve-field schema from an earlier session, a
`director` combo with `none` in it plus `moves`, `avoids` and a save/load `library`, none of which
exist in the file either copy holds. Equal files on both sides of a copy and a running process three
hours behind them. The `.pyc` timestamps under `custom_nodes/openh3ir/__pycache__` said the same
thing and are the other cheap tell: older than the `.py` beside them means the import is stale.


## Falsifying a guard

**Falsify every test you write. It is not ceremony. It is what distinguishes a test from a
comment.** Break the code the test covers, on purpose, and watch it go red.

**And a test that has never been seen failing is a test nobody has verified.** This suite shipped one
that was green for its whole life while the field it guarded was dropped in transit, so every check
holding the compiler and the pack together has a defect written for it in
`research/contract_falsification.py`: it plants the defect, proves the defect is live, runs the test
that claims to catch it, and puts the file back. Run it on a clean tree; 49 cases, all of which must
go red.

**It reports three outcomes, not two, and that distinction is the file's second draft.** RED is a
guard that fired. GREEN is a guard that did not. BROKEN is a case that never ran -- the anchor
moved, the write did not land, the edit made the module unimportable, or the test it names no
longer exists. The first draft printed the same thing for GREEN and BROKEN, and two cases hid in
that: one named a test that had been renamed, and one planted an unbalanced parenthesis. pytest
exits non-zero for a `SyntaxError` and for an unknown node id exactly as it does for a failing
assertion, so both printed RED for months of nothing. **Anything that plants defects has to prove it
planted them before it is allowed an opinion about the guard.**

Two traps it records rather than works around, because anything editing source in a loop will hit
them:

  * **Python validates a cached `.pyc` on (mtime, size) and mtime has one-second resolution.** A
    defect exactly as long as what it replaces, planted within a second of the restore before it,
    runs against the OLD bytecode. Five cases reported a guard that does not fire before
    `__pycache__` was wiped between them.
  * **`python -O` strips `assert`.** The first draft checked its anchors with one, so under `-O` a
    moved anchor became a silent no-op: nothing was edited, the test passed on untouched source,
    and the case printed GREEN. Nothing in that file uses `assert` any more.

