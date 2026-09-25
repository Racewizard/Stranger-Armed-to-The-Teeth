r"""Build AT3's private Python runtime: StrangerAT3\python\.

AT3 is a launcher plus 48 Python tools that use ONLY the standard library.
Asking every player to install Python first was the single biggest support
problem, so the release carries its own interpreter - laid out exactly like
python.org's "embeddable package":

    python.exe, pythonw.exe, python3.dll, python3XX.dll, vcruntime140*.dll
    *.pyd + their DLLs          the compiled standard-library modules
    python3XX.zip               the standard library, precompiled (.pyc)
    python3XX._pth              isolates it: no PYTHONPATH, no user site,
                                no system install - and adds ..\..\ModTools
    LICENSE.txt                 the PSF license, as the license requires

It is built FROM the python.org CPython this script runs under (sys.base_prefix),
so nothing is downloaded and the runtime is exactly the interpreter the tools
were tested with. Dropped because no AT3 tool imports them: tkinter/Tcl/Tk,
IDLE, the test suite, ensurepip, venv, sqlite, turtle demos, pydoc data.

    python StrangerAT3\build_runtime.py            build (replaces python\)
    python StrangerAT3\build_runtime.py --check    run every ModTools script's
                                                   imports under the new runtime
"""
import argparse, glob, os, shutil, subprocess, sys, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(HERE, "python")
SRC = sys.base_prefix
VER = "%d%d" % sys.version_info[:2]

DROP_LIB = {"test", "tkinter", "idlelib", "turtledemo", "ensurepip", "venv", "lib2to3",
            "site-packages", "pydoc_data", "sqlite3", "__pycache__", "unittest"}
DROP_DLL = ("_tkinter", "tcl", "tk", "_sqlite3", "sqlite3", "libtommath")


def build():
    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    os.makedirs(OUT)
    for f in ("python.exe", "pythonw.exe", "python3.dll", "python%s.dll" % VER,
              "vcruntime140.dll", "vcruntime140_1.dll", "LICENSE.txt"):
        p = os.path.join(SRC, f)
        if os.path.exists(p):
            shutil.copy2(p, OUT)
    for p in glob.glob(os.path.join(SRC, "DLLs", "*")):
        b = os.path.basename(p).lower()
        if b.endswith((".pyd", ".dll")) and not b.startswith(DROP_DLL):
            shutil.copy2(p, OUT)

    lib = os.path.join(SRC, "Lib")
    zpath = os.path.join(OUT, "python%s.zip" % VER)
    n = 0
    with zipfile.PyZipFile(zpath, "w", compression=zipfile.ZIP_DEFLATED, optimize=0) as z:
        for name in sorted(os.listdir(lib)):
            full = os.path.join(lib, name)
            if name in DROP_LIB:
                continue
            if os.path.isdir(full):
                if not os.path.exists(os.path.join(full, "__init__.py")):
                    continue
                z.writepy(full, filterfunc=lambda p: not any(
                    ("%s%s%s" % (os.sep, d, os.sep)) in p for d in ("test", "tests", "idle_test")))
                n += 1
            elif name.endswith(".py"):
                z.writepy(full)
                n += 1
    with open(os.path.join(OUT, "python%s._pth" % VER), "w", encoding="ascii") as f:
        f.write("python%s.zip\n.\n..\\..\\ModTools\n" % VER)
    size = sum(os.path.getsize(os.path.join(dp, x)) for dp, _d, fs in os.walk(OUT) for x in fs)
    print("built %s - Python %s, %d stdlib entries, %.1f MB" % (OUT, sys.version.split()[0], n, size / 1e6))


def check():
    exe = os.path.join(OUT, "python.exe")
    if not os.path.exists(exe):
        sys.exit("no runtime - build it first")
    probe = ("import sys; print(sys.version.split()[0], sys.prefix); "
             "assert not any('site-packages' in p for p in sys.path), sys.path")
    r = subprocess.run([exe, "-c", probe], capture_output=True, text=True)
    print("runtime:", (r.stdout or r.stderr).strip())
    bad = 0
    mods = sorted(os.path.splitext(os.path.basename(p))[0] for p in glob.glob(os.path.join(ROOT, "ModTools", "*.py")))
    for m in mods:
        # Import each tool as a module (its main() does not run) - this proves
        # every import it needs resolves inside the private runtime.
        r = subprocess.run([exe, "-c", "import %s" % m], capture_output=True, text=True,
                           cwd=os.path.join(ROOT, "ModTools"))
        if r.returncode != 0:
            last = (r.stderr.strip().splitlines() or ["?"])[-1]
            if "ModuleNotFoundError" in last or "ImportError" in last:
                bad += 1
                print("  FAIL %-28s %s" % (m, last))
    print("%d tool(s) checked, %d import failure(s)" % (len(mods), bad))
    return 1 if bad else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    sys.exit(check() if a.check else (build() or 0))
