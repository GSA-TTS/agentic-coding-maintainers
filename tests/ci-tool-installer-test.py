"""Offline installer control-flow fixtures; run only in a workspace sandbox.

Every external installer command is a synthetic stub on a closed PATH. No
downloads, real package installs, native tool execution, or upstream digest
verification occur. The hash stub checks the supplied upstream pin independently
of the installer and verifies synthetic payload integrity, not upstream bytes.
"""

import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

if not sys.flags.isolated or not sys.dont_write_bytecode:
    raise SystemExit("Run this sandbox test with python3 -I -B")

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "tools/install-ci-tools.sh"
BASH = shutil.which("bash")
if BASH is None:
    raise SystemExit("sandbox must provide Bash")

# Independent expectations, not parsed from the installer under test.
PINS = {
    "x86_64": (
        "a293ac937715ae6fb6b64da86761598379e6149f40fbc00fde9ba8a2a562ac65",
        "8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8",
        "d185f726bdaf92df78273217dfdd24ebcd6b0ef48cf3ce776ff5762b6e138c99",
        "8c3be12b05d5c177a04c29e3c78ce89ac86f1595681cab149b65b97c4e227198",
    ),
    "aarch64": (
        "d3ead1f0ed779e777a034ccd9286be6bd9bd3cdaba732ff9797f8288a283e9e2",
        "325e971b6ba9bfa504672e29be93c24981eeb1c07576d730e9f7c8805afff0c6",
        "37eebbd5762a44f262d94875431b14a6d2402991e90a685113ea97b8b41be833",
        "12b331c1d2db6b9eb13cfca64306b1b157a86eb69db83023e261eaa7e7c14588",
    ),
}
ARCHIVES = ("ruff.tgz", "actionlint.tgz", "zizmor.tgz", "shellcheck.tar.xz")
TOOLS = ("ruff", "actionlint", "zizmor", "shellcheck")


def assets(arch):
    action_arch = "amd64" if arch == "x86_64" else "arm64"
    urls = (
        f"https://github.com/astral-sh/ruff/releases/download/0.17.1/ruff-{arch}-unknown-linux-gnu.tar.gz",
        f"https://github.com/rhysd/actionlint/releases/download/v1.7.12/actionlint_1.7.12_linux_{action_arch}.tar.gz",
        f"https://github.com/zizmorcore/zizmor/releases/download/v1.31.1/zizmor-{arch}-unknown-linux-gnu.tar.gz",
        f"https://github.com/koalaman/shellcheck/releases/download/v0.11.0/shellcheck-v0.11.0.linux.{arch}.tar.xz",
    )
    members = (f"ruff-{arch}-unknown-linux-gnu/ruff", "actionlint", "zizmor",
               "shellcheck-v0.11.0/shellcheck")
    return {url: {"pin": pin, "member": member}
            for url, pin, member in zip(urls, PINS[arch], members)}


STUB = r'''
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

name = Path(sys.argv[0]).name
args = sys.argv[1:]
root = Path(os.environ["FIXTURE_ROOT"])
spec = json.loads((root / "assets.json").read_text())
stdin = sys.stdin.read() if name == "sha256sum" else ""
with (root / "events.jsonl").open("a") as log:
    log.write(json.dumps({"name": name, "args": args, "stdin": stdin}) + "\n")

if name == "uname":
    assert args in (["-s"], ["-m"])
    print(os.environ["FIXTURE_OS" if args == ["-s"] else "FIXTURE_ARCH"])
elif name == "python3":
    if args == ["-c", 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")']:
        print(os.environ["FIXTURE_PYTHON"])
    else:
        assert args == ["-m", "venv", str(root / "destination/venv")]
        bindir = Path(args[2]) / "bin"
        bindir.mkdir(parents=True)
        shutil.copyfile(sys.argv[0], bindir / "pip")
        (bindir / "pip").chmod(0o700)
        (bindir / "bandit").write_text("synthetic Bandit; never execute\n")
elif name == "dirname":
    assert len(args) == 1
    print(str(Path(args[0]).parent))
elif name == "mkdir":
    assert args[0] == "-p"
    for arg in args[1:]:
        path = Path(arg)
        assert path.is_relative_to(root / "destination")
        path.mkdir(parents=True, exist_ok=True)
elif name == "mktemp":
    assert args == ["-d"]
    path = Path(tempfile.mkdtemp(dir=root / "scratch"))
    assert path.stat().st_mode & 0o777 == 0o700
    print(path)
elif name == "curl":
    assert args[:8] == ["--fail", "--location", "--proto", "=https",
                        "--proto-redir", "=https", "--tlsv1.2", "--output"]
    assert len(args) == 10
    output, url = Path(args[8]), args[9]
    assert url in spec
    assert output.parent.parent == root / "scratch"
    if output.name == os.environ.get("FAIL_DOWNLOAD"):
        output.write_bytes(b"partial failed download")
        raise SystemExit(22)
    payload = ("synthetic archive:" + url).encode()
    if output.name == os.environ.get("CORRUPT_DOWNLOAD"):
        payload += b"corrupt"
    output.write_bytes(payload)
    output.with_suffix(".url").write_text(url)
elif name == "sha256sum":
    assert args == ["--check", "--strict"]
    expected, filename = stdin.rstrip("\n").split("  ", 1)
    archive = Path(filename)
    url = archive.with_suffix(".url").read_text()
    if expected != spec[url]["pin"]:
        print("unexpected upstream pin", file=sys.stderr)
        raise SystemExit(1)
    actual = hashlib.sha256(archive.read_bytes()).hexdigest()
    synthetic = hashlib.sha256(("synthetic archive:" + url).encode()).hexdigest()
    if actual != synthetic:
        print("synthetic checksum mismatch", file=sys.stderr)
        raise SystemExit(1)
    archive.with_suffix(".verified").touch()
elif name == "tar":
    archive = Path(args[1])
    assert archive.with_suffix(".verified").exists(), "extraction before verification"
    assert args[:1] == (["-xJf"] if archive.name.endswith(".xz") else ["-xzf"])
    assert args[2:4] == ["-C", str(archive.parent)]
    member = spec[archive.with_suffix(".url").read_text()]["member"]
    assert args[4:] == ([member] if member in ("actionlint", "zizmor") else [])
    extracted = archive.parent / member
    extracted.parent.mkdir(parents=True, exist_ok=True)
    extracted.write_text("synthetic native tool; never execute\n")
elif name == "install":
    assert args[:2] == ["-m", "0755"]
    assert len(args) == 4
    assert Path(args[2]).is_file()
    assert Path(args[3]).parent == root / "destination/bin"
    shutil.copyfile(args[2], args[3])
elif name == "pip":
    lock = root / ("tools/ci/bandit-requirements-linux-" + os.environ["FIXTURE_ARCH"] + ".txt")
    assert args == ["install", "--disable-pip-version-check", "--require-hashes", "-r", str(lock)]
    assert len(lock.read_text().splitlines()) == 7
elif name == "cp":
    assert args == [str(root / "tools/ci/package.json"),
                    str(root / "tools/ci/package-lock.json"), str(root / "destination/pyright") + "/"]
    for source in args[:2]:
        shutil.copyfile(source, Path(args[2]) / Path(source).name)
elif name == "npm":
    assert args == ["ci", "--ignore-scripts", "--no-audit", "--no-fund"]
    assert Path.cwd() == root / "destination/pyright"
    bindir = Path.cwd() / "node_modules/.bin"
    bindir.mkdir(parents=True)
    (bindir / "pyright").write_text("synthetic Pyright; never execute\n")
elif name == "ln":
    assert args[0] == "-sf" and len(args) == 3
    assert Path(args[1]).is_file()
    assert Path(args[2]).parent == root / "destination/bin"
    Path(args[2]).symlink_to(args[1])
elif name == "rm":
    assert args[:2] == ["-rf", "--"] and len(args) == 3
    path = Path(args[2])
    assert path.parent == root / "scratch"
    shutil.rmtree(path)
else:
    raise AssertionError("unexpected command: " + name)
'''


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(BASH, "sandbox must provide Bash")
        temporary = tempfile.TemporaryDirectory(prefix="ci-installer-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.commands = self.root / "commands"
        self.commands.mkdir()
        (self.root / "scratch").mkdir()
        (self.root / "tools/ci").mkdir(parents=True)
        self.installer = self.root / "tools/install-ci-tools.sh"
        shutil.copyfile(INSTALLER, self.installer)
        for filename in ("bandit-requirements-linux-x86_64.txt",
                         "bandit-requirements-linux-aarch64.txt", "package.json", "package-lock.json"):
            shutil.copyfile(ROOT / "tools/ci" / filename, self.root / "tools/ci" / filename)
        # Closed PATH and clean environment: no fallback to curl/pip/npm/native tools.
        for command in ("uname", "python3", "dirname", "mkdir", "mktemp", "curl",
                        "sha256sum", "tar", "install", "ln", "cp", "npm", "rm"):
            stub = self.commands / command
            stub.write_text(f"#!{sys.executable} -I\n" + STUB)
            stub.chmod(0o700)

    def run_installer(self, arch="x86_64", system="Linux", python="3.12", **failures):
        assert BASH is not None
        (self.root / "assets.json").write_text(json.dumps(assets(arch if arch in PINS else "x86_64")))
        environment = {
            "PATH": str(self.commands), "HOME": str(self.root), "LC_ALL": "C",
            "FIXTURE_ROOT": str(self.root), "FIXTURE_ARCH": arch,
            "FIXTURE_OS": system, "FIXTURE_PYTHON": python, **failures,
        }
        result = subprocess.run(
            [BASH, str(self.installer), str(self.root / "destination")],
            cwd=self.root, env=environment, text=True, capture_output=True,
            timeout=30, check=False,
        )
        events = [json.loads(line) for line in (self.root / "events.jsonl").read_text().splitlines()]
        self.assertEqual(list((self.root / "scratch").iterdir()), [], result.stderr)
        return result, events

    def assert_success(self, arch):
        result, events = self.run_installer(arch)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        names = [event["name"] for event in events]
        self.assertEqual(names, ["uname", "uname", "python3", "dirname", "mkdir", "mktemp"]
                         + ["curl", "sha256sum", "tar", "install"] * 4
                         + ["python3", "pip", "ln", "mkdir", "cp", "npm", "ln", "rm"])
        self.assertEqual([event["args"][-1] for event in events if event["name"] == "curl"],
                         list(assets(arch)))
        self.assertEqual([event["stdin"].split("  ")[0] for event in events
                          if event["name"] == "sha256sum"], list(PINS[arch]))
        self.assertEqual({path.name for path in (self.root / "destination/bin").iterdir()},
                         {*TOOLS, "bandit", "pyright"})
        self.assertTrue((self.root / "destination/bin/bandit").is_symlink())
        self.assertTrue((self.root / "destination/bin/pyright").is_symlink())
        for name in ("package.json", "package-lock.json"):
            self.assertEqual((self.root / "destination/pyright" / name).read_bytes(),
                             (ROOT / "tools/ci" / name).read_bytes())

    def test_x86_64(self):
        self.assert_success("x86_64")

    def test_aarch64(self):
        self.assert_success("aarch64")

    def test_lock_diff_is_only_pyyaml_wheel(self):
        x86 = (ROOT / "tools/ci/bandit-requirements-linux-x86_64.txt").read_text().splitlines()
        arm = (ROOT / "tools/ci/bandit-requirements-linux-aarch64.txt").read_text().splitlines()
        self.assertEqual(len(x86), 7)
        self.assertEqual(len(arm), 7)
        self.assertEqual([line.split(" --hash=")[0] for line in arm], [
            "bandit==1.9.4", "markdown-it-py==4.2.0", "mdurl==0.1.2", "pygments==2.21.0",
            "pyyaml==6.0.3", "rich==15.0.0", "stevedore==5.9.1",
        ])
        for line in x86 + arm:
            self.assertRegex(line, r"^[a-z-]+==[0-9.]+ --hash=sha256:[0-9a-f]{64}$")
        self.assertEqual([(left, right) for left, right in zip(x86, arm) if left != right], [(
            "pyyaml==6.0.3 --hash=sha256:ba1cc08a7ccde2d2ec775841541641e4548226580ab850948cbfda66a1befcdc",
            "pyyaml==6.0.3 --hash=sha256:9149cad251584d5fb4981be1ecde53a1ca46c891a79788c0df828d2f166bda28",
        )])

    def assert_rejected(self, **platform):
        result, events = self.run_installer(**platform)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertFalse((self.root / "destination").exists())
        expected = ["uname", "uname"]
        if "python" in platform:
            expected.append("python3")
            self.assertIn("requires Python 3.12", result.stderr)
        else:
            self.assertIn("supports Linux x86_64 and aarch64 only", result.stderr)
        self.assertEqual([event["name"] for event in events], expected)

    def assert_failure(self, arch, index, failure):
        archive = ARCHIVES[index]
        if failure == "BAD_PIN":
            text = self.installer.read_text()
            self.assertEqual(text.count(PINS[arch][index]), 1)
            self.installer.write_text(text.replace(PINS[arch][index], "0" * 64))
            result, events = self.run_installer(arch)
        else:
            result, events = self.run_installer(arch, **{failure: archive})
        self.assertEqual(result.returncode, 22 if failure == "FAIL_DOWNLOAD" else 1, result.stderr)
        names = [event["name"] for event in events]
        expected = ["uname", "uname", "python3", "dirname", "mkdir", "mktemp"]
        expected += ["curl", "sha256sum", "tar", "install"] * index + ["curl"]
        if failure != "FAIL_DOWNLOAD":
            expected.append("sha256sum")
            self.assertIn("unexpected upstream pin" if failure == "BAD_PIN"
                          else "synthetic checksum mismatch", result.stderr)
        expected.append("rm")
        self.assertEqual(names, expected, "only cleanup may follow download/hash failure")
        self.assertEqual({path.name for path in (self.root / "destination/bin").iterdir()},
                         set(TOOLS[:index]))


# Separate cases get fresh fixtures, including each of the four failure positions.
def rejection_case(**platform):
    def test(self):
        self.assert_rejected(**platform)
    return test


def failure_case(arch, index, failure):
    def test(self):
        self.assert_failure(arch, index, failure)
    return test


for system, arch in (("Darwin", "arm64"), ("Darwin", "x86_64"), ("Linux", "arm64"),
                     ("Linux", "riscv64"), ("Linux", "armv7l"), ("FreeBSD", "aarch64")):
    setattr(InstallerTests, f"test_reject_{system}_{arch}", rejection_case(system=system, arch=arch))
for arch in PINS:
    for version in ("3.11", "3.13", ""):
        suffix = re.sub(r"\W", "_", version) or "empty"
        setattr(InstallerTests, f"test_reject_python_{arch}_{suffix}",
                rejection_case(arch=arch, python=version))
    for index, tool in enumerate(TOOLS):
        for failure in ("FAIL_DOWNLOAD", "CORRUPT_DOWNLOAD", "BAD_PIN"):
            setattr(InstallerTests, f"test_{arch}_{tool}_{failure.lower()}",
                    failure_case(arch, index, failure))


if __name__ == "__main__":
    unittest.main()
