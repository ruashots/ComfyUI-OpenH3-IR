"""Running the compiler in the Python that ComfyUI is running, and asking a language model what it
is.

This is the all-in-one half of the pack. A user installs the node pack, types the address of their
own language model on the Setup node, and renders: there is no second process, no port to pick and
nothing to start. The compiler is the `open-h3-ir` package that `requirements.txt` names, and it
runs here, in ComfyUI's own interpreter.

**This module is the only place in the pack that names `h3ir`, and every one of those imports is
inside a function.** That is not a style rule, and it survives the pack becoming an all-in-one for
three reasons that have nothing to do with tidiness:

  * ComfyUI takes a pack whose import raises off the menu entirely, with a traceback in a console
    nobody is reading. The compiler is a separate installation and can be absent, half-installed or
    shadowed, and none of those may cost somebody every node in this pack.
  * A pack driving a compiler on another machine needs no local package at all, and must not be made
    to install one.
  * The compiler declares fastapi, uvicorn, pydantic and tiktoken, so pip puts all four into
    ComfyUI's Python. Measured on this checkout: `import h3ir.compile` takes 0.06 seconds and loads
    none of the four. The in-process path never imports `h3ir.service`, which is the one module that
    needs fastapi, and that is what keeps those packages installed but never loaded.

**The brief is built here rather than borrowed from the service.** `h3ir.service._to_brief` is the
compiler's only conversion from a request into a `Brief`, and it lives in the one module that pulls
in fastapi. Most of what it does is about uploads, and an in-process caller has none: the files are
on the same disk, because this pack put them there. What is left is small enough to state, and
stating it gets the field names checked by Python at call time. `brief_from_payload` below is that
statement, and `tests/test_in_process.py` holds it against `_to_brief` by running the same request
through both and comparing the two briefs field by field.

**Both compile paths build the request with the same function.** `h3ir_client.build_payload` decides
what a graph is asking for, and it is the only thing that decides it. The HTTP path posts that
dictionary; this path converts it. So a rule about what a request says -- an empty intent, a shot
count of `auto`, a director with nothing written in it -- is written once and both paths obey it.

**An unknown key is refused here, never dropped.** The wire models set `extra="forbid"` because
pydantic's silent drop cost this project a real bug: a picture arrived saying nothing about who it
replaces, and the render was plausible and wrong. A conversion that reads the keys it knows and
ignores the rest would put that bug back on the path that has no wire to catch it.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

from .h3ir_client import (REFUSED_AS_ASKED, ServiceError, analysis_tool_missing, asset_unreadable,
                          contradictions, needs_input_first, over_capacity, refused_as_asked)

# The compiler's own settings, and the two a person can reach from the Setup node. Named so a message
# can tell somebody that a value came from their environment rather than from the canvas, which is
# the difference between a setting they can see and one they cannot.
LLM_URL_ENV = "H3IR_LLM_URL"
LLM_MODEL_ENV = "H3IR_LLM_MODEL"

# What pip installs, spelled the way somebody types it. The import package is `h3ir` and the
# distribution is `open-h3-ir`, and a message that gets that backwards sends a person to install
# something that does not exist.
DISTRIBUTION = "open-h3-ir"

# Where a saved credential lives: one file in ComfyUI's own per-user folder, beside the Director's
# saved directions, holding an address and the key that address wants.
#
# **It is deliberately NOT a widget value, and that is the whole reason this file exists.** Every
# widget value is written into the saved workflow and into the graph embedded in every rendered
# video, which the Director node's own documentation calls a feature: drag the video back in and the
# direction comes with it. For a paid API key that same mechanism is a leak, and people share
# workflows by dropping a picture into a chat.
#
# The panel writes it through ComfyUI's own `/userdata` routes. Python reads it back from disk, so
# the test and the real compile take the same path to the same credential -- a check that reads a
# key some other way can pass while the queue fails.
KEY_STORE = "openh3ir/llm/keys.json"


def _user_file(name: str) -> str:
    """A file in ComfyUI's per-user folder, spelled the way ComfyUI's own `/userdata` routes spell it.

    `default` is the user id ComfyUI uses unless it was started with `--multi-user`, which is a
    login-gated mode. On a multi-user install the panel writes under the signed-in user's folder and
    this reads `default`, so a stored key is not found and the request goes out with no credential.
    That surfaces as the endpoint's own 401 with a message, which is a loud failure rather than a
    render nobody can explain.
    """
    import folder_paths
    return os.path.join(folder_paths.get_user_directory(), "default", *name.split("/"))


def endpoint_key(url: str) -> str:
    """The credential somebody saved on this ComfyUI for this endpoint, or "" when there is none.

    Keyed on the address exactly as the node holds it, trimmed and with no trailing slash, because
    that is the string the panel saved it under and the string the node sends.

    Every way of not having one answers "": no ComfyUI, no file, unreadable JSON, no entry. A
    credential store that raised would take a queue down over a file nobody has.
    """
    address = (url or "").strip().rstrip("/")
    if not address:
        return ""
    try:
        with open(_user_file(KEY_STORE), encoding="utf-8") as fh:
            saved = json.load(fh)
    except Exception:                     # noqa: BLE001 - absent, unreadable and empty are all none
        return ""
    if not isinstance(saved, dict):
        return ""
    return str(saved.get(address) or "").strip()


def environment_defaults() -> dict[str, str]:
    """What ComfyUI's own environment would give if the node's two fields are left empty.

    Published so the panel can say so BEFORE a queue. An empty field that is not really empty is the
    most confusing state this node has: the compiler uses the environment, the report says so after
    a run, and until then the canvas shows a blank box that looks like nothing is set.

    Never a refusal and never a default. It reports what is in the environment and nothing else.
    """
    return {"url": os.environ.get(LLM_URL_ENV, "").strip(),
            "model": os.environ.get(LLM_MODEL_ENV, "").strip()}


# --------------------------------------------------------------------------- is it here at all

def availability() -> tuple[str, str]:
    """Whether the compiler can run in this Python: `("ok", "")`, `("absent", ...)`, `("broken", ...)`.

    Three answers rather than two, because the three have three different fixes and a person has to
    be able to read which one they are in. Absent means nothing installed the package. Broken means
    the package is there and something it needs is not, or it raises on import, which is what a
    half-finished pip run leaves behind. Neither is ever reported as the other.

    `h3ir.compile` rather than `h3ir` itself, because an empty `h3ir/__init__.py` imports on a
    package whose modules are missing, and answering "ok" for that would move the failure to the
    queue and describe it as something else.
    """
    try:
        import h3ir.compile  # noqa: F401 - imported to find out whether it can be
    except ModuleNotFoundError as e:
        if (e.name or "").split(".")[0] == "h3ir":
            return "absent", str(e)
        return "broken", (f"{DISTRIBUTION} is installed and something it needs is not: {e}")
    except Exception as e:                              # noqa: BLE001 - any import failure is one
        return "broken", f"{type(e).__name__}: {e}"
    return "ok", ""


def package_version() -> str:
    """What the installed compiler calls itself, or "" when there is none.

    Informational, and never compared: `contract_version` is the field that answers whether two
    halves agree. This is for a message that has to name a version so two people can say which one
    each of them has.
    """
    try:
        from importlib.metadata import version
        return str(version(DISTRIBUTION))
    except Exception:                                   # noqa: BLE001 - absent is an ordinary answer
        return ""


def installed_contract() -> dict[str, Any] | None:
    """The contract of the `open-h3-ir` installed in THIS Python, or None when there is none.

    One of the two ways to ask. `h3ir_client.fetch_contract` asks a service over HTTP; this asks the
    package that is about to do the work in the same process, which is the ordinary case now that
    the pack ships as an all-in-one.

    **Whichever compiler is going to write the brief is the one that must be asked.** That is the
    invariant, and it is easy to break in a way that produces confident nonsense: reading the local
    package's contract while compiling against a remote service would compare this machine's version
    to another machine's work and refuse graphs that are perfectly fine. `contract.the_compiler`
    picks one source to match the compile path and never merges them.

    None is an ordinary answer for absent, broken and half-installed alike, because a client never
    fails on the CHECK. The request after it has its own messages for every way it can go wrong.
    """
    try:
        from h3ir.contract import contract
    except Exception:      # noqa: BLE001 - absent, broken, or half-installed are all "no contract"
        return None
    try:
        got = contract()
    except Exception:      # noqa: BLE001 - same answer; a client never fails on the CHECK
        return None
    return got if isinstance(got, dict) and "contract_version" in got else None


def require_installed() -> None:
    """Refuse the queue when there is no compiler in this Python, naming the fix for the case at hand.

    Reached only on the in-process path, and only once the Setup node has said that is the path: a
    graph driving a service on another machine needs nothing installed here and must never be told
    to install it.
    """
    state, detail = availability()
    if state == "ok":
        return
    if state == "absent":
        raise ServiceError(
            f"this graph compiles in ComfyUI itself, and {DISTRIBUTION} is not installed in the "
            "Python ComfyUI is running. That package is the compiler: it turns the sentence on the "
            "node into the brief H3 renders from.\n\n"
            f"Install it where ComfyUI runs, with that Python: python -m pip install "
            f"'{DISTRIBUTION}'. ComfyUI Manager does this for you when it installs this pack, so "
            "reaching this usually means the pack was copied in by hand.\n\n"
            "The other way out is to run the compiler somewhere else: start it with h3ir serve and "
            "put its address in the service field on the Setup node.")
    raise ServiceError(
        f"{DISTRIBUTION} is installed in the Python ComfyUI is running and it will not import, so "
        f"nothing can compile here: {detail}\n\n"
        "That is a half-finished or damaged install rather than anything in your graph. Install it "
        f"again where ComfyUI runs, with that Python: python -m pip install --force-reinstall "
        f"'{DISTRIBUTION}'.")


# --------------------------------------------------------------------------- the language model

def resolve_llm_url(typed: str) -> tuple[str, str]:
    """The address to use and where it came from, or a refusal naming the field on the node.

    Two sources and they are not equal. The Setup node's field is the one a person can see, so it
    wins. The environment is the compiler's own documented channel and a ComfyUI started from a
    shell that sets it is a real setup, so it is honoured -- and the report says so, because a
    setting nobody can see on the canvas has to be said out loud somewhere.

    There is deliberately no default. The compiler's own is `http://127.0.0.1:8000/v1`, which is a
    placeholder meaning "a server on this machine", and taking it here would send somebody's queue
    at a port with nothing behind it and then explain the failure in terms of an environment
    variable they have no service to set it on.
    """
    typed = (typed or "").strip()
    if typed:
        return typed, "the Setup node"
    from_env = os.environ.get(LLM_URL_ENV, "").strip()
    if from_env:
        return from_env, f"{LLM_URL_ENV} in ComfyUI's environment"
    raise ServiceError(
        "this graph compiles in ComfyUI itself, and there is no language model for it to write "
        "with. The compiler turns your sentence into a brief by asking a language model, and it "
        "needs the address of one that can also read pictures.\n\n"
        "Put that address in the language model field on the OpenH3-IR Setup node, in full and "
        "ending in /v1, for example http://192.168.1.20:8000/v1. Anything that speaks the OpenAI "
        "API works: vLLM, llama.cpp's server, LM Studio, Ollama, or a hosted one.")


def resolve_llm_model(url: str, typed: str, *, timeout: float = 20.0) -> tuple[str, str]:
    """Which model on that endpoint writes the brief, and where that answer came from.

    Asked HERE rather than left to the compiler, and the reason is the message. The compiler refuses
    to guess between several models and says so by naming an environment variable, which is the right
    sentence for a service and the wrong one for somebody looking at a node: there is no service to
    set it on. So the question is settled on this side, where the answer is a field on the canvas,
    and the compiler is handed an id it never has to discover.

    **Several ids are not necessarily several models.** One set of weights published under several
    names is one choice with nothing in it, and `endpoint_report` collapses those. What is left is a
    real choice, and this will not make it: the model that has to be picked is the one that can read
    a picture, and no model list on any of these servers says which one that is.
    """
    typed = (typed or "").strip()
    if typed:
        return typed, "the Setup node"
    from_env = os.environ.get(LLM_MODEL_ENV, "").strip()
    if from_env:
        return from_env, f"{LLM_MODEL_ENV} in ComfyUI's environment"
    got = endpoint_report(url, timeout=timeout)
    if not got.get("ok"):
        raise ServiceError(
            f"the model field on the OpenH3-IR Setup node is empty, so this asked {url} which "
            f"models it serves, and it did not answer: {got.get('reason', 'no reason given')}\n\n"
            "Fix the language model address on that node, or name the model in the field beside it "
            "so nothing has to be asked.")
    choices = got.get("choose_from") or []
    if len(choices) == 1:
        return choices[0], f"the only model {url} serves"
    raise ServiceError(
        f"{url} serves {len(choices)} models, so which one writes this brief is a real choice and "
        "this will not guess it. The brief is written by reading your reference pictures through "
        "that model, and no list of models says which of them can see.\n\n"
        "Put one of these in the model field on the OpenH3-IR Setup node: "
        + ", ".join(choices))


def _status_in(answered: str) -> int | None:
    """The HTTP status inside the compiler's own account of one liveness attempt, or None.

    Parsed HERE rather than in the panel, in one place with a test on it, because the difference it
    settles is one a person acts on. Nothing answering at all and a server answering 401 are two
    different problems with two different fixes, and the compiler's probe records both as text:
    `HTTP 401` for one, `ConnectError: ...` for the other. A panel left to tell those apart by
    reading prose would be a second, quieter copy of this parse.

    None is the honest answer for a socket that never opened. It is not an error and it is not a 0:
    there was no HTTP exchange to have a status.
    """
    found = re.match(r"^HTTP (\d{3})$", str(answered or "").strip())
    return int(found.group(1)) if found else None


def one_name_per_checkpoint(entries: list[dict[str, Any]]
                            ) -> tuple[list[str], dict[str, list[str]]]:
    """One name per set of weights, and the names it stands in for.

    A model list can name one checkpoint several times. vLLM's `--served-model-name` publishes the
    same weights under every name it is given and stamps every one of those entries with the same
    `root`, so offering all of them is a panel inventing a decision: whichever a person picks, the
    same file answers. Grouping by `root` is what collapses that. An entry with no `root`, which is
    every entry on Ollama, is its own group, and that is the safe direction -- it can only offer more
    choice, never merge two models that are really two.

    **Which name survives is the rule this function exists to state.** The survivor is what a person
    clicks in a list, types into a field, and recognises months later looking at their own server, so
    it is chosen rather than fallen into:

        1. Within a group, the survivor is the first id the server lists whose `id` is NOT its own
           `root`. That id is a name somebody typed into `--served-model-name`: the operator decided
           this is what the model is called here. `root` is where the weights came from, which is
           provenance rather than a name anybody chose.
        2. If no id in the group differs from its root, the survivor is the first id the server
           lists. Nobody named it, so there is nothing to prefer and the server's own order stands.

    MEASURED on a live vLLM: ids `philbert440/Qwen3.8-27B-Uncensored-Aggressive-W4A16-AWQ` and
    `qwen3.8u`, one `root`, and the second is the one the operator wrote. Rule 1 keeps it. Rule 2 is
    what an unaliased server gets, and there the two rules agree.

    **The survivor is always an `id` and never a `root`.** That is a correctness line rather than a
    taste one: whatever a person picks is sent straight back to the server as `model`, and a `root`
    is not promised to be a name the server answers to -- vLLM sets it from the model path, so on a
    server started from a local directory it is a filesystem path with no route behind it. Only the
    strings in `data[].id` are names the server has published as its own.
    """
    groups: dict[str, list[dict[str, Any]]] = {}
    for m in entries:
        groups.setdefault(str(m.get("root") or m["id"]), []).append(m)

    survivors: list[str] = []
    collapsed: dict[str, list[str]] = {}
    for members in groups.values():
        chosen = next((str(m["id"]) for m in members
                       if str(m["id"]) != str(m.get("root") or m["id"])), "")
        keep = chosen or str(members[0]["id"])
        survivors.append(keep)
        others = [str(m["id"]) for m in members if str(m["id"]) != keep]
        if others:
            collapsed[keep] = others
    return list(dict.fromkeys(survivors)), collapsed


def endpoint_report(url: str, *, timeout: float = 20.0) -> dict[str, Any]:
    """What is answering at an address and which models it serves, for the panel's test control.

    Read off the compiler's own client rather than by fetching `/v1/models` here, so the panel tests
    the very code the queue will use: the same liveness paths in the same order, the same credential
    decision, the same collapsing of several ids onto one set of weights.

    `choose_from` is the honest answer to "which model", and it is often shorter than `ids`: two ids
    can be one checkpoint, and picking between them is a choice with nothing in it. `also_known_as`
    maps each survivor to the names it stands in for, so a panel can say so beside the row rather
    than leaving somebody to wonder where the name they typed last week went.
    `one_name_per_checkpoint` above states which name survives and why.

    **Nothing here says which model can see**, because no model list on any of these servers carries
    that. `can_it_see` is the only way to find out and it costs a request to the model itself.

    **`_get` and `_headers` are the compiler's private methods and this is the one place that reaches
    for them.** The alternative was fetching `/v1/models` here with `httpx`, which would restate two
    things the compiler measured and owns: which liveness paths to try and in what order, and whether
    a configured credential goes out. A second opinion about either is a panel that says an endpoint
    is down when the queue would have reached it.
    `tests/test_in_process.py::test_the_private_methods_this_reaches_for_are_still_on_the_backend`
    holds the coupling against the installed compiler, so a release that renames one fails a test
    here rather than a button in somebody's browser.
    """
    state, detail = availability()
    if state != "ok":
        return {"ok": False, "reason": detail, "installed": False}
    from h3ir.backend import Backend

    cfg = _config(url, "", timeout=timeout)
    with Backend(cfg) as b:
        probe = b.health_probe()
        out: dict[str, Any] = {
            "installed": True,
            "url": b.base_url(),
            "ok": probe.ok,
            "via": probe.via,
            "tried": [{"url": u, "answered": w, "status": _status_in(w)}
                      for u, w in probe.attempts],
            "credential": bool(b._headers()),
            "ids": [],
            "choose_from": [],
        }
        if not probe.ok:
            out["reason"] = (
                f"nothing answered at {b.base_url()}. Check the address, and check that the server "
                "is running and reachable from the machine ComfyUI is on.")
            return out
        try:
            entries = [m for m in (b._get(f"{b.base_url()}/models", 10.0).json().get("data") or [])
                       if m.get("id")]
        except Exception as e:                          # noqa: BLE001 - reported, never raised
            out["ok"] = False
            out["reason"] = (f"{b.base_url()} answered, and its list of models could not be read: "
                             f"{e}")
            return out
        out["ids"] = [str(m["id"]) for m in entries]
        out["choose_from"], out["also_known_as"] = one_name_per_checkpoint(entries)
        out["context"] = next((m.get("max_model_len") for m in entries if m.get("max_model_len")),
                              None)
        out["server_version"] = b.server_version()
        if not out["ids"]:
            out["ok"] = False
            out["reason"] = (f"{b.base_url()} is answering and lists no models at all, so there is "
                             "nothing to write with. Load a model on that server.")
    return out


def can_it_see(url: str, model: str, *, timeout: float = 120.0) -> dict[str, Any]:
    """Ask one model to read three digits off a generated picture, and report what it said.

    The one capability the compiler cannot do without, and the one thing no model list anywhere
    reports. Every reference picture in a graph is read through this model, so a text-only one
    answers every other check perfectly and then sees none of the media: the brief comes back
    describing pictures nobody looked at.

    The compiler's own `vision_check` draws the picture, writes it to a file and passes it through
    the same message builder a real analysis uses, so this exercises the production wiring rather
    than a shortcut written for a panel.
    """
    state, detail = availability()
    if state != "ok":
        return {"ok": False, "reason": detail, "installed": False}
    from h3ir.backend import Backend, BackendError, EndpointRefused, vision_check

    if not model.strip():
        return {"installed": True, "ok": False, "reason": (
            "no model was named, and this has to ask one particular model whether it can see. "
            "Pick a model first.")}
    cfg = _config(url, model, timeout=timeout)
    with Backend(cfg) as b:
        try:
            ok, said = vision_check(b)
        except EndpointRefused as e:
            return {"installed": True, "said": str(e)[:300], **_what_the_refusal_means(e, model)}
        except BackendError as e:
            # A timeout or a truncation says nothing either way, so no verdict is recorded. Reporting
            # one would be this pack guessing about the thing it was asked to measure.
            return {"installed": True, "ok": None, "reason": (
                f"the check could not be completed, so nothing is known about whether {model} can "
                f"see: {e}")}
    out = {"installed": True, "ok": ok, "said": said, "model": model}
    if not ok:
        out["reason"] = (
            f"{model} did not read the test picture. Reference pictures in the tray are read "
            "through this model, so a graph with a picture attached cannot work with it. A brief "
            "with nothing in the tray still can. Pick a model with a vision tower.")
    return out


def _what_the_refusal_means(refused, model: str) -> dict[str, Any]:
    """A refused request is not automatically an answer about vision, and reading it as one is the
    wrong-message failure this pack exists to prevent.

    MEASURED against a live vLLM: asking about a model that is not loaded came back as
    `HTTP 404: The model does not exist`, and the first draft of this reported it as "it cannot read
    a picture, pick one with a vision tower". Somebody reading that would go looking for a vision
    model to replace one that was never there.

    So the status decides. A request the server looked at and rejected as unacceptable is a
    judgement about the model, and it is the one thing a text-only model does with a picture. A
    missing model, a rejected credential and a server that broke are three different problems, and
    none of them says anything at all about vision -- so none of them gets a verdict.
    """
    status = getattr(refused, "status", 0)
    if status in (400, 415, 422):
        return {"ok": False, "reason": (
            f"{model} rejected a request with a picture in it, so it cannot read one. Reference "
            "pictures in the tray are read through this model. Pick one with a vision tower.")}
    if status == 404:
        return {"ok": None, "reason": (
            f"that endpoint has no model called {model}, so nothing was asked and nothing is known "
            "about whether it can see. Check the model field on the OpenH3-IR Setup node against "
            "the list the endpoint serves.")}
    if status in (401, 403):
        return {"ok": None, "reason": (
            f"that endpoint refused the request as unauthorised, so {model} was never asked. It "
            "wants a credential. Set H3IR_LLM_KEY in ComfyUI's environment and restart ComfyUI.")}
    return {"ok": None, "reason": (
        f"that endpoint answered with an error rather than a verdict, so nothing is known about "
        f"whether {model} can see: {refused}")}


def _config(url: str, model: str, *, timeout: float):
    """The compiler's configuration with the two things the node owns put into it, and nothing else.

    Built and handed to a `Backend` rather than written into the compiler's global configuration.
    That global is read for the cache directory, the tokenizer and the prompt templates, which are
    facts about the installation and not about this graph, and replacing it would make one node's
    widgets decide what another queue does.

    The credential is the third thing the node can own, and it comes from ComfyUI's own per-user
    folder rather than from a widget. A stored key wins; with none, `H3IR_LLM_KEY` in the
    environment still decides, exactly as it did before this store existed.

    Every other language model setting -- the token budget, whether reasoning is on -- keeps coming
    from the environment, which is where the compiler documents them.
    """
    from h3ir.config import Config, LLMConfig

    address = url.strip().rstrip("/")
    fields: dict[str, Any] = {"base_url": address, "model": model.strip(),
                              "timeout_s": float(timeout)}
    saved = endpoint_key(address)
    if saved:
        fields["api_key"] = saved
    return Config(llm=LLMConfig(**fields))


# --------------------------------------------------------------------------- the request

# Every top-level key of a request this pack can write. `h3ir_client.build_payload` is what writes
# them, `seed` and `transcripts` are arguments to the compile rather than fields of a `Brief`, and
# the rest map onto `Brief` below. Anything else arriving here is refused rather than dropped: a key
# the conversion does not know is a request asking for something it will not get, which is the
# failure `extra="forbid"` exists to stop on the wire and would otherwise walk straight back in on
# the path that has no wire.
_BRIEF_KEYS = frozenset({
    "intent", "assets", "seconds", "aspect", "megapixels", "dialogue", "onscreen_text", "shots",
    "loras", "silent", "constraints", "creativity", "director", "director_profile", "effort",
    "seed", "transcripts",
})

# The same, for one attachment. `path` and the two `paired_video_` spellings are how the bytes are
# named; everything else is what the file IS. `url` and `sha256` are in the wire's list and not in
# this one on purpose: an in-process compile has neither, because the files are already on this disk.
_ASSET_KEYS = frozenset({
    "path", "note", "replaces", "kind", "role", "sizing", "seconds", "frames", "paired_video_path",
    "provenance",
})

# What the wire model allows for a stated canvas size. Mirrored here so the two paths refuse the same
# request, and pinned to `service.BriefIn` by
# `tests/test_in_process.py::test_the_size_bounds_are_the_wire_models_own`, so a change over there
# fails a test over here rather than becoming a graph one path takes and the other does not.
MEGAPIXELS_MIN, MEGAPIXELS_MAX = 0.25, 2.5


def brief_from_payload(payload: dict[str, Any], sha_of) -> Any:
    """The request this graph is making, as the compiler's own `Brief`.

    The same dictionary the HTTP path posts, converted instead of sent. Everything it is allowed to
    say is said by `build_payload`, so this decides nothing about the request: it maps names onto
    fields and refuses anything it does not recognise.

    `sha_of` names a file by its own bytes. The service hashes the same bytes on the other side of
    the wire, so the two paths produce the same digest for the same file -- which is what lets the
    report put the tray's slot labels back onto the compiler's manifest either way. It is the node's
    memoised one, so a clip is read once per queue rather than once per use.

    Two things the wire does that this must do identically, because getting either wrong is silent.
    `role_stated` says whether the CALLER named the role, and mode inference reads it: this pack
    states every role from the tray, so it is always true here, and the contract check has already
    refused any role the compiler has no name for. And a soundtrack's pointer at its own clip becomes
    that clip's digest, because the digest is the identity the runtime pairs on -- left as a path it
    would name nothing, the pair would quietly stop being a pair, and one file would carry two
    different labels.
    """
    from h3ir.models import AssetKind, AssetRef, Brief, DialogueLine, Role

    unknown = sorted(set(payload) - _BRIEF_KEYS)
    if unknown:
        raise ServiceError(
            f"internal: this node wrote a request with {', '.join(unknown)} in it, and the "
            "conversion that hands it to the compiler has no field of that name. That request is "
            "written here rather than by you, so it is a defect in OpenH3-IR rather than something "
            "in your graph.")

    roles = {r.value: r for r in Role}
    assets = []
    for a in payload.get("assets") or []:
        extra = sorted(set(a) - _ASSET_KEYS)
        if extra:
            raise ServiceError(
                f"internal: an attachment in this request carries {', '.join(extra)}, which the "
                "conversion that hands it to the compiler has no field for. That is a defect in "
                "OpenH3-IR rather than something in your graph.")
        role = roles.get(str(a.get("role") or ""))
        if role is None:
            # Unreachable from the canvas: every tray slot states a role from the tray's own list and
            # `contract.differences` has already stopped a graph naming one this compiler does not
            # have. Said anyway, because the alternative is falling through to the kind's default and
            # compiling something nobody asked for.
            raise ServiceError(
                f"the compiler in this ComfyUI has no job called {a.get('role')!r}. This node pack "
                "is newer than the open-h3-ir installed beside it. Update it where ComfyUI runs: "
                f"python -m pip install --upgrade '{DISTRIBUTION}'.")
        path = str(a.get("path") or "")
        if not path:
            raise ServiceError(
                "internal: an attachment in this request names no file, so nothing can be compiled "
                "from it. That is a defect in OpenH3-IR rather than something in your graph.")
        paired = a.get("paired_video_path")
        assets.append(AssetRef(
            kind=AssetKind(str(a.get("kind") or "image")), role=role, sha256=sha_of(path),
            path=path, note=a.get("note"), sizing=str(a.get("sizing") or "match"),
            seconds=a.get("seconds"), frames=a.get("frames"), provenance=a.get("provenance"),
            paired_video_sha256=(sha_of(paired) if paired else None),
            replaces=str(a.get("replaces") or "").strip(), role_stated=True))

    mp = payload.get("megapixels")
    if mp is not None and not (MEGAPIXELS_MIN <= float(mp) <= MEGAPIXELS_MAX):
        raise ServiceError(
            f"size, in megapixels is {float(mp):g}, and the compiler renders between "
            f"{MEGAPIXELS_MIN:g} and {MEGAPIXELS_MAX:g}. Set 0 for H3's native size.")

    return Brief(
        intent=str(payload["intent"]), assets=assets,
        seconds=float(payload.get("seconds", 5.0)), aspect=str(payload.get("aspect", "16:9")),
        megapixels=(float(mp) if mp is not None else None),
        dialogue=[DialogueLine(text=str(d["text"]), language=str(d.get("language", "English")),
                               speaker_hint=d.get("speaker"), voiceover=bool(d.get("voiceover")))
                  for d in (payload.get("dialogue") or [])],
        onscreen_text=[str(t) for t in (payload.get("onscreen_text") or [])],
        shots=payload.get("shots"), loras=list(payload.get("loras") or []),
        silent=bool(payload.get("silent", False)),
        constraints=[str(c) for c in (payload.get("constraints") or [])],
        effort=str(payload.get("effort", "standard")),
        creativity=str(payload.get("creativity", "balanced")),
        director=str(payload.get("director") or ""),
        director_profile=payload.get("director_profile"))


# --------------------------------------------------------------------------- the compile

def compile_here(payload: dict[str, Any], *, sha_of, llm_url: str, llm_model: str,
                 timeout: float) -> dict[str, Any]:
    """Compile in this Python, and answer exactly what `h3ir_client.compile_brief` answers.

    Same keys, same meanings, so `render_fields`, `report` and `director_note` cannot tell the two
    apart and neither path is the one that gets less. The HTTP path assembles this dictionary from
    two replies -- the brief envelope and its render fields -- and this assembles it from the
    document those replies are built out of.

    Every way the compiler can refuse is turned into the sentence the node pack already writes for
    that refusal over HTTP, so a contradictory graph reads the same either way. What differs is only
    what a person can act on: an unreachable language model here is theirs, on the Setup node, and
    over there it belongs to whoever runs the service.
    """
    require_installed()
    from h3ir.analyse import AssetAnalysisError, ToolMissing
    from h3ir.backend import Backend, BackendError, BackendUnavailable
    from h3ir.compile import BriefRefused, compile_brief
    from h3ir.plan import ProfileOptions

    brief = brief_from_payload(payload, sha_of)
    cfg = _config(llm_url, llm_model, timeout=timeout)
    try:
        with Backend(cfg) as backend:
            doc = compile_brief(
                brief, backend=backend, opts=ProfileOptions(name=cfg.profile),
                seed=payload.get("seed"),
                thinking_prose=(payload.get("effort") == "max"),
                # Read off the configuration this compile is using rather than off the compiler's
                # global one. They agree today, because both read the same environment variable, and
                # a caller that hands the backend its settings and then lets one of them come from
                # somewhere else is one release away from disagreeing with itself.
                thinking_planning=cfg.llm.default_thinking,
                transcripts=dict(payload.get("transcripts") or {}))
    except BriefRefused as e:
        # The compiler read the request, understood it, and will not write it as stated. The same two
        # branches the HTTP path has, and the same sentences: which side of a socket the refusal
        # crossed is not something the person reading it has to care about.
        raise ServiceError(over_capacity(str(e)) if e.code == "over-capacity"
                           else refused_as_asked(str(e)) if e.code in REFUSED_AS_ASKED
                           else f"the compiler refused this brief ({e.code}): {e}") from e
    except BackendUnavailable as e:
        raise ServiceError(_endpoint_did_not_answer(e, llm_url, llm_model)) from e
    except BackendError as e:
        raise ServiceError(
            f"the language model answered with an error rather than a brief: {e}\n\n"
            "Nothing is wrong with this graph. That is the server in the language model field on "
            "the OpenH3-IR Setup node.") from e
    except ToolMissing as e:
        raise ServiceError(analysis_tool_missing(str(e), where="on the machine ComfyUI runs on"))\
            from e
    except AssetAnalysisError as e:
        raise ServiceError(asset_unreadable(str(e))) from e

    return _as_the_service_answers(doc, brief)


def _endpoint_did_not_answer(unavailable, url: str, model: str) -> str:
    """The language model could not be reached, said to somebody looking at a node.

    MEASURED live, and the first draft of this got it wrong in the way this pack exists to prevent.
    The compiler's own sentence for an unreachable endpoint ends "Start it, or set H3IR_LLM_URL",
    which is correct advice for a service and wrong here: there is no service, and the address is a
    field on the canvas. Passing that sentence through and then adding "that is the field on the
    Setup node" hands the reader two contradictory instructions and lets them pick.

    So the endpoint is asked again -- it has already failed, so nobody is waiting on this -- and the
    evidence comes back as data rather than as somebody else's prose. What was tried, and what each
    attempt said, is the useful half; the advice is written here, where it can name the right thing.

    An endpoint that answers on the second look means the failure was about something other than
    reachability, and there the compiler's own sentence is the best description there is, so it is
    passed through whole.
    """
    got = endpoint_report(url, timeout=10.0)
    if got.get("ok"):
        return (f"the language model at {url} refused to write this brief: {unavailable}\n\n"
                "It is answering, so this is about that endpoint rather than about your graph or "
                "the network.")
    tried = "\n".join(f"  {a['url']} answered {a['answered']}" for a in got.get("tried") or ())
    return (f"the language model at {url} did not answer, so there is nothing to write this brief "
            "with."
            + (f" This graph asked for {model}." if model else "")
            + "\n\n"
            + (f"What was tried:\n{tried}\n\n" if tried else "")
            + "Bring that server up, or point the language model field on the OpenH3-IR Setup node "
              "at one that is running, and queue again. Nothing was rendered from a worse brief, "
              "which is what refusing buys.")


def _as_the_service_answers(doc, brief) -> dict[str, Any]:
    """The document as the two HTTP replies the node already knows how to read.

    Assembled from `h3ir.service`'s own two route handlers -- the brief envelope and the render
    fields -- without importing them, because that module is the one that needs fastapi. Kept
    honest by `tests/test_in_process.py`, which builds the same document both ways and compares the
    dictionaries.
    """
    asked = doc.provenance.get("clarification")
    if asked:
        # One decision the compiler will not make on somebody's behalf. Refused here rather than
        # returned, exactly as the HTTP path refuses a `needs_input` reply: there is no second turn
        # in a queue, and compiling on an assumption is how a picture becomes an opening frame
        # nobody asked for.
        raise ServiceError(needs_input_first(str(asked.get("question") or ""),
                                             str(asked.get("default_if_unanswered") or "")))
    if not doc.ok:
        # The compiler's own split between a contradiction the caller stated and an invariant of its
        # own. A caller can act on the first and should never see the second, so the second says
        # whose bug it is instead of listing rule ids at somebody.
        theirs = [f for f in doc.errors if f.rule.split("-")[0] in
                  ("T6", "T7", "M5", "M6", "M7", "L3", "X10", "X11", "X12", "X13", "X15")]
        if theirs:
            raise ServiceError(contradictions([{"rule": f.rule, "message": f.msg}
                                               for f in doc.errors]))
        raise ServiceError(
            "the compiler failed its own checks while writing this brief, which is a bug in "
            "open-h3-ir rather than in your request: "
            + "; ".join(f"{f.rule}: {f.msg}" for f in doc.errors))

    retention = {src: s.retention for s in doc.plan.subjects for src in s.sources}
    return {
        "prompt": doc.prompt,
        "mode": doc.mode.value,
        "wiring": [{"label": m.label, "wiring": m.wiring, "sha256": m.sha256,
                    "kind": m.kind.value, "sizing": m.sizing,
                    "retention": retention.get(m.label, "")}
                   for m in doc.plan.manifest],
        "frames": doc.plan.target.frames,
        "canvas": list(doc.plan.target.canvas),
        "render_hash": doc.render_hash(),
        # The service mints a random id per request and remembers the document under it. Nothing
        # in-process remembers anything, so the brief's own content hash is the id: it names this
        # exact request, two queues of an unchanged graph produce the same one, and it is the thing
        # somebody would quote when asking why a render came out the way it did.
        "brief_id": brief.hash()[:16],
        "degraded": bool(doc.fell_back),
        "fallback_reason": doc.fallback_reason or "",
        "director_used": doc.provenance.get("director") or "",
    }
