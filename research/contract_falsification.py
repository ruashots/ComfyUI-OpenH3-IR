#!/usr/bin/env python
"""Break each thing the contract guards, one at a time, and confirm the guard goes red.

A test that has never been seen failing is a test nobody has verified, and this suite has already
shipped one that was green for its whole life while the field it guarded was being dropped in
transit. So every check added for the compiler/pack contract has a defect written for it here: the
defect is planted, the test that claims to catch it is run, and the file is put back.

**One of these plants its defect in the INSTALLED compiler rather than in this repository**, because
that is the shape of the thing after the split: the compiler is a package this pack depends on, its
director prose can move under this pack in a release, and what has to go red then is the check that
the generated copies here are current. `in_the_compiler` resolves `h3ir` the way the interpreter
does and edits it there, with the same read-back, liveness probe and restore as everything else.

**The compiler's own thirteen cases are in the compiler's repository.** Its guards are its tests,
neither repository can run the other's, and neither list is complete on its own.

    .venv/bin/python research/contract_falsification.py

It edits the working tree and restores it, so run it on a clean tree and check `git status` after.

**Three outcomes, and the third one is the whole point of this file's second draft.**

    RED      the defect was planted, proved live, and the guard failed. What you want.
    GREEN    the defect was planted, proved live, and the guard passed anyway. A guard that
             does not guard.
    BROKEN   the case did not run. The anchor moved, the write did not land, the interpreter
             would not have seen it, or the test it names does not exist.

**GREEN and BROKEN used to print the same thing, and that is how a case hid.** An earlier draft
reported "the guard did not fire" whenever pytest exited non-zero -- so a case whose defect never
reached the file, and a guard that genuinely failed to catch a live defect, were indistinguishable.
Anything that plants defects has to prove it planted them before it is allowed an opinion about the
guard.

Every way this file was found to be able to lie, and what closes it:

  * **A missing anchor under `-O`.** The old draft checked its anchor with `assert`, and `python -O`
    strips asserts. A moved anchor then became a silent no-op: the file was never edited, the test
    passed on unmodified source, and the case printed GREEN. Measured, not supposed. Nothing here
    uses `assert` any more; every check raises `CaseBroken` explicitly.
  * **A write that does not land.** The bytes on disk are read back and compared to what was meant.
  * **Source the interpreter would not load.** A shadowing install, or a stale `.pyc`, and the test
    runs against code nobody edited. The module is imported in a subprocess and asked which file it
    came from and what is in it.
  * **A test id that does not exist.** pytest exits 4 for an unknown node id and 5 when nothing is
    collected, and the old draft counted both as RED, so a renamed test looked like a guard firing.
    Exit codes are now read for what they mean, and every id is collected before anything is
    planted.
  * **A case that proves nothing because its test was already failing.** Every named test is run on
    the clean tree first and must pass, or the RED that follows means nothing.

**The `__pycache__` wipe is load-bearing.** Python validates a cached `.pyc` on (mtime, size) and
mtime has one-second resolution. Several defects here are exactly as long as what they replace --
`9` for `6`, `ASSETS` for `BRIEFS`, `snapshot()` for `contract()` -- and land in the same second as
the restore before them, so the interpreter serves the OLD bytecode. Five cases lied that way before
the wipe existed. Note what the wipe does NOT cover on its own: a same-length edit is invisible to
the size check, which is why the liveness probe reads the source the interpreter actually resolved
rather than trusting the wipe.
"""
from __future__ import annotations

import hashlib
import pathlib
import shutil
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
PY = str(REPO / ".venv" / "bin" / "python")

# What pytest's exit codes mean. Only 1 is a test that ran and failed; everything else above 0 is
# this harness failing to ask the question, which is a different fact and must not read as RED.
TESTS_PASSED, TESTS_FAILED = 0, 1
CANNOT_ASK = {2: "pytest was interrupted", 3: "an internal pytest error",
              4: "pytest usage error, which is what an unknown test id looks like",
              5: "no tests were collected"}


# The pack lives at the repository root, so these are bare names. `contract.json` is not here: it is
# generated, and the case that proves the generated copies are checked plants its defect in the
# compiler that generates them instead.
TOUCHES = ["tray.py", "h3ir_client.py", "nodes.py", "contract.py", "compiler.py", "web_api.py",
           "web/director.js", "web/contract.data.js", "web/setup.js", "web/main.js",
           "web/prompt.js", "requirements.txt"]


def _compiler_dir() -> pathlib.Path:
    """Where `import h3ir` actually resolves to for the interpreter that runs the tests.

    Asked of that interpreter rather than of this one, and never guessed from a path: this pack is
    installed beside a compiler somebody else installed, and the whole point of the case that edits
    it is to be editing the file the tests will really load.
    """
    probe = subprocess.run([PY, "-c", "import h3ir, pathlib; print(pathlib.Path(h3ir.__file__).parent)"],
                           capture_output=True, text=True)
    if probe.returncode != 0:
        raise SystemExit("no `open-h3-ir` is installed for " + PY + ", so nothing here can run:\n"
                         + probe.stderr.strip()[-400:])
    return pathlib.Path(probe.stdout.strip())


COMPILER = _compiler_dir()

# The name this pack is imported under. ComfyUI names the package after the cloned folder, which has
# hyphens in it and cannot be spelled in an `import`, so the tests pin one and so does the probe
# below. It has to match `tests/conftest.py` or the probe would be importing a second copy.
PACKAGE = "openh3ir"

# Registering the repository root as a package, in one line, for a subprocess that has to import a
# pack module the way a test does. Without it `import contract` is a relative import with no parent
# and every liveness probe would report BROKEN for a reason that is not the defect.
BOOTSTRAP = (
    "import importlib.util,sys;"
    f"_s=importlib.util.spec_from_file_location({PACKAGE!r}, {str(REPO / '__init__.py')!r},"
    f" submodule_search_locations=[{str(REPO)!r}]);"
    f"_m=importlib.util.module_from_spec(_s);sys.modules[{PACKAGE!r}]=_m;_s.loader.exec_module(_m);")


class CaseBroken(RuntimeError):
    """This case did not run. Never reported as a guard that failed to fire."""


_IMPORTABLE: set[str] | None = None


def _importable() -> set[str]:
    """Which of the modules these cases touch can be imported here AT ALL, measured on the clean
    tree once.

    One file cannot: `nodes.py` reaches for ComfyUI's node API at module scope, so it does not
    import outside a canvas at all, and `tests/test_comfyui_schema.py` reads it as source instead.
    An import probe on it would report BROKEN for a reason that has nothing to do with the defect,
    which is the same class of lie this whole draft exists to remove, arriving from the other side.
    """
    global _IMPORTABLE
    if _IMPORTABLE is None:
        names = sorted({_module_of(f) for f in TOUCHES if f.endswith(".py")})
        probe = subprocess.run(
            [PY, "-B", "-c", BOOTSTRAP + "import importlib\n"
             f"for n in {names!r}:\n"
             "    try:\n        importlib.import_module(n)\n        print(n)\n"
             "    except Exception:\n        pass"],
            cwd=REPO, capture_output=True, text=True)
        _IMPORTABLE = set(probe.stdout.split())
    return _IMPORTABLE


def _module_of(rel: str) -> str:
    """The name a pack file is imported under: the package, then the file. `web/director.js` and
    anything else that is not Python has no name here and never reaches this."""
    return f"{PACKAGE}." + rel[:-3].replace("/", ".")


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


class Defect:
    """One planted defect, and everything needed to prove it was really planted.

    `plant` refuses rather than returns on every way the edit can fail to happen, because a defect
    that is not in the file is a case that did not run and the two must never print the same thing.
    """

    def __init__(self, rel: str, old: str, new: str):
        self.rel, self.old, self.new = rel, old, new

    # What a subprocess has to run before it can import this file. A pack module needs the root
    # registered as a package; the installed compiler is an ordinary import and needs nothing.
    preamble = BOOTSTRAP

    @property
    def path(self) -> pathlib.Path:
        return REPO / self.rel

    def plant(self) -> None:
        before = self.path.read_text(encoding="utf-8")
        found = before.count(self.old)
        if found != 1:
            raise CaseBroken(f"the anchor appears {found} times in {self.rel}, not once. It has "
                             "moved or been edited; fix the case, it is testing nothing.")
        wanted = before.replace(self.old, self.new)
        if wanted == before:
            raise CaseBroken(f"replacing the anchor in {self.rel} changes nothing")
        self.path.write_text(wanted, encoding="utf-8")
        on_disk = self.path.read_text(encoding="utf-8")
        if on_disk != wanted:
            raise CaseBroken(f"{self.rel} on disk is not what was written to it "
                             f"({_digest(on_disk)} against {_digest(wanted)})")

    @property
    def module(self) -> str | None:
        """The importable name of this file, or None when a test cannot be consuming it that way.

        `nodes.py` imports ComfyUI's node API at module scope and cannot be imported outside a
        canvas at all, which is why `tests/test_comfyui_schema.py` reads it as source. Whether that
        is true is MEASURED at startup rather than listed here, so a file that becomes importable
        later stops being an exception on its own.
        """
        if self.path.suffix != ".py":
            return None
        name = _module_of(self.rel)
        return name if name in _importable() else None

    def prove_live(self) -> str:
        """Confirm the tests would really see the edit, proved the way the tests consume the file.

        A module a test imports can be shadowed by an install or served from a stale cache, and
        neither shows up in a read-back, so it is imported in a subprocess and asked which file it
        came from and what is in it. A file a test reads as text -- every `.js`, the JSON, and the
        Python that cannot be imported here -- is already fully proved by the read-back in `plant`,
        and importing it would fail for reasons that have nothing to do with the defect.
        """
        module = self.module
        if module is None:
            return f"{self.rel} read from disk"
        wanted = _digest(self.path.read_text(encoding="utf-8"))
        probe = subprocess.run(
            [PY, "-B", "-c", self.preamble +
             "import importlib,hashlib;"
             f"m=importlib.import_module({module!r});"
             "src=open(m.__file__,encoding='utf-8').read();"
             "print(m.__file__);"
             "print(hashlib.sha256(src.encode()).hexdigest()[:16])"],
            cwd=REPO, capture_output=True, text=True)
        if probe.returncode != 0:
            raise CaseBroken(f"{module} imports on the clean tree and not with this defect in "
                             f"place, so the test below ran against nothing: "
                             f"{probe.stderr.strip()[-300:]}")
        loaded, got = (probe.stdout.strip().splitlines() + ["", ""])[:2]
        if pathlib.Path(loaded).resolve() != self.path.resolve():
            raise CaseBroken(f"{module} loads from {loaded}, not from the file this case edited. "
                             "Something on the path is shadowing the checkout.")
        if got != wanted:
            raise CaseBroken(f"{module} reads as {got} and the file on disk is {wanted}")
        return f"{module} loads {wanted} from the edited file"


class Installed(Defect):
    """A defect planted in the compiler this pack is installed beside, rather than in this pack.

    The split made the compiler a dependency, so the way its prose moves under this pack is a
    release: somebody upgrades `open-h3-ir`, the seven directions change, and the generated copies
    in `web/` and `contract.json` are now stale. That is the one drift this repository cannot cause
    and has to notice, so it is proved from here by editing the compiler where it actually lives.

    Everything else is the same obligation. The write is read back, the module is imported in a
    subprocess and asked which file it came from, and the file is restored afterwards. The one
    difference is that `path` leaves this repository, so `git status` is not what tells you the tree
    was put back -- `main` compares the bytes.
    """

    @property
    def path(self) -> pathlib.Path:
        return COMPILER / self.rel

    @property
    def module(self) -> str | None:
        return f"h3ir.{self.rel[:-3]}" if self.path.suffix == ".py" else None

    preamble = ""


class Rewrite(Defect):
    """A defect that cannot be expressed as one substitution: a block that moves rather than
    changes. Same obligations, its own edit."""

    def __init__(self, rel: str, edit):
        super().__init__(rel, "", "")
        self.edit = edit

    def plant(self) -> None:
        before = self.path.read_text(encoding="utf-8")
        wanted = self.edit(before)
        if wanted == before:
            raise CaseBroken(f"the rewrite of {self.rel} changed nothing")
        self.path.write_text(wanted, encoding="utf-8")
        if self.path.read_text(encoding="utf-8") != wanted:
            raise CaseBroken(f"{self.rel} on disk is not what was written to it")


def patch(rel: str, old: str, new: str) -> Defect:
    return Defect(rel, old, new)


def in_the_compiler(rel: str, old: str, new: str) -> Installed:
    return Installed(rel, old, new)


def _move_the_check_later(source: str) -> str:
    """Somebody moves the contract check below the compile, so the media travels first.

    A real move rather than a deletion: the claim under test is the ORDER, and deleting the call
    would prove only that it exists.

    The compile is now two branches of one `if`, so the block moves past both of them. Moving it
    past only the in-process branch would leave the HTTP one still checked first and prove half of
    what this claims.
    """
    start = source.index("        # Are the two halves talking about the same thing?")
    end = source.index("        if here:\n            # Which model, settled on this side")
    block = source[start:end]
    if "contract_differences" not in block:
        raise CaseBroken("the check block was not found; this case is testing nothing")
    after = source.index("\n", source.index("timeout=float(machine[\"timeout_s\"]), brief=brief)",
                                            end)) + 1
    return source[:start] + source[end:after] + block + source[after:]


move_the_check_later = Rewrite("nodes.py", _move_the_check_later)


def _chip_reads_ok_first(source: str) -> str:
    """Somebody moves the `installed` branch below the two `ok` branches on the vision answer.

    A real move rather than a deletion, because the claim under test is the ORDER. The route answers
    `installed: false` together with `ok: false` when there is no compiler, so a panel that looks at
    `ok` first paints a red "vision off" about a model nobody ever asked.
    """
    start = source.index("    if (got.installed === false) {")
    end = source.index("    if (got.ok === true) {")
    block = source[start:end]
    if "compilerTrouble" not in block:
        raise CaseBroken("the installed branch was not found; this case is testing nothing")
    after = source.index("    } else {\n      // Nothing is known", end)
    return source[:start] + source[end:after] + block + source[after:]


chip_reads_ok_first = Rewrite("web/setup.js", _chip_reads_ok_first)


CASES = [
    ("a director's prose moves in the compiler and the copies here are not regenerated",
     in_the_compiler("director.py", "The camera is mounted and travelling",
                     "The camera is bolted down and travelling"),
     "tests/test_contract_drift.py::test_the_generated_copies_are_what_this_compiler_publishes"),

    ("the generated browser copy is hand-edited",
     patch("web/contract.data.js", 'name: "James Cameron"', 'name: "J. Cameron"'),
     "tests/test_contract_drift.py::test_the_generated_copies_are_what_this_compiler_publishes"),

    ("an export the panel imports is renamed in the generated copy",
     patch("web/contract.data.js", "export const CAMERA_MOVES",
           "export const CAMERA_MOVE_NAMES"),
     "tests/test_director_panel.py::test_the_generated_copy_exports_everything_the_panel_imports"),

    ("the panel declares its own directions again instead of importing them",
     patch("web/director.js", "const VERSION = \"director v3\";",
           "const DIRECTORS = [];\nconst VERSION = \"director v3\";"),
     "tests/test_director_panel.py::test_the_panel_reads_the_generated_copy_rather_than_declaring_its_own"),

    ("who a picture replaces stops being copied into the request (the live bug)",
     patch("h3ir_client.py",
           '    if str(extra.get("replaces") or "").strip():\n'
           '        a["replaces"] = str(extra["replaces"]).strip()\n',
           ""),
     "tests/test_contract_drift.py::test_who_a_picture_replaces_reaches_the_request"),

    ("an empty replaces field starts travelling as an empty string",
     patch("h3ir_client.py", 'if str(extra.get("replaces") or "").strip():',
           'if "replaces" in extra:'),
     "tests/test_contract_drift.py::test_a_picture_that_replaces_nobody_says_nothing_about_it"),

    ("the tray offers a job the compiler does not take",
     patch("tray.py", '"storyboard": "storyboard",',
           '"storyboard": "storyboard",\n    "a hologram": "hologram",'),
     "tests/test_contract_drift.py::test_every_job_the_tray_offers_is_a_job_the_compiler_takes"),

    ("the pack offers a shot pin the compiler clamps away",
     patch("h3ir_client.py", "MAX_SHOTS = 10   # the service's PINNED_SHOTS_MAX",
           "MAX_SHOTS = 14   # the service's PINNED_SHOTS_MAX"),
     "tests/test_contract_drift.py::test_the_shot_ceiling_the_pack_offers_is_the_one_the_contract_publishes"),

    ("the pack offers a creativity setting the compiler stopped taking",
     patch("h3ir_client.py",
           'CREATIVITY = ("restrained", "balanced", "bold", "extreme")',
           'CREATIVITY = ("restrained", "balanced", "bold", "extreme", "unhinged")'),
     "tests/test_contract_drift.py::test_the_option_lists_the_pack_draws_are_the_ones_the_contract_publishes"),

    ("the tray refuses at a capacity that is not H3's",
     patch("tray.py", 'CAPACITY = {"picture": 9, "video": 3, "sound": 3}',
           'CAPACITY = {"picture": 6, "video": 3, "sound": 3}'),
     "tests/test_contract_drift.py::test_the_capacity_the_tray_refuses_at_is_the_compilers_own"),

    ("a missing field becomes a note instead of stopping the graph",
     patch("contract.py",
           'out.append(Difference(stop=True, message=(\n'
           '                f"this graph says something {where} that {half.where} does not understand: "',
           'out.append(Difference(stop=False, message=(\n'
           '                f"this graph says something {where} that {half.where} does not understand: "'),
     "tests/test_contract_drift.py::test_a_field_the_service_cannot_take_stops_the_graph_and_names_it "
     "tests/test_contract_drift.py::test_a_brief_setting_the_service_cannot_take_stops_the_graph_too"),

    ("a missing role becomes a note instead of stopping the graph",
     patch("contract.py",
           "        out.append(Difference(stop=True, message=(\n"
           "            f'a slot in the tray is set to",
           "        out.append(Difference(stop=False, message=(\n"
           "            f'a slot in the tray is set to"),
     "tests/test_contract_drift.py::test_a_slot_set_to_a_job_the_service_has_no_name_for_stops_the_graph"),

    ("a drifted director copy starts stopping renders it has no business stopping",
     patch("contract.py",
           '        out.append(Difference(\n'
           '            f"the seven directions this node pack ships are not the ones {half.where} publishes. "',
           '        out.append(Difference(stop=True, message=\n'
           '            f"the seven directions this node pack ships are not the ones {half.where} publishes. "'),
     "tests/test_contract_drift.py::test_a_drifted_direction_is_reported_and_never_stops_a_render"),

    ("an older service with nothing new in the graph is stopped anyway",
     patch("contract.py", "        for field in sending:\n            if field in known:\n                continue",
           "        for field in list(sending) + ['replaces']:\n            if field in known:\n                continue"),
     "tests/test_contract_drift.py::test_the_same_older_service_is_fine_for_a_graph_that_does_not_use_the_new_thing"),

    ("a service too old to publish a contract becomes a failure",
     patch("contract.py", '    if live is None:\n        return [Difference(',
           '    if live is None:\n        return [Difference(stop=True, message='),
     "tests/test_contract_drift.py::test_a_service_too_old_to_publish_a_contract_is_a_note_and_never_a_failure"),

    ("a job only the service can do stops being reported",
     patch("contract.py", "    out += _what_this_pack_cannot_reach(live, half)\n", ""),
     "tests/test_contract_drift.py::test_a_job_the_service_takes_and_the_pack_cannot_offer_is_reported_and_never_stops"),

    ("a moved limit stops being reported",
     patch("contract.py", "    out += _limits_that_moved(live, half)\n", ""),
     "tests/test_contract_drift.py::test_a_limit_that_moved_is_reported_in_words_a_user_reads"),

    ("a difference stops naming which service it is about",
     patch("contract.py", 'f"this graph says something {where} that {half.where} does not understand: "',
           'f"this graph says something {where} that the compiler does not understand: "'),
     "tests/test_contract_drift.py::test_every_difference_names_the_service_it_is_about"),

    ("the contract is asked for only after the media has been sent", move_the_check_later,
     "tests/test_contract_drift.py::test_the_check_happens_before_the_media_travels"),

    ("a difference that stops the graph stops raising",
     patch("nodes.py", "        if stops:\n            raise ServiceError",
           "        if False and stops:\n            raise ServiceError"),
     "tests/test_contract_drift.py::test_the_node_refuses_on_a_stop_and_reports_the_rest"),

    ("the notes never reach the report",
     patch("nodes.py",
           '        for gap in gaps:\n            text += "\\n" + line("note", gap.message)\n', ""),
     "tests/test_contract_drift.py::test_the_node_refuses_on_a_stop_and_reports_the_rest"),

    ("an unreachable service raises instead of answering None",
     patch("h3ir_client.py", "    try:\n        status, body = _request(server, \"/v1/contract\", timeout=timeout)\n    except ServiceError:\n        return None",
           "    status, body = _request(server, \"/v1/contract\", timeout=timeout)"),
     "tests/test_contract_drift.py::test_asking_an_unreachable_service_is_never_an_exception "
     "tests/test_contract_drift.py::test_a_service_error_while_asking_is_swallowed_rather_than_raised"),

    ("anything with a 200 is treated as a contract",
     patch("h3ir_client.py",
           '    if status != 200 or not isinstance(body, dict) or "contract_version" not in body:\n        return None',
           "    if status != 200:\n        return None"),
     "tests/test_contract_drift.py::test_a_service_that_answers_with_something_else_is_treated_as_publishing_nothing"),

    ("the pack starts importing the compiler",
     patch("tray.py", "import json\nimport re",
           "import json\nimport re\n\nimport h3ir.contract"),
     "tests/test_contract_drift.py::test_the_pack_never_imports_the_compiler_while_it_is_being_imported"),

    ("the em dash rule loses its reach over the panel",
     patch("web/director.js", 'const SAVED_DIR = "openh3ir/directors";',
           'const SAVED_DIR = "openh3ir/directors";\nconst OOPS = "a note — with a machine tell";'),
     "tests/test_director_panel.py::test_no_em_dash_reaches_anything_the_owner_reads"),

    ("a published refusal loses its branch in the client",
     patch("h3ir_client.py", '"replacement-target-ambiguous", "replacement-target-unnamed",',
           '"replacement-target-unnamed",'),
     "tests/test_comfyui_node.py"),

    ("the client groups a refusal the compiler no longer makes",
     patch("h3ir_client.py", '"aspect-invalid", "director-profile-invalid",',
           '"aspect-was-invalid", "director-profile-invalid",'),
     "tests/test_contract_drift.py::test_the_refusals_the_client_groups_are_all_refusals_the_compiler_still_makes"),

    ("a refusal offers the user raw role tokens instead of the words on the dropdown",
     patch("contract.py",
           "    return T.WORDS_FOR_ROLE.get(TRAY_KIND.get(kind, \"\"), {}).get(role, role)",
           "    return role"),
     "tests/test_contract_drift.py::test_a_slot_set_to_a_job_the_service_has_no_name_for_stops_the_graph"),

    ("the pack tells people to install a version it does not require",
     patch("contract.py", 'FIRST_PUBLISHING_RELEASE = "0.3.0"',
           'FIRST_PUBLISHING_RELEASE = "0.2.0"'),
     "tests/test_contract_drift.py::test_the_version_the_pack_tells_people_to_install_is_the_one_it_requires"),

    ("an optional key is described by a stand-in instead of the real value",
     patch("h3ir_client.py",
           "transcripts=dict(transcripts or {}), **brief))",
           "transcripts={}, **brief))"),
     "tests/test_contract_drift.py::test_the_optional_keys_are_described_by_what_the_graph_actually_carries"),

    ("the node stops passing the graph's real transcripts to the check",
     patch("nodes.py", "payload_shape(written, brief, transcripts)",
           "payload_shape(written, brief)"),
     "tests/test_contract_drift.py::test_the_node_passes_the_graphs_own_transcripts_to_the_check"),

    ("the pack imports the compiler while ComfyUI is loading it",
     patch("contract.py", "from . import tray as T",
           "from . import tray as T\nimport h3ir.contract"),
     "tests/test_contract_drift.py::test_the_pack_never_imports_the_compiler_while_it_is_being_imported"),

    ("a second place in the pack reaches for the compiler",
     patch("h3ir_client.py", "def payload_shape(",
           "def _also_imports_it():\n    from h3ir import contract\n    return contract\n\n\ndef payload_shape("),
     "tests/test_contract_drift.py::test_every_reach_for_the_compiler_is_in_the_one_module_that_owns_them"),

    ("an absent compiler raises instead of answering None",
     patch("compiler.py",
           "    try:\n        from h3ir.contract import contract\n    except Exception:      # noqa: BLE001 - absent, broken, or half-installed are all \"no contract\"\n        return None",
           "    from h3ir.contract import contract"),
     "tests/test_contract_drift.py::test_no_compiler_in_this_python_is_an_answer_rather_than_a_crash"),

    ("a half-installed compiler's rubbish is taken for a contract",
     patch("compiler.py",
           '    return got if isinstance(got, dict) and "contract_version" in got else None',
           "    return got"),
     "tests/test_contract_drift.py::test_a_compiler_that_answers_with_rubbish_is_treated_as_absent"),

    ("the pack compares a local compiler against the remote one it compiles with",
     patch("contract.py", "            ask=lambda: fetch_contract(address, timeout=timeout))",
           "            ask=lambda: _compiler.installed_contract() or fetch_contract("
           "address, timeout=timeout))"),
     "tests/test_contract_drift.py::test_the_pack_never_reaches_for_the_compiler_while_it_is_talking_to_a_service"),

    # ------------------------------------------------------- the compiler running in this Python

    ("a half-installed compiler is reported as one that was never installed",
     patch("compiler.py",
           '        return "broken", (f"{DISTRIBUTION} is installed and something it needs is not: {e}")',
           '        return "absent", str(e)'),
     "tests/test_in_process.py::test_an_absent_compiler_and_a_broken_one_are_never_reported_as_each_other"),

    ("the pack checks for a local compiler before it knows whether the graph needs one",
     patch("nodes.py",
           '        here = not machine["server"]\n'
           '        llm_url = llm_url_from = llm_model = llm_model_from = ""\n'
           "        if here:",
           '        require_installed()\n'
           '        here = not machine["server"]\n'
           '        llm_url = llm_url_from = llm_model = llm_model_from = ""\n'
           "        if here:"),
     "tests/test_in_process.py::test_an_absent_compiler_is_never_mentioned_to_a_graph_that_compiles_elsewhere"),

    ("who a picture replaces stops crossing into the in-process brief",
     patch("compiler.py", '            replaces=str(a.get("replaces") or "").strip(), role_stated=True))',
           "            replaces=\"\", role_stated=True))"),
     "tests/test_in_process.py::test_the_two_paths_build_the_same_brief_from_the_same_graph "
     "tests/test_in_process.py::test_who_a_picture_replaces_survives_the_in_process_conversion"),

    ("the in-process brief forgets that the caller stated every role",
     patch("compiler.py", '            replaces=str(a.get("replaces") or "").strip(), role_stated=True))',
           '            replaces=str(a.get("replaces") or "").strip(), role_stated=False))'),
     "tests/test_in_process.py::test_the_role_is_recorded_as_stated_because_this_pack_always_states_it "
     "tests/test_in_process.py::test_the_two_paths_build_the_same_brief_from_the_same_graph"),

    ("a soundtrack's pointer at its clip is left as a path instead of a digest",
     patch("compiler.py", "            paired_video_sha256=(sha_of(paired) if paired else None),",
           "            paired_video_sha256=(str(paired) if paired else None),"),
     "tests/test_in_process.py::test_a_soundtrack_points_at_its_clip_by_content_and_not_by_path "
     "tests/test_in_process.py::test_the_two_paths_build_the_same_brief_from_the_same_graph"),

    ("a key the in-process conversion does not know is dropped instead of refused",
     patch("compiler.py", "    unknown = sorted(set(payload) - _BRIEF_KEYS)",
           "    unknown = []"),
     "tests/test_in_process.py::test_a_brief_key_the_conversion_does_not_know_is_refused_rather_than_dropped"),

    ("a key on an attachment is dropped instead of refused",
     patch("compiler.py", "        extra = sorted(set(a) - _ASSET_KEYS)", "        extra = []"),
     "tests/test_in_process.py::test_an_attachment_key_the_conversion_does_not_know_is_refused_too"),

    ("the in-process answer loses the retention marker the report prints",
     patch("compiler.py", '                    "retention": retention.get(m.label, "")}',
           '                    "retention": ""}'),
     "tests/test_in_process.py::test_the_in_process_answer_is_what_the_service_would_have_replied"),

    ("a clarification is assumed away instead of stopping the queue",
     patch("compiler.py", "    if asked:\n", "    if False:\n"),
     "tests/test_in_process.py::test_one_decision_the_compiler_will_not_take_stops_the_queue_rather_than_being_assumed"),

    ("the compiler's own broken invariant is handed to the user as their contradiction",
     patch("compiler.py",
           '        theirs = [f for f in doc.errors if f.rule.split("-")[0] in',
           '        theirs = [f for f in doc.errors if True or f.rule.split("-")[0] in'),
     "tests/test_in_process.py::test_the_compilers_own_broken_invariant_is_reported_as_its_bug_and_not_the_users"),

    ("a missing language model address falls back to the compiler's placeholder",
     patch("compiler.py", '    from_env = os.environ.get(LLM_URL_ENV, "").strip()\n'
                          "    if from_env:\n"
                          '        return from_env, f"{LLM_URL_ENV} in ComfyUI\'s environment"',
           '    from_env = os.environ.get(LLM_URL_ENV, "").strip()\n'
           '    return from_env or "http://127.0.0.1:8000/v1", "a default"'),
     "tests/test_in_process.py::test_no_address_anywhere_is_refused_by_naming_the_field_on_the_node "
     "tests/test_in_process.py::test_the_compiler_is_never_left_to_pick_the_default_address"),

    ("the node guesses which of several models can see",
     patch("compiler.py", "    if len(choices) == 1:\n        return choices[0],",
           "    if len(choices) >= 1:\n        return choices[0],"),
     "tests/test_in_process.py::test_several_models_are_refused_by_listing_them_rather_than_by_guessing"),

    ("one checkpoint under several names is offered as several models",
     patch("compiler.py", '        groups.setdefault(str(m.get("root") or m["id"]), []).append(m)',
           '        groups.setdefault(str(m["id"]), []).append(m)'),
     "tests/test_in_process.py::test_several_names_for_one_checkpoint_are_one_choice"),

    ("the name that survives a collapse is the repository instead of the one the operator chose",
     patch("compiler.py",
           '        chosen = next((str(m["id"]) for m in members\n'
           '                       if str(m["id"]) != str(m.get("root") or m["id"])), "")',
           '        chosen = ""'),
     "tests/test_in_process.py::test_several_names_for_one_checkpoint_are_one_choice "
     "tests/test_in_process.py::test_several_chosen_names_for_one_checkpoint_keep_the_first_the_server_listed"),

    # The mistake this guards is not a typo. `root` reads like the canonical name of a checkpoint,
    # so offering it is the tidy-looking rewrite somebody reaches for -- and on a server started
    # from a local directory it is a filesystem path the server has no route for.
    ("a name the server never published is offered as something to pick",
     patch("compiler.py", "        keep = chosen or str(members[0][\"id\"])",
           "        keep = str(members[0].get(\"root\") or members[0][\"id\"])"),
     "tests/test_in_process.py::test_the_surviving_name_is_always_one_the_server_published_as_an_id "
     "tests/test_in_process.py::test_several_names_for_one_checkpoint_are_one_choice"),

    ("the names collapsed into one row stop being reported beside it",
     patch("compiler.py", "        if others:\n            collapsed[keep] = others",
           "        if False:\n            collapsed[keep] = others"),
     "tests/test_in_process.py::test_several_names_for_one_checkpoint_are_one_choice"),

    ("a timeout on the vision check is reported as a model that cannot see",
     patch("compiler.py", '            return {"installed": True, "ok": None, "reason": (',
           '            return {"installed": True, "ok": False, "reason": ('),
     "tests/test_in_process.py::test_a_model_that_cannot_see_is_reported_as_that_and_a_timeout_is_reported_as_neither"),

    ("a missing model is reported as a model that cannot see (the live bug)",
     patch("compiler.py", "    status = getattr(refused, \"status\", 0)\n"
                          "    if status in (400, 415, 422):",
           "    status = getattr(refused, \"status\", 0)\n"
           "    if status:"),
     "tests/test_in_process.py::test_a_refused_request_is_only_a_verdict_about_vision_when_it_is_one"),

    ("a difference tells a ComfyUI with no service to restart one",
     patch("contract.py",
           '            f"`{field}`. This node pack is newer than it, and it refuses a field it does not "',
           '            f"`{field}`. This node pack is newer than the service, and the service refuses "'),
     "tests/test_contract_drift.py::test_a_difference_about_the_compiler_in_this_python_never_says_service"),

    ("the note about an old compiler in this Python names a service to update",
     patch("contract.py", "f\"there. {half.update} Then the two are checked before a queue instead.\")]",
           "\"there. Update open-h3-ir where the service runs, then restart h3ir serve.\")]"),
     "tests/test_contract_drift.py::test_a_compiler_in_this_python_too_old_to_publish_a_contract_says_what_to_upgrade"),

    ("the report stops saying which compiler wrote the brief",
     patch("h3ir_client.py",
           '        line("brief id", f"{prompt_body.get(\'brief_id\', \'\')}   from {compiler}"),',
           '        line("brief id", f"{prompt_body.get(\'brief_id\', \'\')}"),'),
     "tests/test_in_process.py::test_the_report_names_which_compiler_wrote_the_brief"),

    ("the report stops naming the language model that wrote the brief",
     patch("nodes.py", '            text += "\\n" + line("written by", f"{llm_model}  at {llm_url}")',
           '            pass'),
     "tests/test_in_process.py::test_the_language_model_that_wrote_the_brief_is_named_in_the_report"),

    ("a language model field a service graph cannot use is ignored in silence",
     patch("nodes.py", '        elif machine["llm_url"] or machine["llm_model"]:',
           "        elif False:"),
     "tests/test_in_process.py::test_a_language_model_field_a_service_graph_cannot_use_is_reported_and_never_ignored"),

    ("the pack stops declaring the compiler it runs in process",
     patch("requirements.txt", "open-h3-ir>=0.3.0", "# open-h3-ir>=0.3.0"),
     "tests/test_in_process.py::test_the_pack_declares_the_compiler_it_now_runs_in_process "
     "tests/test_contract_drift.py::test_the_version_the_pack_tells_people_to_install_is_the_one_it_requires"),

    ("the in-process size ceiling drifts from the wire model's own",
     patch("compiler.py", "MEGAPIXELS_MIN, MEGAPIXELS_MAX = 0.25, 2.5",
           "MEGAPIXELS_MIN, MEGAPIXELS_MAX = 0.25, 4.0"),
     "tests/test_in_process.py::test_the_size_bounds_are_the_wire_models_own"),

    ("a new field is added in the middle of the Setup node and shifts every saved workflow",
     patch("nodes.py", '                io.String.Input(\n'
                       '                    "llm_url", display_name="language model"',
           '                io.String.Input(\n'
           '                    "llm_note", display_name="a note", default="", optional=True,\n'
           '                    tooltip="A note to yourself about this machine. It is never sent."),\n'
           '                io.String.Input(\n'
           '                    "llm_url", display_name="language model"'),
     "tests/test_comfyui_schema.py::test_the_setup_nodes_inputs_are_in_the_order_every_saved_workflow_depends_on"),

    ("an unreachable language model tells a node user to set an environment variable",
     patch("compiler.py", "    got = endpoint_report(url, timeout=10.0)\n    if got.get(\"ok\"):",
           "    got = endpoint_report(url, timeout=10.0)\n    if True:"),
     "tests/test_in_process.py::test_an_unreachable_language_model_never_tells_a_node_user_to_set_an_environment_variable"),

    ("a new Setup node opens pointing at a service nobody started",
     patch("nodes.py", '                    "server", display_name="compile on", default=""',
           '                    "server", display_name="compile on", default=DEFAULT_SERVER'),
     "tests/test_comfyui_schema.py::test_an_empty_compile_target_is_the_ordinary_case_and_the_field_says_so"),

    # ---------------------------------------------------------------------- the Setup panel

    ("the report line goes back to truncating instead of wrapping",
     patch("web/setup.js", "  overflow:hidden;min-height:4.2em;}",
           "  overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}"),
     "tests/test_setup_panel.py::test_the_report_is_a_box_that_wraps_rather_than_a_line_that_truncates "
     "tests/test_setup_panel.py::test_the_report_boxes_are_pinned_to_the_rows_the_longest_message_needs"),

    ("a quiet line loses its pin and starts negotiating for room",
     patch("web/setup.js", ".oh3s-lead{flex:0 0 auto;font-size:10px;line-height:1.45;color:rgba(243,239,230,.56);\n  min-height:2.9em;}",
           ".oh3s-lead{flex:0 0 auto;font-size:10px;line-height:1.45;color:rgba(243,239,230,.56);}"),
     "tests/test_setup_panel.py::test_every_quiet_line_is_pinned_so_none_of_them_reflows"),

    ("the spare space goes back above the headings",
     patch("web/setup.js", "  color:rgba(243,239,230,.56);flex-wrap:wrap;}",
           "  color:rgba(243,239,230,.56);flex-wrap:wrap;min-height:calc(4.5em + 7px);}"),
     "tests/test_setup_panel.py::test_the_spare_space_is_above_the_rule_and_never_above_a_heading"),

    # The anchor moved once already, when the sentence it named was rewritten. It is taken from the
    # line the guard itself reads now, so a rewrite of the message breaks the case loudly instead of
    # leaving it planting nothing.
    ("an instruction the panel wrote is shortened, not just somebody else's words",
     patch("web/setup.js",
           '                 + "with pictures or clips on the Media node will not work. A prompt with an empty "',
           '                 + Panel.quote("with pictures or clips on the Media node will not work. ", 20)'),
     "tests/test_setup_panel.py::test_only_quoted_material_is_ever_shortened"),

    ("a brand new node goes back to complaining about ComfyUI's own defaults",
     patch("web/setup.js", "    if (!FILES.some((f) => this.chosen(f.w))) {",
           "    if (false) {"),
     "tests/test_setup_panel.py::test_a_brand_new_node_says_what_happened_rather_than_complaining"),

    ("the wrong-row warning fires on a row nobody picked in",
     patch("web/setup.js", "      if (!this.chosen(w)) continue;", "      if (false) continue;"),
     "tests/test_setup_panel.py::test_neither_file_warning_fires_on_a_row_nobody_has_picked_in"),

    ("the same-file warning fires on two rows nobody picked in",
     patch("web/setup.js", '    if (this.chosen("video_vae") && this.chosen("audio_vae")\n        && video',
           "    if (video"),
     "tests/test_setup_panel.py::test_neither_file_warning_fires_on_a_row_nobody_has_picked_in"),

    ("whether a node is new starts being decided from a file name",
     patch("web/setup.js", "  chosen(name) { return this.configured || this.touched.has(name); }",
           "  chosen(name) { return String(this.w[name].value || \"\").includes(\"minimax\"); }"),
     "tests/test_setup_panel.py::test_a_new_node_is_known_from_how_it_was_built_and_never_from_a_file_name"),

    ("a value nobody chose is drawn as though somebody had",
     patch("web/setup.js", "      sel.classList.toggle(\"oh3s-untouched\", !this.chosen(f.w));", "      "),
     "tests/test_setup_panel.py::test_an_untouched_row_is_drawn_in_the_grey_the_address_example_uses"),

    ("a backtick reaches the CSS block and the whole panel stops parsing",
     patch("web/setup.js", ".oh3s-cue{color:#eb8219;}", "/* a `stray` tick */\n.oh3s-cue{color:#eb8219;}"),
     "tests/test_setup_panel.py::test_no_backtick_reaches_the_css_block"),

    ("a field on the panel is left with a placeholder and no label",
     patch("web/setup.js",
           'el("span", { class: "oh3s-wlabel", textContent: "endpoint" }), this.addrIn);',
           "this.addrIn);"),
     "tests/test_setup_panel.py::test_the_two_typed_fields_carry_a_label_inside_their_own_row"),

    ("a new field arrives with a placeholder standing in for its label",
     patch("web/setup.js", "      placeholder: EXAMPLE,",
           '      placeholder: "type the address of your language model",'),
     "tests/test_setup_panel.py::test_no_label_is_only_a_placeholder "
     "tests/test_setup_panel.py::test_the_endpoint_field_shows_an_example_and_still_has_its_label"),

    ("the api key becomes a widget value and rides out in every shared workflow",
     patch("web/setup.js", "    this.savedKey = key;\n    this.keyEditing = false;",
           "    this.w.llm_model.value = key;\n    this.savedKey = key;\n"
           "    this.keyEditing = false;"),
     "tests/test_setup_panel.py::test_the_api_key_never_becomes_a_widget_value"),

    ("the panel saves a key where the Python that uses it does not look",
     patch("compiler.py", 'KEY_STORE = "openh3ir/llm/keys.json"',
           'KEY_STORE = "openh3ir/keys.json"'),
     "tests/test_setup_panel.py::test_the_credential_is_stored_where_the_python_that_uses_it_reads_it"),

    ("a trailing slash on the address loses the credential",
     patch("compiler.py", '    address = (url or "").strip().rstrip("/")\n    if not address:',
           '    address = (url or "").strip()\n    if not address:'),
     "tests/test_setup_panel.py::test_a_stored_credential_reaches_the_compiler_and_an_absent_one_leaves_the_environment_alone"),

    ("moving the credential onto the node takes the environment channel away",
     patch("compiler.py", "    saved = endpoint_key(address)\n    if saved:\n"
                          '        fields["api_key"] = saved',
           '    fields["api_key"] = endpoint_key(address)'),
     "tests/test_setup_panel.py::test_a_stored_credential_reaches_the_compiler_and_an_absent_one_leaves_the_environment_alone"),

    ("an unreadable credential store takes the queue down instead of answering none",
     patch("compiler.py",
           "    except Exception:                     # noqa: BLE001 - absent, unreadable and empty are all none\n        return \"\"",
           "    except FileNotFoundError:\n        return \"\""),
     "tests/test_setup_panel.py::test_a_credential_store_that_cannot_be_read_is_no_credential_rather_than_a_failure"),

    ("the chip reads ok before it reads installed",
     chip_reads_ok_first,
     "tests/test_setup_panel.py::test_the_chip_reads_installed_before_it_reads_ok"),

    ("the vision check is fired with no model named",
     patch("web/setup.js", "  async look(url, id, run) {\n    if (!id) return;",
           "  async look(url, id, run) {"),
     "tests/test_setup_panel.py::test_the_vision_route_is_never_asked_about_an_empty_model"),

    ("a check that did not finish is painted as a model that cannot see",
     patch("web/setup.js", '  unknown: { text: "no answer", cls: "" },',
           '  unknown: { text: "no answer", cls: "oh3s-blind" },'),
     "tests/test_setup_panel.py::test_a_check_that_did_not_finish_is_never_painted_as_a_model_that_cannot_see"),

    ("a sentence on the panel is quietly reworded",
     patch("web/setup.js", '"no key. That endpoint does not ask for one."',
           '"No API key configured for this endpoint."'),
     "tests/test_setup_panel.py::test_the_panel_says_the_words_that_were_specified"),

    ("an em dash reaches something a person reads on the panel",
     patch("web/setup.js", 'this.say("Stopped. Nothing changed.");',
           'this.say("Stopped \u2014 nothing changed.");'),
     "tests/test_setup_panel.py::test_no_em_dash_reaches_anything_a_person_reads_on_this_panel"),

    ("the panel offers every id the server published instead of one per checkpoint",
     patch("web/setup.js", "    const rows = this.narrowed();\n    this.list.append(",
           "    const rows = (this.report && this.report.ids) || [];\n    this.list.append("),
     "tests/test_setup_panel.py::test_the_panel_offers_the_folded_list_and_never_every_id"),

    # The list of guessed addresses this used to edit is gone, and so is the test that held them to
    # loopback. The OTHER test it named still has a job -- nothing shipped may name a real machine on
    # a real network -- so the case is re-pointed at a place a LAN address can still get in.
    ("a real machine on a real network gets into something that ships",
     patch("web/setup.js", 'const SERVICE_EXAMPLE = "http://another-machine:8420";',
           'const SERVICE_EXAMPLE = "http://192.168.4.31:8420";'),
     "tests/test_setup_panel.py::test_nothing_in_the_pack_names_a_real_machine_on_anybody_s_network"),

    ("a dropped node starts reaching the network on its own again",
     patch("web/setup.js", "    this.render();\n    this.askCompiler();\n    this.readKey();",
           "    this.render();\n    this.askCompiler();\n    this.readKey();\n    this.test();"),
     "tests/test_setup_panel.py::test_a_fresh_node_makes_no_network_call_at_all"),

    ("the endpoint field gets a caret back that opens nothing",
     patch("web/setup.js",
           'el("span", { class: "oh3s-wlabel", textContent: "endpoint" }), this.addrIn);',
           'el("span", { class: "oh3s-wlabel", textContent: "endpoint" }), this.addrIn,\n'
           '      el("span", { class: "oh3s-caret", textContent: "x" }));'),
     "tests/test_setup_panel.py::test_the_endpoint_field_has_no_caret_because_there_is_nothing_to_open"),

    ("a label starts claiming who you buy from",
     patch("web/setup.js", 'class: "oh3s-wlabel", textContent: "endpoint"',
           'class: "oh3s-wlabel", textContent: "openai endpoint"'),
     "tests/test_setup_panel.py::test_the_endpoint_label_is_the_word_the_panel_already_uses_everywhere_else"),

    ("the fact about which servers work goes back to being nowhere",
     patch("web/setup.js", '        + "server that speaks the OpenAI API works.";', '        + "";'),
     "tests/test_setup_panel.py::test_the_openai_fact_is_a_sentence_rather_than_a_label"),

    ("the panel's wrong-row warning drifts from the compiler's own rule",
     patch("web/setup.js",
           'const FAMILY = { reference_model: "ref2va", frames_model: "fl2va" };',
           'const FAMILY = { reference_model: "ref-2-va", frames_model: "fl2va" };'),
     "tests/test_setup_panel.py::test_the_wrong_row_warning_is_the_compilers_own_rule"),

    ("the panel stops reading the file name only where the name settles the question",
     patch("web/setup.js", "      if (name.includes(other) && !name.includes(wanted)) {",
           "      if (name.includes(other)) {"),
     "tests/test_setup_panel.py::test_the_wrong_row_warning_is_the_compilers_own_rule"),

    ("the route stops telling the panel what the environment would give",
     patch("web_api.py", '            "env_url": env["url"],', '            "env_url": "",'),
     "tests/test_setup_panel.py::test_the_route_tells_the_panel_what_the_environment_would_give"),

    ("a connection that never opened is reported as an HTTP status",
     patch("compiler.py", r'    found = re.match(r"^HTTP (\d{3})$", str(answered or "").strip())',
           r'    found = re.search(r"(\d{3})", str(answered or "").strip())'),
     "tests/test_setup_panel.py::test_the_liveness_attempts_carry_the_status_that_tells_the_failures_apart"),

    ("the panel hides a widget the node does not have and takes the control away",
     patch("web/setup.js", '      const wanted = ["server", "llm_url", "llm_model",',
           '      const wanted = ["server", "llm_key", "llm_url", "llm_model",'),
     "tests/test_setup_panel.py::test_the_panel_drives_widgets_that_are_really_on_the_node"),

    # ----------------------------------------------------------------- the Main panel

    ("a field on the Main panel loses the label that survives typing",
     patch("web/main.js", 'this.row("resolution", "megapixels"),',
           'this.row("", "megapixels"),'),
     "tests/test_main_panel.py::test_every_row_carries_a_visible_label"),

    ("a label goes back to being a placeholder, so it vanishes at the first keystroke",
     patch("web/main.js",
           '    const kids = [el("span", { class: "oh3m-label", textContent: label }), value];',
           '    const kids = [el("span", { class: "oh3m-label", placeholder: label }), value];'),
     "tests/test_main_panel.py::test_the_label_is_a_real_element_and_not_a_placeholder"),

    ("the Main panel starts parsing the prompt itself instead of borrowing the parse",
     patch("web/main.js", "  renderReport() {\n    const f = promptFacts(this.node, this.box.value);",
           "  renderReport() {\n    const marks = this.box.value.split(/@speaks\\(/).length - 1;\n"
           "    const f = promptFacts(this.node, this.box.value);"),
     "tests/test_main_panel.py::test_the_panel_derives_no_fact_about_the_prompt_itself"),

    ("a shot count that cannot fit is taken away instead of dimmed",
     patch("web/main.js", "        on: held === String(n), dim: !fits, warn: true,",
           "        on: held === String(n), dim: !fits, warn: true, disabled: !fits,"),
     "tests/test_main_panel.py::test_a_count_that_cannot_fit_is_dimmed_and_told_what_it_needs_and_stays_clickable"),

    ("the Main panel offers a word the schema would refuse",
     patch("web/main.js", '  ["extreme", "pushes every choice harder"],',
           '  ["extreme", "pushes every choice harder"],\n  ["unhinged", "no limits at all"],'),
     "tests/test_main_panel.py::test_every_option_a_list_offers_is_a_value_the_schema_accepts"),

    ("the shot arithmetic on the panel drifts from the one the node states",
     patch("web/main.js", "const SECONDS_PER_SHOT = 1.2;", "const SECONDS_PER_SHOT = 0.8;"),
     "tests/test_main_panel.py::test_the_arithmetic_the_shot_list_shows_is_the_one_the_tooltip_states"),

    ("something other than the prompt box starts taking the pixels the node gains",
     patch("web/main.js",
           ".oh3m-msg{flex:0 0 auto;font-size:10px;line-height:1.4;color:rgba(243,239,230,.56);",
           ".oh3m-msg{flex:1 1 auto;font-size:10px;line-height:1.4;color:rgba(243,239,230,.56);"),
     "tests/test_main_panel.py::test_the_prompt_box_is_the_only_element_that_grows"),

    ("the panel drives a widget the Main node does not have",
     patch("web/main.js", 'const WIDGETS = ["intent", "seconds",',
           'const WIDGETS = ["intent", "tone", "seconds",'),
     "tests/test_main_panel.py::test_the_panel_drives_widgets_that_are_really_on_the_node"),

    ("the host's textarea is left floating on top of the panel that replaced it",
     patch("web/main.js", '    e.style.setProperty("display", "none", "important");\n', ""),
     "tests/test_main_panel.py::test_the_panel_hides_the_host_textarea_as_well_as_the_widget_row"),

    ("a backtick reaches the Main panel's stylesheet and the file stops parsing",
     patch("web/main.js", ".oh3m-msg.oh3m-bad{color:#f07070;}",
           ".oh3m-msg.oh3m-bad{color:#f07070;}\n/* the `oh3m-msg` box */"),
     "tests/test_main_panel.py::test_no_backtick_reaches_the_css_block "
     "tests/test_main_panel.py::test_the_panel_is_a_module_that_actually_parses"),

    ("a dash starts doing a comma's job in something a person reads",
     patch("web/main.js", 'textContent: "one prompt to a ready H3 job"',
           'textContent: "one prompt - to a ready H3 job"'),
     "tests/test_main_panel.py::test_no_dash_is_used_as_punctuation_in_anything_a_person_reads"),

    ("the report loses the fact that tells an unconnected tray from an empty one",
     patch("web/prompt.js", "  const connected = Boolean(trayState(node));",
           "  const connected = true;"),
     "tests/test_main_panel.py::test_the_report_can_tell_an_unconnected_tray_from_an_empty_one"),

    ("prompt.js stops exporting the parse the Main panel imports",
     patch("web/prompt.js", "export function promptFacts(node, text) {",
           "function promptFacts(node, text) {"),
     "tests/test_main_panel.py::test_prompt_js_exports_everything_the_panel_imports"),
]


def _wipe_bytecode() -> None:
    """Every `__pycache__` in the checkout, gone. See the module docstring for why this is not
    hygiene.

    Collected before anything is deleted. `rglob` walks the tree lazily, and deleting directories
    out from under a live walk gives undefined coverage of the rest of it.
    """
    caches = [c for c in REPO.rglob("__pycache__") if ".venv" not in c.parts]
    for cache in caches:
        shutil.rmtree(cache, ignore_errors=True)


def _pytest(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([PY, "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider",
                           *args], cwd=REPO, capture_output=True, text=True)


def preflight() -> list[str]:
    """Before a single defect is planted: does every test named here exist, and does it pass?

    Both halves matter. A node id that no longer resolves makes pytest exit 4, which an earlier
    draft of this file counted as RED -- so a renamed test read as a guard firing. And a test that
    is already failing makes the RED after it meaningless.
    """
    ids = sorted({i for _n, _d, tests in CASES for i in tests.split()})
    print(f"pre-flight: {len(ids)} distinct tests named by {len(CASES)} cases")
    print(f"pre-flight: the compiler under test is {COMPILER}")
    problems, real = [], list(ids)
    if _pytest("--collect-only", *ids).returncode != 0:
        real = []
        for one in ids:
            if _pytest("--collect-only", one).returncode == 0:
                real.append(one)
            else:
                problems.append(f"{one} does not exist; the case naming it can never mean anything")
    # Only over the ids that resolve. Running the whole batch when one id is bad makes pytest exit
    # on the usage error and report nothing about the rest, which would print as a second, separate
    # problem that is really the first one wearing a different coat.
    if real:
        clean = _pytest(*real)
        if clean.returncode != 0:
            problems.append("these tests do not all pass on the clean tree, so any RED below "
                            f"proves nothing: {clean.stdout.strip().splitlines()[-1]}")
    print("pre-flight: " + ("OK, every named test exists and passes on the clean tree"
                            if not problems else f"{len(problems)} problem(s)"))
    for p in problems:
        print("   ", p)
    return problems


def _every_case_is_backed_up(backup: dict[pathlib.Path, str]) -> list[str]:
    """Refuse to plant anything in a file this run cannot put back.

    MEASURED, and it is the worst way this file can fail. A case was added that edits `web_api.py`
    and `TOUCHES` was not updated, so the defect was planted, the guard was asked about it, and the
    file was never restored: the repository was left carrying a deliberate fault, and the only reason
    it was noticed is that a later test failed on it.

    Nothing about planting requires a file to be in `TOUCHES` -- only restoring does -- so the two
    lists have to be held together here rather than by whoever adds the next case.
    """
    missing = sorted({str(d.path) for _n, d, _t in CASES if d.path not in backup})
    return [f"{p} is edited by a case and is not backed up. Add it to TOUCHES." for p in missing]


def main() -> int:
    # Keyed on the real path rather than on a repo-relative name, because one case edits the
    # installed compiler and that file is not under this repository at all.
    files = [REPO / f for f in TOUCHES] + [d.path for _n, d, _t in CASES if isinstance(d, Installed)]
    backup = {f: f.read_text(encoding="utf-8") for f in dict.fromkeys(files)}
    unsafe = _every_case_is_backed_up(backup)
    if unsafe:
        print("nothing was planted, because this run could not have put the tree back:")
        for problem in unsafe:
            print("   ", problem)
        return 2
    _wipe_bytecode()
    if preflight():
        print("\nnothing was planted. Fix the cases above first.")
        return 2
    print()

    red, green, broken = [], [], []
    for name, defect, tests in CASES:
        note = ""
        try:
            defect.plant()
            _wipe_bytecode()
            note = defect.prove_live()
            out = _pytest(*tests.split())
            if out.returncode == TESTS_FAILED:
                red.append(name)
                print(f"RED     {name}")
            elif out.returncode == TESTS_PASSED:
                green.append((name, note, out.stdout.strip().splitlines()[-1]))
                print(f"GREEN   {name}")
                print(f"        the defect WAS live ({note}) and the guard passed anyway")
                print(f"        {out.stdout.strip().splitlines()[-1]}")
            else:
                why = CANNOT_ASK.get(out.returncode, f"pytest exited {out.returncode}")
                broken.append((name, why))
                print(f"BROKEN  {name}")
                print(f"        {why}; this case asked nothing")
        except CaseBroken as e:
            broken.append((name, str(e)))
            print(f"BROKEN  {name}")
            print(f"        {e}")
        finally:
            for f, text in backup.items():
                f.write_text(text, encoding="utf-8")
            wrong = [str(f) for f, text in backup.items()
                     if f.read_text(encoding="utf-8") != text]
            if wrong:
                print(f"        the tree was NOT restored: {wrong}. Stopping.")
                return 3
    _wipe_bytecode()

    print()
    print(f"{len(red)} red, {len(green)} green, {len(broken)} broken, of {len(CASES)} cases")
    for name, note, tail in green:
        print(f"  GUARD DID NOT FIRE  {name}  ({note}; {tail})")
    for name, why in broken:
        print(f"  CASE DID NOT RUN    {name}  ({why})")
    if green or broken:
        return 1
    print(f"all {len(CASES)} guards fired")
    return 0


if __name__ == "__main__":
    sys.exit(main())
