"""Beginner-install helpers: isolated test folders, prompts, no-tty fallback."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALL_SH = REPO_ROOT / "install.sh"


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def _source_helpers(script: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    merged["DEX_INSTALL_LIB_ONLY"] = "1"
    merged.pop("DEX_INSTALL_PYTHON", None)
    if env:
        merged.update(env)
    return subprocess.run(
        ["/bin/bash", "-c", f'set -e\n. "{INSTALL_SH}"\n{script}'],
        capture_output=True,
        text=True,
        timeout=20,
        env=merged,
    )


def test_default_target_is_home_dex_on_release() -> None:
    result = _source_helpers(
        'dex_default_target',
        env={"HOME": "/tmp/dex-home", "DEX_INSTALL_REF": "release"},
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "/tmp/dex-home/Dex"


def test_feature_branch_defaults_to_isolated_dex_test() -> None:
    result = _source_helpers(
        'dex_default_target',
        env={
            "HOME": "/tmp/dex-home",
            "DEX_INSTALL_REF": "cursor/beginner-install-b596",
        },
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "/tmp/dex-home/Dex-test"


def test_install_dir_wins_over_feature_branch_default() -> None:
    result = _source_helpers(
        'dex_default_target',
        env={
            "HOME": "/tmp/dex-home",
            "DEX_INSTALL_DIR": "~/Custom-Dex",
            "DEX_INSTALL_REF": "cursor/beginner-install-b596",
        },
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "/tmp/dex-home/Custom-Dex"


def test_expand_path_and_cloud_provider() -> None:
    home = _source_helpers('dex_expand_path "~/Notes"', env={"HOME": "/Users/sam"})
    assert home.stdout.strip() == "/Users/sam/Notes"
    icloud = _source_helpers(
        'dex_cloud_provider "/Users/sam/Library/Mobile Documents/com~apple~CloudDocs/Dex" && true',
    )
    assert icloud.returncode == 0
    assert "iCloud" in icloud.stdout
    onedrive = _source_helpers('dex_cloud_provider "/Users/sam/OneDrive/Dex" && true')
    assert "OneDrive" in onedrive.stdout
    local = _source_helpers(
        'if dex_cloud_provider "/Users/sam/Dex"; then echo cloud; else echo local; fi',
    )
    assert local.stdout.strip() == "local"


def test_should_bootstrap_skips_ci_in_place(tmp_path: Path) -> None:
    result = _source_helpers(
        f'if dex_should_bootstrap "{tmp_path}"; then echo clone; else echo inplace; fi',
        env={"DEX_INSTALL_NONINTERACTIVE": "1", "CI": "true"},
    )
    assert result.stdout.strip() == "inplace"


def test_should_bootstrap_when_install_dir_is_empty(tmp_path: Path) -> None:
    target = tmp_path / "Dex-test"
    result = _source_helpers(
        f'if dex_should_bootstrap "{target}"; then echo clone; else echo inplace; fi',
        env={"DEX_INSTALL_DIR": str(target), "DEX_INSTALL_NONINTERACTIVE": "1"},
    )
    assert result.stdout.strip() == "clone"


def test_should_not_bootstrap_existing_checkout(tmp_path: Path) -> None:
    root = tmp_path / "Dex-test"
    (root / "core").mkdir(parents=True)
    (root / "core" / "provision.cjs").write_text("// fixture\n", encoding="utf-8")
    (root / "install.sh").write_text("#!/bin/bash\n", encoding="utf-8")
    result = _source_helpers(
        f'if dex_should_bootstrap "{root}"; then echo clone; else echo inplace; fi',
        env={"DEX_INSTALL_DIR": str(root)},
    )
    assert result.stdout.strip() == "inplace"


def test_repo_ref_and_beta_line() -> None:
    ref = _source_helpers("dex_repo_ref", env={"DEX_INSTALL_REF": "cursor/beginner-install-b596"})
    assert ref.stdout.strip() == "cursor/beginner-install-b596"
    beta = _source_helpers("dex_apps_line")
    assert "heydex.ai/beta" in beta.stdout
    assert "Dex is in beta" not in beta.stdout
    assert "desktop app and mobile app" in beta.stdout


def test_welcome_and_finish_copy() -> None:
    text = INSTALL_SH.read_text(encoding="utf-8")
    assert "Dave and Dex are genuinely delighted" in text
    assert "Dave and the Dex team" not in text
    assert "Dex is in beta" not in text
    assert "Would you like to start Dex in Claude Code now?" in text
    assert 'exec "$bin" "/setup"' in text
    assert "</dev/tty" in text
    assert "Open your Dex folder now?" not in text
    assert 'echo "(That' not in text
    assert "Still working — this can take a minute." in text
    assert "✓ Your Dex folder is ready" in text
    assert "Copy and paste this line" in text


def test_branch_test_mode_only_when_isolated() -> None:
    release = _source_helpers(
        'if dex_is_branch_test; then echo yes; else echo no; fi',
        env={"DEX_INSTALL_REF": "release"},
    )
    assert release.stdout.strip() == "no"
    isolated = _source_helpers(
        'if dex_is_branch_test; then echo yes; else echo no; fi',
        env={"DEX_INSTALL_DIR": "/tmp/Dex-test", "DEX_INSTALL_REF": "release"},
    )
    assert isolated.stdout.strip() == "yes"
    feature = _source_helpers(
        'if dex_is_branch_test; then echo yes; else echo no; fi',
        env={"DEX_INSTALL_REF": "cursor/beginner-install-b596"},
    )
    assert feature.stdout.strip() == "yes"


def test_noninteractive_read_tty_uses_default() -> None:
    result = _source_helpers(
        'dex_read_tty "Name: " "Sam"; printf "%s\\n" "$REPLY"',
        env={"DEX_INSTALL_NONINTERACTIVE": "1"},
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "Sam"


def test_installer_source_keeps_ci_finish_and_forbids_claude_command_v() -> None:
    text = INSTALL_SH.read_text(encoding="utf-8")
    assert "Open one of these apps" in text
    assert "type: /setup" in text
    assert "Dex installation complete" in text
    assert "if command -v claude" not in text
    assert "dave@heydex.ai" in text
    assert "Open me next.md" in text
    assert "DEX_INSTALL_DIR" in text
    assert "DEX_INSTALL_REF" in text
    assert "Dex-test" in text
    # Isolation vars must prefix bash after the pipe, never curl.
    documented = [
        line for line in text.splitlines()
        if "curl -fsSL" in line and "raw.githubusercontent.com" in line
    ]
    assert documented, "install.sh must document the branch-test curl | bash command"
    for line in documented:
        assert line.lstrip("# ").startswith("curl ")
        assert '| DEX_INSTALL_DIR="$HOME/Dex-test"' in line
        assert "DEX_INSTALL_REF=" in line.split("|", 1)[1]
        assert "DEX_INSTALL_DIR=" not in line.split("curl", 1)[0]


def _mini_checkout(root: Path) -> None:
    (root / "core" / "migrations").mkdir(parents=True)
    (root / "core" / "mcp").mkdir(parents=True)
    (root / "core" / "provision.cjs").write_text("console.log('provision')\n", encoding="utf-8")
    (root / "core" / "migrations" / "v1-to-v2-brain-vault-split.cjs").write_text(
        """const fs = require('fs');
const path = require('path');
const real = process.env.DEX_TEST_REAL_MIGRATOR;
if (real) {
  const migrator = require(real);
  migrator.findReleaseRef(process.cwd(), path.join(process.cwd(), '.git'));
}
fs.mkdirSync(path.join('.dex', 'brain.git'), { recursive: true });
fs.mkdirSync(path.join('System', '.dex'), { recursive: true });
if (!fs.existsSync('.git')) fs.mkdirSync('.git');
fs.writeFileSync(path.join('System', '.dex', 'topology.json'), '{}\\n');
process.exit(0);
""",
        encoding="utf-8",
    )
    (root / "core" / "mcp" / "requirements.hash.txt").write_text("# fixture\n", encoding="utf-8")
    (root / "package-lock.json").write_text('{ "lockfileVersion": 3 }\n', encoding="utf-8")
    (root / "install.sh").write_text(INSTALL_SH.read_text(encoding="utf-8"), encoding="utf-8")
    (root / "scripts").mkdir(exist_ok=True)
    (root / "scripts" / "compose-vault-gitignore.py").write_text("# fixture\n", encoding="utf-8")
    (root / ".gitignore").write_text("00-Inbox/\n", encoding="utf-8")
    (root / "System").mkdir(exist_ok=True)


def _shim_bin(tmp_path: Path, *, node_ok: bool = True) -> Path:
    shim = tmp_path / "bin"
    shim.mkdir()
    real_node = shutil.which("node") or "/usr/bin/node"
    _write_executable(
        shim / "git",
        """#!/bin/sh
if [ "$1" = "--version" ]; then echo "git version 2.50.0"; exit 0; fi
if [ "$1" = "clone" ]; then
  target=""
  for arg in "$@"; do target="$arg"; done
  mkdir -p "$target"
  if [ -n "$DEX_TEST_CLONE_SRC" ] && [ -d "$DEX_TEST_CLONE_SRC" ]; then
    # Use cp, not python3: the python3 shim intercepts -c for installer probes.
    cp -a "$DEX_TEST_CLONE_SRC/." "$target/"
  fi
  exit 0
fi
if [ "$1" = "remote" ]; then exit 0; fi
exit 0
""",
    )
    if node_ok:
        _write_executable(
            shim / "node",
            f"""#!/bin/sh
if [ "$1" = "-v" ]; then echo "v22.0.0"; exit 0; fi
if [ "$1" = "-e" ]; then exec "{real_node}" "$@"; fi
case " $* " in
  *v1-to-v2-brain-vault-split.cjs*) exec "{real_node}" "$@" ;;
esac
exit 0
""",
        )
        _write_executable(shim / "npm", "#!/bin/sh\nexit 0\n")
        _write_executable(shim / "npx", "#!/bin/sh\nexit 0\n")
    _write_executable(
        shim / "python3",
        """#!/bin/sh
if [ "$1" = "--version" ]; then echo "Python 3.12.0"; exit 0; fi
if [ "$1" = "-c" ]; then echo "$0"; exit 0; fi
if [ "$1" = "-m" ] && [ "$2" = "venv" ]; then
  mkdir -p "$3/bin"
  printf '#!/bin/sh\\nexit 0\\n' > "$3/bin/pip"
  printf '#!/bin/sh\\nexit 0\\n' > "$3/bin/python"
  chmod +x "$3/bin/pip" "$3/bin/python"
  exit 0
fi
if [ "$1" = "-m" ] && [ "$2" = "core.harnesses.registry" ]; then
  echo '[]'
  exit 0
fi
exit 0
""",
    )
    _write_executable(shim / "xcode-select", "#!/bin/sh\nexit 0\n")
    return shim


def _run_install(tmp_path: Path, env: dict[str, str], *, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    clone_src = tmp_path / "clone-src"
    _mini_checkout(clone_src)
    shim = _shim_bin(tmp_path)
    merged = os.environ.copy()
    merged.pop("DEX_INSTALL_PYTHON", None)
    merged.update(
        {
            "PATH": f"{shim}:/usr/bin:/bin",
            "HOME": str(tmp_path / "home"),
            "DEX_INSTALL_LOG": str(tmp_path / "install.log"),
            "DEX_INSTALL_NO_OPEN": "1",
            "DEX_TEST_CLONE_SRC": str(tmp_path / "clone-src"),
        }
    )
    merged.update(env)
    (tmp_path / "home").mkdir(exist_ok=True)
    return subprocess.run(
        ["/bin/bash", str(clone_src / "install.sh")],
        cwd=tmp_path,
        env=merged,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def test_no_tty_isolated_dir_clones_into_test_folder_not_cwd(tmp_path: Path) -> None:
    target = tmp_path / "home" / "Dex-test"
    result = _run_install(
        tmp_path,
        {
            "DEX_INSTALL_DIR": str(target),
            "DEX_INSTALL_REF": "cursor/beginner-install-b596",
            "DEX_INSTALL_NONINTERACTIVE": "1",
        },
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (target / "core" / "provision.cjs").is_file()
    assert (target / "install.sh").is_file()
    assert not (tmp_path / "core").exists()
    assert "Dex installation complete" in result.stdout
    assert "Open one of these apps" in result.stdout


def test_no_tty_without_install_dir_stays_in_place_and_does_not_clone(tmp_path: Path) -> None:
    # Simulate CI: run the copied installer from a fixture folder that is not a
    # full checkout and do not set DEX_INSTALL_DIR.
    root = tmp_path / "fixture"
    _mini_checkout(root)
    (root / "core" / "provision.cjs").unlink()
    shim = _shim_bin(tmp_path)
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{shim}:/usr/bin:/bin",
            "DEX_INSTALL_NONINTERACTIVE": "1",
            "DEX_INSTALL_LOG": str(tmp_path / "install.log"),
        }
    )
    result = subprocess.run(
        ["/bin/bash", "install.sh"],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Dex installation complete" in result.stdout
    assert not (tmp_path / "home" / "Dex-test").exists()


def _parent_env_without_isolation(tmp_path: Path, extra: dict[str, str] | None = None) -> dict[str, str]:
    """Env a producer process (curl/cat) may have — isolation vars must not live here."""
    env = os.environ.copy()
    for key in (
        "DEX_INSTALL_DIR",
        "DEX_INSTALL_REF",
        "DEX_INSTALL_NONINTERACTIVE",
        "DEX_INSTALL_PYTHON",
        "CI",
    ):
        env.pop(key, None)
    env.update(
        {
            "PATH": extra.pop("PATH") if extra and "PATH" in extra else env.get("PATH", "/usr/bin:/bin"),
            "HOME": str(tmp_path / "home"),
            "DEX_INSTALL_LOG": str(tmp_path / "install.log"),
            "DEX_INSTALL_NO_OPEN": "1",
            "DEX_TEST_CLONE_SRC": str(tmp_path / "clone-src"),
        }
    )
    if extra:
        env.update(extra)
    (tmp_path / "home").mkdir(exist_ok=True)
    return env


def test_piped_install_reads_isolation_vars_from_bash_not_the_producer(tmp_path: Path) -> None:
    """Real user shape: cat install.sh | VAR=... bash. Vars on bash, not on cat."""
    clone_src = tmp_path / "clone-src"
    _mini_checkout(clone_src)
    shim = _shim_bin(tmp_path)
    target = tmp_path / "home" / "Dex-test"
    live = tmp_path / "home" / "Dex"
    parent = _parent_env_without_isolation(
        tmp_path,
        {"PATH": f"{shim}:/usr/bin:/bin"},
    )
    result = subprocess.run(
        f'cat "{clone_src / "install.sh"}" | '
        f'DEX_INSTALL_DIR="{target}" '
        f'DEX_INSTALL_REF="cursor/beginner-install-b596" '
        f"DEX_INSTALL_NONINTERACTIVE=1 DEX_INSTALL_NO_OPEN=1 bash",
        shell=True,
        cwd=tmp_path,
        env=parent,
        capture_output=True,
        text=True,
        timeout=30,
        executable="/bin/bash",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (target / "core" / "provision.cjs").is_file()
    assert (target / "install.sh").is_file()
    assert not live.exists()
    assert not (tmp_path / "core").exists()
    assert "Isolated install folder" in result.stdout
    assert "Dex installation complete" in result.stdout


def test_piped_install_ignores_isolation_vars_prefixed_on_cat(tmp_path: Path) -> None:
    """Broken shape: VAR=... cat install.sh | bash. bash must not see the vars."""
    clone_src = tmp_path / "clone-src"
    _mini_checkout(clone_src)
    shim = _shim_bin(tmp_path)
    target = tmp_path / "home" / "Dex-test"
    live = tmp_path / "home" / "Dex"
    # Noninteractive belongs on the inherited env so the in-place path is
    # stable. Isolation folder/ref must stay on cat only — bash ignores those.
    parent = _parent_env_without_isolation(
        tmp_path,
        {
            "PATH": f"{shim}:/usr/bin:/bin",
            "DEX_INSTALL_NONINTERACTIVE": "1",
        },
    )
    result = subprocess.run(
        f'DEX_INSTALL_DIR="{target}" '
        f'DEX_INSTALL_REF="cursor/beginner-install-b596" '
        f'cat "{clone_src / "install.sh"}" | bash',
        shell=True,
        cwd=clone_src,
        env=parent,
        capture_output=True,
        text=True,
        timeout=30,
        executable="/bin/bash",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert not (target / "core" / "provision.cjs").exists()
    assert not live.exists()
    assert (clone_src / "core" / "provision.cjs").is_file()
    assert "Isolated install folder" not in result.stdout
    assert "Dex installation complete" in result.stdout


def test_missing_node_stops_with_plain_english(tmp_path: Path) -> None:
    target = tmp_path / "home" / "Dex-test"
    clone_src = tmp_path / "clone-src"
    _mini_checkout(clone_src)
    shim = _shim_bin(tmp_path, node_ok=False)
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{shim}:/usr/bin:/bin",
            "HOME": str(tmp_path / "home"),
            "DEX_INSTALL_DIR": str(target),
            "DEX_INSTALL_REF": "cursor/beginner-install-b596",
            "DEX_INSTALL_NONINTERACTIVE": "1",
            "DEX_INSTALL_LOG": str(tmp_path / "install.log"),
            "DEX_INSTALL_NO_OPEN": "1",
            "DEX_TEST_CLONE_SRC": str(clone_src),
        }
    )
    (tmp_path / "home").mkdir(exist_ok=True)
    result = subprocess.run(
        ["/bin/bash", str(clone_src / "install.sh")],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode != 0
    assert "Node.js is not installed" in result.stdout or "nodejs.org" in result.stdout
    assert not target.exists() or not (target / "core" / "provision.cjs").exists()


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_NAME": "Dex Test",
            "GIT_AUTHOR_EMAIL": "dex-test@example.com",
            "GIT_COMMITTER_NAME": "Dex Test",
            "GIT_COMMITTER_EMAIL": "dex-test@example.com",
        }
    )
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result


def _official_source(tmp_path: Path, feature_ref: str) -> Path:
    src = tmp_path / "official-src"
    _mini_checkout(src)
    (src / "CLAUDE.md").write_text("# Dex\n", encoding="utf-8")
    _git(src, "init", "-b", "release")
    _git(src, "add", "-A")
    _git(src, "commit", "-m", "official release")
    _git(src, "branch", feature_ref)
    # `git remote get-url` applies insteadOf. Keep the rewritten file:// path
    # matching dex_remote_is_official (*github.com/davekilleen/[Dd]ex*).
    bare = tmp_path / "github.com" / "davekilleen" / "dex.git"
    bare.parent.mkdir(parents=True, exist_ok=True)
    _git(tmp_path, "clone", "--bare", "--quiet", str(src), str(bare))
    return bare


def _git_preserving_configured_url(bin_dir: Path) -> Path:
    """Real git, except `remote get-url` returns the stored URL (no insteadOf)."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    real_git = shutil.which("git") or "/usr/bin/git"
    if Path(real_git).resolve() == (bin_dir / "git").resolve():
        real_git = "/usr/bin/git"
    _write_executable(
        bin_dir / "git",
        f"""#!/bin/sh
# Migrator calls: git --git-dir=... --work-tree=... remote get-url origin
seen_remote=0
seen_get_url=0
git_dir=""
name=""
for arg in "$@"; do
  case "$arg" in
    --git-dir=*) git_dir="${{arg#--git-dir=}}" ;;
    remote) seen_remote=1 ;;
    get-url) seen_get_url=1 ;;
    -c|--work-tree=*|--push|--all|--help) ;;
    -*) ;;
    *)
      if [ "$seen_get_url" = 1 ] && [ -z "$name" ]; then
        name="$arg"
      fi
      ;;
  esac
done
if [ "$seen_remote" = 1 ] && [ "$seen_get_url" = 1 ] && [ -n "$name" ]; then
  if [ -n "$git_dir" ]; then
    url=$("{real_git}" --git-dir="$git_dir" config --local --get "remote.${{name}}.url" 2>/dev/null || true)
  else
    url=$("{real_git}" config --local --get "remote.${{name}}.url" 2>/dev/null || true)
  fi
  if [ -n "$url" ]; then
    printf '%s\\n' "$url"
    exit 0
  fi
fi
exec "{real_git}" "$@"
""",
    )
    return bin_dir / "git"


def _instead_of_env(bare: Path, git_bin: Path | None = None) -> dict[str, str]:
    official = "https://github.com/davekilleen/dex.git"
    rewrite = f"file://{bare}"
    env = {
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": f"url.{rewrite}.insteadof",
        "GIT_CONFIG_VALUE_0": official,
        "DEX_INSTALL_REPO": official,
        "DEX_TEST_REAL_MIGRATOR": str(REPO_ROOT / "core" / "migrations" / "v1-to-v2-brain-vault-split.cjs"),
    }
    if git_bin is not None:
        _git_preserving_configured_url(git_bin)
        env["PATH"] = f"{git_bin}:{os.environ.get('PATH', '/usr/bin:/bin')}"
    return env


def test_ensure_official_release_ref_fetches_for_feature_branch(tmp_path: Path) -> None:
    feature = "cursor/beginner-install-b596"
    bare = _official_source(tmp_path, feature)
    work = tmp_path / "work"
    extra = _instead_of_env(bare, tmp_path / "git-bin")
    clone = subprocess.run(
        [
            "git",
            "clone",
            "--quiet",
            "--branch",
            feature,
            "--single-branch",
            extra["DEX_INSTALL_REPO"],
            str(work),
        ],
        env={**os.environ, **extra},
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert clone.returncode == 0, clone.stdout + clone.stderr
    missing = subprocess.run(
        ["git", "rev-parse", "--verify", "refs/remotes/origin/release^{commit}"],
        cwd=work,
        capture_output=True,
        text=True,
    )
    assert missing.returncode != 0
    result = subprocess.run(
        [
            "/bin/bash",
            "-c",
            f'set -e; . "{INSTALL_SH}"; dex_ensure_official_release_ref; git rev-parse --verify refs/remotes/origin/release^{{commit}}',
        ],
        cwd=work,
        env={
            **os.environ,
            **extra,
            "DEX_INSTALL_LIB_ONLY": "1",
            "DEX_INSTALL_REF": feature,
            "DEX_INSTALL_NONINTERACTIVE": "1",
        },
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip()
    prove = subprocess.run(
        [
            "node",
            "-e",
            "const m=require(process.argv[1]); console.log(m.findReleaseRef(process.cwd(), require('path').join(process.cwd(),'.git')).ref)",
            extra["DEX_TEST_REAL_MIGRATOR"],
        ],
        cwd=work,
        env={**os.environ, **extra},
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert prove.returncode == 0, prove.stdout + prove.stderr
    assert "refs/remotes/origin/release" in prove.stdout


def test_piped_feature_branch_fetches_release_and_finishes(tmp_path: Path) -> None:
    """Real | bash pipe + real git: feature-only clone must still get official release history."""
    feature = "cursor/beginner-install-b596"
    bare = _official_source(tmp_path, feature)
    extra = _instead_of_env(bare)
    shim = _shim_bin(tmp_path)
    _git_preserving_configured_url(shim)
    target = tmp_path / "home" / "Dex-test"
    live = tmp_path / "home" / "Dex"
    parent = _parent_env_without_isolation(
        tmp_path,
        {
            "PATH": f"{shim}:/usr/bin:/bin",
            **extra,
        },
    )
    script = tmp_path / "official-src" / "install.sh"
    result = subprocess.run(
        f'cat "{script}" | '
        f'DEX_INSTALL_DIR="{target}" '
        f'DEX_INSTALL_REF="{feature}" '
        f"DEX_INSTALL_REPO='{extra['DEX_INSTALL_REPO']}' "
        f"DEX_INSTALL_NONINTERACTIVE=1 DEX_INSTALL_NO_OPEN=1 bash",
        shell=True,
        cwd=tmp_path,
        env=parent,
        capture_output=True,
        text=True,
        timeout=60,
        executable="/bin/bash",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "official release history" not in result.stdout.lower() or "could not prove" not in result.stdout
    assert "could not prove that the local release branch" not in result.stdout
    assert (target / "core" / "provision.cjs").is_file()
    assert not live.exists()
    assert "Dex installation complete" in result.stdout
    prove = subprocess.run(
        ["git", "rev-parse", "--verify", "refs/remotes/upstream/release^{commit}"],
        cwd=target,
        capture_output=True,
        text=True,
    )
    if prove.returncode != 0:
        prove = subprocess.run(
            ["git", "rev-parse", "--verify", "refs/remotes/origin/release^{commit}"],
            cwd=target,
            capture_output=True,
            text=True,
        )
    assert prove.returncode == 0, "branch-test install must fetch official release history"
    found = subprocess.run(
        [
            "node",
            "-e",
            "const m=require(process.argv[1]); console.log(m.findReleaseRef(process.cwd(), require('path').join(process.cwd(),'.git')).ref)",
            extra["DEX_TEST_REAL_MIGRATOR"],
        ],
        cwd=target,
        env=parent,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert found.returncode == 0, found.stdout + found.stderr


def test_release_history_safety_check_still_in_migrator() -> None:
    text = (REPO_ROOT / "core" / "migrations" / "v1-to-v2-brain-vault-split.cjs").read_text(
        encoding="utf-8"
    )
    assert "could not prove that the local release branch contains only official release history" in text
    installer = INSTALL_SH.read_text(encoding="utf-8")
    assert "dex_ensure_official_release_ref" in installer
    assert "git clone --quiet --branch" in installer
    assert "config', '--get', `remote.${remote}.url`" in text or (
        "config', '--get'" in text and "remote.${remote}.url" in text
    )
    assert "trap - EXIT" in installer
    assert installer.count("trap - EXIT") >= 3
