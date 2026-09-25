#!/usr/bin/env python3
"""Install effort-router into every supported AI CLI found on this machine.

  python3 install.py                          install or update (idempotent)
  python3 install.py --reset-effort-defaults  also drop the global effort defaults
  python3 install.py --dry-run                show what would change, change nothing
  python3 install.py --hosts claude,codex     limit to some hosts
  python3 install.py uninstall                remove everything installed

Nothing outside the files listed below is touched; every edited config is
backed up to ~/.local/state/effort-router/backups/<timestamp>/ first.
"""

import argparse
import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HOME = Path.home()
NAME = "effort-router"
PLUGIN_ID = f"{NAME}@{NAME}"
BLOCK_BEGIN = f"<!-- {NAME}:begin -->"
BLOCK_END = f"<!-- {NAME}:end -->"
STATE = Path(os.environ.get("XDG_STATE_HOME") or HOME / ".local" / "state") / NAME

CODEX_HOME = Path(os.environ.get("CODEX_HOME") or HOME / ".codex")
AGY_CONFIG = HOME / ".gemini" / "config"
GROK_HOME = HOME / ".grok"
CLAUDE_SETTINGS = HOME / ".claude" / "settings.json"


class Installer:
    def __init__(self, dry_run):
        self.dry_run = dry_run
        self.backup_dir = STATE / "backups" / time.strftime("%Y%m%d-%H%M%S")

    # ------------------------------------------------------------ primitives
    def say(self, message):
        print(("[dry-run] " if self.dry_run else "") + message)

    def backup(self, path):
        if self.dry_run or not path.exists():
            return
        target = self.backup_dir / str(path).lstrip("/")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)

    def write_text(self, path, new):
        old = path.read_text(encoding="utf-8") if path.exists() else ""
        if old == new:
            return False
        diff = difflib.unified_diff(old.splitlines(), new.splitlines(), str(path), str(path), lineterm="", n=1)
        self.say(f"edit {path}\n" + "\n".join(f"    {line}" for line in list(diff)[2:]))
        if not self.dry_run:
            self.backup(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(new, encoding="utf-8")
        return True

    def symlink(self, link, target):
        if link.is_symlink() and Path(os.readlink(link)) == target:
            return
        if link.exists() or link.is_symlink():
            if not (link.is_symlink() and NAME in os.readlink(link)):
                self.say(f"SKIP {link}: exists and is not ours — remove it by hand to install")
                return
        self.say(f"link {link} -> {target}")
        if not self.dry_run:
            link.parent.mkdir(parents=True, exist_ok=True)
            if link.is_symlink():
                link.unlink()
            link.symlink_to(target, target_is_directory=True)

    def unlink(self, link):
        if link.is_symlink() and NAME in os.readlink(link):
            self.say(f"remove {link}")
            if not self.dry_run:
                link.unlink()

    def run(self, *cmd):
        self.say("run " + " ".join(cmd))
        if self.dry_run:
            return True
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"    failed ({result.returncode}): {(result.stderr or result.stdout).strip()[:400]}")
        return result.returncode == 0

    # ----------------------------------------------------------------- hosts
    def claude_install(self):
        listed = subprocess.run(["claude", "plugin", "marketplace", "list"], capture_output=True, text=True).stdout
        if NAME in listed:
            self.run("claude", "plugin", "marketplace", "update", NAME)
        else:
            self.run("claude", "plugin", "marketplace", "add", str(ROOT))
        installed = subprocess.run(["claude", "plugin", "list"], capture_output=True, text=True).stdout
        if PLUGIN_ID in installed or f"{NAME}@" in installed:
            self.run("claude", "plugin", "update", PLUGIN_ID)
        else:
            self.run("claude", "plugin", "install", PLUGIN_ID)

    def claude_uninstall(self):
        self.run("claude", "plugin", "uninstall", PLUGIN_ID)
        self.run("claude", "plugin", "marketplace", "remove", NAME)

    def codex_install(self):
        self.symlink(CODEX_HOME / "skills" / "effort-routing", ROOT / "skills" / "effort-routing")
        block = (ROOT / "hosts" / "codex" / "AGENTS.block.md").read_text(encoding="utf-8").strip()
        self.write_text(CODEX_HOME / "AGENTS.md", upsert_block(read(CODEX_HOME / "AGENTS.md"), block))

    def codex_uninstall(self):
        self.unlink(CODEX_HOME / "skills" / "effort-routing")
        path = CODEX_HOME / "AGENTS.md"
        if path.exists():
            self.write_text(path, remove_block(read(path)))

    def agy_install(self):
        # The plugin directory carries hooks.json, rules/ and skills/ itself.
        self.symlink(AGY_CONFIG / "plugins" / NAME, ROOT / "hosts" / "agy")

    def agy_uninstall(self):
        self.unlink(AGY_CONFIG / "plugins" / NAME)

    def grok_install(self):
        # spawn_subagent carries no model or effort, and agent frontmatter
        # effort is ignored (verified on Grok Build 1.0.41): nothing to route.
        self.say("grok: subagent effort cannot be set per spawn — only the session effort applies; skipped")

    def grok_uninstall(self):
        pass

    # ------------------------------------------------------ global defaults
    def reset_effort_defaults(self, hosts):
        """Drop pinned global effort so each CLI falls back to its model's own default."""
        if "claude" in hosts and CLAUDE_SETTINGS.exists():
            self.write_text(CLAUDE_SETTINGS, drop_claude_effort(read(CLAUDE_SETTINGS)))
        if "codex" in hosts and (CODEX_HOME / "config.toml").exists():
            path = CODEX_HOME / "config.toml"
            self.write_text(path, drop_toml_key(read(path), None, "model_reasoning_effort"))
        if "grok" in hosts and (GROK_HOME / "config.toml").exists():
            path = GROK_HOME / "config.toml"
            self.write_text(path, drop_toml_key(read(path), "models", "default_reasoning_effort"))


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
HOSTS = {"claude": "claude", "codex": "codex", "agy": "agy", "grok": "grok"}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", nargs="?", default="install", choices=["install", "uninstall"])
    parser.add_argument("--hosts", help="comma-separated subset of: " + ",".join(HOSTS))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--reset-effort-defaults", action="store_true")
    args = parser.parse_args()

    wanted = args.hosts.split(",") if args.hosts else list(HOSTS)
    unknown = set(wanted) - set(HOSTS)
    if unknown:
        parser.error("unknown hosts: " + ", ".join(sorted(unknown)))
    present = [h for h in wanted if shutil.which(HOSTS[h])]
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


if __name__ == "__main__":
    sys.exit(main())
