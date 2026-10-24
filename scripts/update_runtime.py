"""Local Runtime maintenance: automatic checks, explicit installs and rollback.

Not an MCP tool. Never takes installation commands or health probes from a
release manifest. Runtime and the Amadeus extension have separate lifecycles.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def health_check(root):
    """Run fixed, isolated imports/schema checks; no host, input or paid API."""
    root = Path(root).resolve()
    with tempfile.TemporaryDirectory(prefix="runtime-update-health-") as directory:
        report = Path(directory) / "health.json"
        from app.runtime_update_schedule import minimal_environment
        environment = minimal_environment()
        try:
            result = subprocess.run([sys.executable, "-I", "-B", "-X", "utf8",
                str(root / "scripts/check_execution_component.py"), "--root", str(root),
                "--report", str(report)], cwd=directory, env=environment,
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
            value = json.loads(report.read_text(encoding="utf-8"))
            return (result.returncode == 0 and value.get("passed") is True
                    and value.get("input_executed") is False and value.get("host_started") is False)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            return False


def _confirm(arguments, digest, description, *, input_fn=input):
    if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise ValueError("no_exact_update_target_available")
    if arguments.confirm_target is not None:
        if arguments.confirm_target != digest:
            raise ValueError("confirmation_does_not_match_exact_target")
        return digest
    if not sys.stdin.isatty():
        raise ValueError("interactive_confirmation_or_exact_--confirm-target_required")
    print(description, file=sys.stderr)
    print("Close all Runtime tasks/servers first. User data and model files stay separate.\n"
          "GitHub HTTPS source and hashes are checked; this release is unsigned.\n"
          "To confirm this exact target, paste its SHA-256, or press Enter to cancel:\n" + digest,
          file=sys.stderr)
    if input_fn().strip() != digest:
        raise ValueError("update_cancelled_no_installation_changes")
    return digest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    commands = parser.add_subparsers(dest="action", required=True)
    check = commands.add_parser("check", help="Check the fixed stable release source; never install")
    check.add_argument("--scheduled", action="store_true", help="Respect opt-out and the daily check interval")
    commands.add_parser("status", help="Show staged update, last check and rollback target")
    commands.add_parser("stage", help="Check again and download/verify the exact release; do not install")
    commands.add_parser("settle", help="Verify original session cleanup and clear only proven-settled registrations")
    for action in ("apply", "recover", "rollback"):
        command = commands.add_parser(action)
        command.add_argument("--confirm-target", help="Explicit confirmation of the exact displayed SHA-256")
    setting = commands.add_parser("settings")
    setting.add_argument("--auto-check", choices=("on", "off"))
    args = parser.parse_args(argv)
    try:
        from app.runtime_update import RuntimeUpdater
        from app.runtime_update_schedule import check_and_cache, cached_check, set_automatic_checks, settings
        updater = RuntimeUpdater(args.root)
        if args.action == "check":
            value = check_and_cache(args.root, scheduled=args.scheduled)
        elif args.action == "settings":
            value = (set_automatic_checks(args.root, args.auto_check == "on")
                     if args.auto_check is not None else settings(args.root))
        elif args.action == "status":
            value = {**updater.status(), "release_check": cached_check(args.root)}
        elif args.action == "stage":
            target = updater.check()
            value = updater.stage(target) if target is not None else {"status": "up_to_date"}
        elif args.action == "settle":
            from app.runtime_lifecycle import InstallationMaintenance
            from app.runtime_task_ledger import assert_settled
            with InstallationMaintenance(args.root):
                value = assert_settled(args.root, clear_settled=True)
        else:
            status = updater.status()
            if args.action == "rollback":
                previous = status.get("rollback_target") or {}
                digest = previous.get("target_digest")
                description = "Roll back Runtime to verified local version " + str(previous.get("version"))
            elif args.action == "recover":
                digest = status.get("pending_target_digest")
                description = "Recover the interrupted update and restore the previous verified files."
            else:
                digest = status.get("target_digest")
                description = "Install staged Runtime " + str(status.get("version"))
            confirmed = _confirm(args, digest, description)
            if args.action == "apply":
                value = updater.apply(confirmed, health_check=health_check)
            elif args.action == "recover":
                value = updater.recover(confirmed)
            else:
                value = updater.rollback(confirmed)
        print(json.dumps(value, ensure_ascii=False, indent=2))
        return 1 if (value.get("status") == "check_failed"
                     or args.action == "apply" and value.get("status") != "applied") else 0
    except Exception as error:
        # Errors remain local; no upload of state/configuration/logs.
        print(json.dumps({"status": "update_refused_or_failed", "error_type": type(error).__name__,
                          "error": str(error), "automatic_install": False}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
