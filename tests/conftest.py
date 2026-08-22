"""Test-session configuration: make the repository root importable the way ComfyUI imports it.

**The repository root IS the pack.** ComfyUI Manager clones this repository straight into
`custom_nodes`, and ComfyUI then loads the cloned directory as a package: it builds a spec from the
directory's `__init__.py`, names the package after the folder, and executes it. Every module in here
imports its siblings relatively -- `from . import tray` -- which is correct under that loader and
impossible for a plain `import tray` from a directory on `sys.path`.

So the tests do what ComfyUI does. `spec_from_file_location` with `submodule_search_locations`
pointing at the root makes the root a package, and every test then says `from openh3ir import tray`.

**The name is the tests' choice, not ComfyUI's.** Under ComfyUI the package is called whatever the
cloned folder is called -- `ComfyUI-OpenH3-IR` for a Manager install, which is not something an
`import` statement can spell. The pack's own code never says its own name, so any name works and one
is pinned here to keep the imports readable. `openh3ir` is the name this pack already uses everywhere
a name is needed: the extension ids in `web/`, the upload route, and the director store under
`user/default/openh3ir/`.
"""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "openh3ir"

if PACKAGE not in sys.modules:
    spec = importlib.util.spec_from_file_location(
        PACKAGE, ROOT / "__init__.py", submodule_search_locations=[str(ROOT)])
    module = importlib.util.module_from_spec(spec)
    # Registered before it is executed, so that a submodule importing the package during that
    # execution finds the partially built one instead of starting a second copy.
    sys.modules[PACKAGE] = module
    spec.loader.exec_module(module)
