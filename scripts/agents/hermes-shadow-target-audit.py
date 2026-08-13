#!/usr/bin/env python3
"""Validate the credential-free Hermes shadow security contract."""

from __future__ import annotations

import argparse
import json
import stat
import sys
from pathlib import Path
from typing import Any


class AuditError(ValueError):
    """A fail-closed target-policy validation error."""


TOP_LEVEL_KEYS = {
    "schemaVersion",
    "deployment",
    "vm",
    "runtime",
    "sandbox",
    "commonPolicy",
    "profiles",
    "brokers",
    "backup",
}

EXPECTED_PROFILES = {"astra", "dubble", "rigel"}


def require(condition: bool, code: str) -> None:
    if not condition:
        raise AuditError(code)


def read_policy(path: Path) -> dict[str, Any]:
    require(path.is_absolute(), "policy-path-not-absolute")
    require(path.exists(), "policy-missing")
    require(not path.is_symlink(), "policy-symlink")
    mode = path.stat().st_mode
    require(stat.S_ISREG(mode), "policy-not-regular")
    require(not mode & stat.S_IWOTH, "policy-world-writable")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AuditError("policy-unreadable") from exc
    require(isinstance(data, dict), "policy-not-object")
    require(set(data) == TOP_LEVEL_KEYS, "policy-top-level-schema")
    return data


def validate_deployment(data: dict[str, Any]) -> None:
    deployment = data["deployment"]
    require(isinstance(deployment, dict), "deployment-not-object")
    require(deployment.get("mode") == "shadow", "deployment-not-shadow")
    require(deployment.get("targetHost") == "hermes-vm", "target-host")
    require(
        deployment.get("placementRequiresLiveGate") is True,
        "placement-live-gate-disabled",
    )
    require(deployment.get("vmid") is None, "vmid-selected-before-live-gate")
    for key in (
        "productionDeliveryEnabled",
        "productionSchedulerEnabled",
        "dashboardEnabled",
        "apiServerEnabled",
        "externalListenerEnabled",
        "productionRouteEnabled",
        "sourceCleanupEnabled",
        "sourceArchiveEnabled",
        "retiredVmReuseEnabled",
    ):
        require(deployment.get(key) is False, f"unsafe-deployment-{key}")


def validate_vm(data: dict[str, Any]) -> None:
    vm = data["vm"]
    require(isinstance(vm, dict), "vm-not-object")
    require(vm.get("osTrack") == "current-tier1-ubuntu-lts", "vm-os-track")
    require(vm.get("vcpus", 0) >= 4, "vm-cpu-too-small")
    require(vm.get("memoryMiB", 0) >= 8192, "vm-memory-too-small")
    require(vm.get("diskGiB", 0) >= 64, "vm-disk-too-small")
    for key in (
        "nasPassthrough",
        "controllerHomePassthrough",
        "dockerSocketPassthrough",
        "usbPassthrough",
    ):
        require(vm.get(key) is False, f"unsafe-vm-{key}")


def validate_runtime(data: dict[str, Any]) -> None:
    runtime = data["runtime"]
    require(isinstance(runtime, dict), "runtime-not-object")
    require(
        runtime.get("installMethod") == "official-root-git",
        "runtime-install-method",
    )
    require(runtime.get("releaseTrack") == "official-default", "release-track")
    require(
        runtime.get("codeRoot") == "/usr/local/lib/hermes-agent",
        "runtime-code-root",
    )
    require(runtime.get("launcher") == "/usr/local/bin/hermes", "runtime-launcher")
    require(runtime.get("managedScope") == "/etc/hermes", "managed-scope")
    for key in (
        "runtimeSelfUpdateEnabled",
        "runtimeLazyInstallsEnabled",
        "bundledSkillsEnabled",
    ):
        require(runtime.get(key) is False, f"unsafe-runtime-{key}")


def validate_sandbox(data: dict[str, Any]) -> None:
    sandbox = data["sandbox"]
    require(isinstance(sandbox, dict), "sandbox-not-object")
    require(sandbox.get("backend") == "docker", "sandbox-backend")
    require(sandbox.get("binary") == "/usr/bin/podman", "sandbox-binary")
    for key in (
        "rootless",
        "profileScopedContainers",
        "resourceEnforcementRequiresProof",
    ):
        require(sandbox.get(key) is True, f"sandbox-required-{key}")
    for key in (
        "dockerGroup",
        "dockerSocket",
        "localTerminalFallback",
        "mountCwd",
        "networkEnabled",
        "runAsHostUser",
    ):
        require(sandbox.get(key) is False, f"unsafe-sandbox-{key}")
    for key in ("hostVolumes", "forwardEnvironment", "forwardCredentialFiles"):
        require(sandbox.get(key) == [], f"unsafe-sandbox-{key}")


def validate_common_policy(data: dict[str, Any]) -> None:
    policy = data["commonPolicy"]
    require(isinstance(policy, dict), "common-policy-not-object")
    require(policy.get("approvalMode") == "manual", "approval-mode")
    require(policy.get("cronApprovalMode") == "deny", "cron-approval-mode")
    require(policy.get("permanentCommandAllowlist") == [], "command-allowlist")
    for key in (
        "memoryWriteApproval",
        "skillsWriteApproval",
        "agentSkillScan",
        "promptInjectionScan",
        "secretRedaction",
        "ssrfProtection",
        "destructiveSlashConfirmation",
        "mcpReloadConfirmation",
    ):
        require(policy.get(key) is True, f"policy-required-{key}")
    for key in (
        "autoAcceptHooks",
        "allowAllDiscordUsers",
        "sudoers",
        "supplementaryDockerGroup",
    ):
        require(policy.get(key) is False, f"unsafe-policy-{key}")


def validate_profiles(data: dict[str, Any]) -> None:
    profiles = data["profiles"]
    require(isinstance(profiles, list), "profiles-not-list")
    require(len(profiles) == 3, "profile-count")
    require(
        all(isinstance(profile, dict) for profile in profiles), "profile-not-object"
    )
    require(
        {profile.get("name") for profile in profiles} == EXPECTED_PROFILES,
        "profile-set",
    )

    unique_fields = ("serviceUser", "serviceGroup", "home", "unit")
    for field in unique_fields:
        values = [profile.get(field) for profile in profiles]
        require(
            all(isinstance(value, str) and value for value in values),
            f"profile-{field}",
        )
        require(len(values) == len(set(values)), f"profile-duplicate-{field}")

    for profile in profiles:
        name = profile["name"]
        require(profile["serviceUser"] == f"hermes-{name}", f"profile-user-{name}")
        require(profile["serviceGroup"] == f"hermes-{name}", f"profile-group-{name}")
        require(profile["home"] == f"/var/lib/hermes/{name}", f"profile-home-{name}")
        require(
            profile["unit"] == f"hermes-gateway-{name}.service",
            f"profile-unit-{name}",
        )
        require(profile.get("productionTokenPresent") is False, f"profile-token-{name}")
        require(
            profile.get("productionCronDeliveryEnabled") is False,
            f"profile-cron-delivery-{name}",
        )
        require(profile.get("terminalEnabled") is False, f"profile-terminal-{name}")
        required = profile.get("requiredCapabilities")
        forbidden = profile.get("forbiddenCapabilities")
        require(isinstance(required, list) and required, f"profile-required-{name}")
        require(isinstance(forbidden, list) and forbidden, f"profile-forbidden-{name}")
        require(
            set(required).isdisjoint(forbidden), f"profile-capability-conflict-{name}"
        )
        require("sudo" in forbidden, f"profile-sudo-not-forbidden-{name}")
        require("docker-daemon" in forbidden, f"profile-docker-not-forbidden-{name}")

    by_name = {profile["name"]: profile for profile in profiles}
    for name in ("dubble", "rigel"):
        require(
            "terminal" in by_name[name]["forbiddenCapabilities"],
            f"terminal-not-forbidden-{name}",
        )
        require(
            "cross-profile-secrets" in by_name[name]["forbiddenCapabilities"],
            f"cross-profile-not-forbidden-{name}",
        )


def validate_brokers_and_backup(data: dict[str, Any]) -> None:
    brokers = data["brokers"]
    require(isinstance(brokers, dict), "brokers-not-object")
    require(brokers.get("healthInput") == "aggregate-only-read", "health-input")
    require(brokers.get("dockerInput") == "result-only-read", "docker-input")
    require(
        brokers.get("dockerUpdate") == "proposal-and-approved-plan-only",
        "docker-update",
    )
    for key in ("agentCanApprovePlan", "arbitraryCommand", "arbitraryPath"):
        require(brokers.get(key) is False, f"unsafe-broker-{key}")

    backup = data["backup"]
    require(isinstance(backup, dict), "backup-not-object")
    for key in (
        "sqliteSafeHermesBackup",
        "preUpdateFullBackup",
        "encryptedRestic",
        "proxmoxBackup",
        "restoreTestRequired",
        "openclawRollbackPreserved",
    ):
        require(backup.get(key) is True, f"backup-required-{key}")


def validate(path: Path) -> None:
    data = read_policy(path)
    require(data["schemaVersion"] == 1, "schema-version")
    validate_deployment(data)
    validate_vm(data)
    validate_runtime(data)
    validate_sandbox(data)
    validate_common_policy(data)
    validate_profiles(data)
    validate_brokers_and_backup(data)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("policy", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        validate(args.policy.resolve(strict=False))
    except AuditError as exc:
        print(f"status=failed reason={exc}", file=sys.stderr)
        return 1
    print("status=ok schema=1 profiles=3 mode=shadow")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
