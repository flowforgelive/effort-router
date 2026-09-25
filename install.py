#!/usr/bin/env python3
"""Install effort-router into every supported AI CLI found on this machine.

  python install.py                          install or update (idempotent)
  python install.py --reset-effort-defaults  also drop the global effort defaults
  python install.py --dry-run                show what would change, change nothing
  python install.py --hosts claude,codex     limit to some hosts
  python install.py uninstall                remove everything installed

Works on macOS, Linux and Windows. Files are copied, not symlinked, so re-run
it after `git pull`. Every edited config is backed up to
~/.local/state/effort-router/backups/<timestamp>/ first; directories it did
not create are never overwritten.
"""

import argparse
import difflib
import filecmp
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NAME = "effort-router"
PLUGIN_ID = f"{NAME}@{NAME}"
BLOCK_BEGIN = f"<!-- {NAME}:begin -->"
BLOCK_END = f"<!-- {NAME}:end -->"
MARKER = ".effort-router-managed"
WINDOWS = os.name == "nt"
HOSTS = ("claude", "codex", "agy", "grok")


class Installer:
    def __init__(self, dry_run, home=None, env=os.environ):
        self.dry_run = dry_run
        home = Path(home) if home else Path.home()
        self.state = Path(env.get("XDG_STATE_HOME") or home / ".local" / "state") / NAME
        self.backup_dir = self.state / "backups" / time.strftime("%Y%m%d-%H%M%S")
        self.codex_home = Path(env.get("CODEX_HOME") or home / ".codex")
        self.agy_config = home / ".gemini" / "config"
        self.grok_home = home / ".grok"
        self.claude_settings = home / ".claude" / "settings.json"

    # ------------------------------------------------------------ primitives
    def say(self, message):
        print(("[dry-run] " if self.dry_run else "") + message)

    def backup(self, path):
        if self.dry_run or not path.exists():
            return
        target = self.backup_dir / path.relative_to(path.anchor)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)

    def write_text(self, path, new):
        old = read(path)
        if old == new:
            return False
        diff = difflib.unified_diff(old.splitlines(), new.splitlines(), str(path), str(path), lineterm="", n=1)
        self.say(f"edit {path}\n" + "\n".join(f"    {line}" for line in list(diff)[2:]))
        if not self.dry_run:
            self.backup(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(new, encoding="utf-8", newline="\n")
        return True

    def owned(self, path):
        """True when the path is ours to replace: absent, our marker dir, or a symlink from an older install."""
        if path.is_symlink():
            return NAME in os.readlink(path)
        return not path.exists() or (path / MARKER).exists()

    def install_tree(self, target, files):
        """Make `target` a managed directory holding exactly `files` ({relative path: text or source Path})."""
        if not self.owned(target):
            self.say(f"SKIP {target}: exists and was not created by {NAME} — remove it by hand to install")
            return
        if self.tree_matches(target, files):
            return
        self.say(f"write {target}/ ({len(files)} files)")
        if self.dry_run:
            return
        self.remove_tree(target, quiet=True)
        for rel, content in {**files, MARKER: ""}.items():
            dest = target / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(content, Path):
                shutil.copy2(content, dest)
            else:
                dest.write_text(content, encoding="utf-8", newline="\n")

    def tree_matches(self, target, files):
        if target.is_symlink() or not (target / MARKER).exists():
            return False
        present = {p.relative_to(target).as_posix() for p in target.rglob("*") if p.is_file()} - {MARKER}
        if present != set(files):
            return False
        for rel, content in files.items():
            dest = target / rel
            if isinstance(content, Path):
                if not filecmp.cmp(content, dest, shallow=False):
                    return False
            elif dest.read_text(encoding="utf-8") != content:
                return False
        return True

    def remove_tree(self, target, quiet=False):
        if not (target.is_symlink() or target.exists()) or not self.owned(target):
            return
        if not quiet:
            self.say(f"remove {target}")
        if self.dry_run:
            return
        if target.is_symlink():
            target.unlink()
        else:
            shutil.rmtree(target)

    def run(self, *cmd):
        self.say("run " + " ".join(cmd))
        if self.dry_run:
            return True
        exe = shutil.which(cmd[0]) or cmd[0]  # claude is claude.cmd on Windows
        result = subprocess.run([exe, *cmd[1:]], capture_output=True, text=True)
        if result.returncode != 0:
            print(f"    failed ({result.returncode}): {(result.stderr or result.stdout).strip()[:400]}")
        return result.returncode == 0

    def query(self, *cmd):
        exe = shutil.which(cmd[0]) or cmd[0]
        return subprocess.run([exe, *cmd[1:]], capture_output=True, text=True).stdout

    # ----------------------------------------------------------------- hosts
    def claude_install(self):
        if NAME in self.query("claude", "plugin", "marketplace", "list"):
            self.run("claude", "plugin", "marketplace", "update", NAME)
        else:
            self.run("claude", "plugin", "marketplace", "add", str(ROOT))
        if PLUGIN_ID in self.query("claude", "plugin", "list"):
            self.run("claude", "plugin", "update", PLUGIN_ID)
        else:
            self.run("claude", "plugin", "install", PLUGIN_ID)

    def claude_uninstall(self):
        self.run("claude", "plugin", "uninstall", PLUGIN_ID)
        self.run("claude", "plugin", "marketplace", "remove", NAME)

    def codex_install(self):
        self.install_tree(self.codex_home / "skills" / "effort-routing", skill_files())
        block = (ROOT / "hosts" / "codex" / "AGENTS.block.md").read_text(encoding="utf-8").strip()
        path = self.codex_home / "AGENTS.md"
        self.write_text(path, upsert_block(read(path), block))

    def codex_uninstall(self):
        self.remove_tree(self.codex_home / "skills" / "effort-routing")
        path = self.codex_home / "AGENTS.md"
        if path.exists():
            self.write_text(path, remove_block(read(path)))

    def agy_install(self):
        self.install_tree(self.agy_config / "plugins" / NAME, agy_plugin_files())

    def agy_uninstall(self):
        self.remove_tree(self.agy_config / "plugins" / NAME)

    def grok_install(self):
        # spawn_subagent carries no model or effort, and agent frontmatter
        # effort is ignored (verified on Grok Build 1.0.41): nothing to route.
        self.say("grok: subagent effort cannot be set per spawn — only the session effort applies; skipped")

    def grok_uninstall(self):
        pass

    # ------------------------------------------------------ global defaults
    def reset_effort_defaults(self, hosts):
        """Drop pinned global effort so each CLI falls back to its model's own default."""
        if "claude" in hosts and self.claude_settings.exists():
            self.write_text(self.claude_settings, drop_claude_effort(read(self.claude_settings)))
        codex_config = self.codex_home / "config.toml"
        if "codex" in hosts and codex_config.exists():
            self.write_text(codex_config, drop_toml_key(read(codex_config), None, "model_reasoning_effort"))
        grok_config = self.grok_home / "config.toml"
        if "grok" in hosts and grok_config.exists():
            self.write_text(grok_config, drop_toml_key(read(grok_config), "models", "default_reasoning_effort"))


# ------------------------------------------------------------ file sets
def skill_files():
    skill = ROOT / "skills" / "effort-routing"
    return {p.relative_to(skill).as_posix(): p for p in sorted(skill.rglob("*")) if p.is_file()}


def agy_plugin_files(python=sys.executable, windows=WINDOWS):
    """agy runs hook commands through `sh -c` / `cmd /c` from the plugin directory.

    A launcher with the absolute interpreter path avoids depending on a
    `python3` on PATH (absent on most Windows machines) and on cmd quoting.
    """
    agy = ROOT / "hosts" / "agy"
    hook = agy / "hook.py"
    if windows:
        launcher_name, launcher = "hook.cmd", f'@"{python}" "{hook}"\r\n'
        command = "hook.cmd"
    else:
        # Fall back to python3 on PATH if this interpreter disappears (e.g. a Python upgrade).
        launcher_name = "hook.sh"
        launcher = f'#!/bin/sh\nPY="{python}"\n[ -x "$PY" ] || PY=python3\nexec "$PY" "{hook}"\n'
        command = "sh ./hook.sh"
    hooks = (agy / "hooks.template.json").read_text(encoding="utf-8").replace("{launcher}", command)
    files = {
        "plugin.json": agy / "plugin.json",
        "hooks.json": hooks,
        launcher_name: launcher,
        "rules/AGENTS.md": agy / "rules" / "AGENTS.md",
    }
    files.update({f"skills/effort-routing/{rel}": src for rel, src in skill_files().items()})
    return files


# ------------------------------------------------------------- text helpers
def read(path):
    return path.read_text(encoding="utf-8") if path.exists() else ""


def upsert_block(text, block):
    wrapped = f"{BLOCK_BEGIN}\n{block}\n{BLOCK_END}"
    pattern = re.compile(re.escape(BLOCK_BEGIN) + r".*?" + re.escape(BLOCK_END), re.S)
    if pattern.search(text):
        return pattern.sub(lambda _: wrapped, text)
    return (text.rstrip("\n") + "\n\n" if text.strip() else "") + wrapped + "\n"


def remove_block(text):
    pattern = re.compile(r"\n*" + re.escape(BLOCK_BEGIN) + r".*?" + re.escape(BLOCK_END) + r"\n?", re.S)
    return pattern.sub("\n", text).rstrip("\n") + "\n" if text.strip() else text


def drop_toml_key(text, table, key):
    """Remove `key = ...` from [table] (None = the top level, before any table)."""
    out, current = [], None
    for line in text.splitlines(keepends=True):
        header = re.match(r"\s*\[([^\]]+)\]\s*$", line)
        if header:
            current = header.group(1).strip()
        elif current == table and re.match(rf"\s*{re.escape(key)}\s*=", line):
            continue
        out.append(line)
    return "".join(out)


def drop_claude_effort(text):
    settings = json.loads(text)
    settings.pop("effortLevel", None)
    for per_model in (settings.get("modelSettings") or {}).values():
        if isinstance(per_model, dict):
            per_model.pop("effortLevel", None)
    return json.dumps(settings, ensure_ascii=False, indent=2) + "\n"


# --------------------------------------------------------------------- main
def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", nargs="?", default="install", choices=["install", "uninstall"])
    parser.add_argument("--hosts", help="comma-separated subset of: " + ",".join(HOSTS))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--reset-effort-defaults", action="store_true")
    args = parser.parse_args(argv)

    wanted = args.hosts.split(",") if args.hosts else list(HOSTS)
    unknown = set(wanted) - set(HOSTS)
    if unknown:
        parser.error("unknown hosts: " + ", ".join(sorted(unknown)))
    present = [h for h in wanted if shutil.which(h)]
    for missing in sorted(set(wanted) - set(present)):
        print(f"{missing}: CLI not found, skipped")

    installer = Installer(args.dry_run)
    for host in present:
        print(f"== {host}")
        getattr(installer, f"{host}_{args.action}")()
    if args.action == "install" and args.reset_effort_defaults:
        print("== global effort defaults")
        installer.reset_effort_defaults(present)
    if installer.backup_dir.exists():
        print(f"backups: {installer.backup_dir}")
    if args.action == "install" and not args.dry_run:
        print("done — restart running sessions of the CLIs above to pick up the changes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
