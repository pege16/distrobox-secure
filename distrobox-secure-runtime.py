#!/usr/bin/env python3
"""Rootless, non-Distrobox-initialized OCI backend for distrobox-secure.

Requires Linux images with /bin/sh, id and sleep. Image users must map to the
invoking host UID:GID under Podman keep-id. No host integration is implicit.
"""
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys

MARKER = "io.distrobox-secure.backend"
BACKEND = "podman-standalone-v1"
NAME_RE = re.compile(r"[A-Za-z0-9._-]+\Z")
IMAGE_RE = re.compile(r"[A-Za-z0-9_./:@-]+\Z")


def die(message):
    raise SystemExit("[ERROR] secure runtime: " + message)


def run(args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def inspect_container(name):
    result = run(["podman", "inspect", name], capture_output=True, text=True)
    return json.loads(result.stdout)[0]


def read_profile(name):
    path = Path.home() / ".config/distrobox-secure/containers" / f"{name}.conf"
    profile = {}
    if path.exists():
        for lineno, text in enumerate(path.read_text().splitlines(), 1):
            text = text.strip()
            if not text or text.startswith("#"):
                continue
            if "=" not in text:
                die(f"{path}:{lineno}: expected key=value")
            key, value = (x.strip() for x in text.split("=", 1))
            if key not in {"user", "home", "shell"} or not value or key in profile:
                die(f"{path}:{lineno}: unsupported/duplicate/empty profile setting")
            profile[key] = value
    return profile


def image_identity(image, profile):
    data = json.loads(run(["podman", "image", "inspect", image],
                          capture_output=True, text=True).stdout)[0]
    config = data.get("Config") or {}
    env = dict(item.split("=", 1) for item in (config.get("Env") or []) if "=" in item)
    user = profile.get("user") or config.get("User") or ""
    target_home = profile.get("home") or env.get("HOME") or ""
    shell = profile.get("shell") or "/bin/sh"
    if not user or user in ("root", "0", "0:0"):
        die("image uses root/unspecified user; configure a non-root user in a container profile")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]*|[0-9]+(?::[0-9]+)?", user):
        die("invalid profile/image user")
    if not target_home.startswith("/") or target_home == "/" or ".." in PurePosixPath(target_home).parts:
        die("image HOME missing or invalid; specify home=/absolute/path in container profile")
    if not shell.startswith("/") or ".." in PurePosixPath(shell).parts:
        die("invalid absolute shell")
    # Image code is executed only in a throwaway, read-only, networkless container,
    # without host binds or elevated privileges, to resolve symbolic image users.
    probe = ["podman", "run", "--rm", "--network=none", "--read-only",
             "--userns=keep-id", "--cap-drop=all", "--security-opt=no-new-privileges",
             "--user", user, "--entrypoint", "/bin/sh", image,
             "-c", "id -u; id -g"]
    try:
        ids = run(probe, capture_output=True, text=True).stdout.strip().splitlines()
    except subprocess.CalledProcessError as exc:
        die(f"image identity probe failed; requires /bin/sh and id: {exc}")
    if len(ids) != 2 or not all(x.isdecimal() for x in ids):
        die(f"unexpected identity probe output: {ids!r}")
    if (int(ids[0]), int(ids[1])) != (os.getuid(), os.getgid()):
        die(f"image UID:GID {ids[0]}:{ids[1]} != host {os.getuid()}:{os.getgid()}; "
            "keep-id mapping with a writable host-owned HOME requires matching IDs")
    return user, target_home, shell


def within(path, parent):
    return path == parent or parent in path.parents


def grants(name, isolated, target_home):
    path = Path.home() / ".config/distrobox-secure/permissions.conf"
    mounts, network = [], "none"
    for lineno, raw in enumerate(path.read_text().splitlines() if path.exists() else [], 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(":", 2)
        if len(parts) != 3 or parts[0] != name:
            continue
        _, kind, value = parts
        if kind == "network" and value in {"host", "bridge"}:
            network = value
            continue
        if kind not in {"mount", "home_folder"}:
            die(f"permission line {lineno}: unsupported grant {kind}={value}")
        mode = "rw"
        if kind == "home_folder":
            source, target = value, value
        else:
            candidate = value.rsplit(":", 1)
            if len(candidate) == 2 and candidate[1] in {"ro", "rw", "ro,z", "rw,z"}:
                value, mode = candidate
            if ":" not in value:
                die(f"permission line {lineno}: expected source:target")
            source, target = value.rsplit(":", 1)
        if not source.startswith("/") or not target.startswith("/") or ".." in PurePosixPath(target).parts:
            die(f"permission line {lineno}: absolute paths required; traversal forbidden")
        src = Path(source).resolve(strict=True)
        dst = PurePosixPath(target)
        if src == Path("/") or within(Path.home().resolve(), src) or within(src, isolated):
            die(f"permission line {lineno}: forbidden broad/managed source")
        forbidden = (PurePosixPath("/proc"), PurePosixPath("/sys"),
                     PurePosixPath("/dev"), PurePosixPath("/run"), PurePosixPath("/etc"),
                     PurePosixPath("/usr"), PurePosixPath("/var/run"))
        if dst == PurePosixPath("/") or any(dst == p or p in dst.parents for p in forbidden):
            die(f"permission line {lineno}: forbidden destination {dst}")
        # Prevent bind overlays beneath the managed HOME. These caused the
        # original OpenCode host/container inode divergence.
        managed_home = PurePosixPath(target_home)
        if dst == managed_home or within(dst, managed_home) or within(managed_home, dst):
            die(f"permission line {lineno}: destination overlaps managed HOME; use /workspace or /mnt")
        mounts.append((str(src), str(dst), mode))
    for idx, (_, a, _) in enumerate(mounts):
        for _, b, _ in mounts[idx + 1:]:
            pa, pb = PurePosixPath(a), PurePosixPath(b)
            if pa == pb or pa in pb.parents or pb in pa.parents:
                die(f"overlapping explicit mount destinations {a} and {b}")
    return network, mounts


def planned(name, image, isolated):
    if not NAME_RE.fullmatch(name) or not IMAGE_RE.fullmatch(image):
        die("invalid container name or image")
    if os.geteuid() == 0:
        die("rootless Podman required")
    isolated = Path(isolated).resolve(strict=True)
    if not isolated.is_dir() or not within(isolated, Path.home().resolve()):
        die("managed isolated home must be below host HOME")
    user, target_home, shell = image_identity(image, read_profile(name))
    network, mounts = grants(name, isolated, target_home)
    return isolated, user, target_home, shell, network, mounts


def create_or_check(action, name, image, isolated):
    isolated, user, target_home, shell, network, mounts = planned(name, image, isolated)
    if action == "check":
        print(f"[OK] standalone spec checked: user={user}, HOME={target_home}, network={network}")
        for src, dst, mode in mounts:
            print(f"  {src} -> {dst} ({mode})")
        return
    args = ["podman", "create", "--name", name, "--hostname", name,
            "--userns=keep-id", "--user", user, "--network=" + network,
            "--ipc=private", "--pid=private", "--pids-limit=512",
            "--cap-drop=all", "--security-opt=no-new-privileges",
            "--image-volume=ignore", "--tmpfs=/tmp:rw,nosuid,nodev,size=512m",
            "--label", f"{MARKER}={BACKEND}",
            "--label", f"io.distrobox-secure.user={user}",
            "--label", f"io.distrobox-secure.home={target_home}",
            "--label", f"io.distrobox-secure.shell={shell}",
            "--env", f"HOME={target_home}",
            "--env", f"XDG_CONFIG_HOME={target_home}/.config",
            "--env", f"XDG_DATA_HOME={target_home}/.local/share",
            "--env", f"XDG_CACHE_HOME={target_home}/.cache",
            "--env", f"XDG_STATE_HOME={target_home}/.local/state",
            "--volume", f"{isolated}:{target_home}:rw,Z"]
    for src, dst, mode in mounts:
        args += ["--volume", f"{src}:{dst}:{mode}"]
    # A fixed, minimal supervisor; no Distrobox host integration or privileged mounts.
    args += ["--entrypoint", "/bin/sh", image, "-c", "exec sleep 2147483647"]
    run(args)
    try:
        info = inspect_container(name)
        config = info.get("HostConfig") or {}
        real = {(str(Path(m["Source"]).resolve()), m["Destination"])
                for m in (info.get("Mounts") or []) if m.get("Type") == "bind"}
        expected = {(str(isolated), target_home)} | {(src, dst) for src, dst, _ in mounts}
        unsafe = (real != expected or config.get("Privileged") or
                  not any("no-new-privileges" in str(opt) for opt in (config.get("SecurityOpt") or [])) or
                  info.get("EffectiveCaps") not in ([], None) or
                  info.get("BoundingCaps") not in ([], None) or
                  (Path("/sys/fs/selinux/enforce").exists() and
                   Path("/sys/fs/selinux/enforce").read_text().strip() == "1" and
                   not info.get("ProcessLabel")) or
                  (info.get("Config") or {}).get("Labels", {}).get(MARKER) != BACKEND)
        if unsafe:
            die(f"unsafe created container configuration; mounts missing={expected-real}, extra={real-expected}")
    except BaseException:
        subprocess.run(["podman", "rm", "-f", name], check=False)
        raise
    print("[OK] standalone OCI audit passed; enter with distrobox-secure enter", name)


def managed(name):
    if not NAME_RE.fullmatch(name):
        die("invalid container name")
    labels = (inspect_container(name).get("Config") or {}).get("Labels") or {}
    if labels.get(MARKER) != BACKEND:
        die("legacy/unmanaged container; explicit migration required before recreate")


def enter(name, command):
    if not NAME_RE.fullmatch(name):
        die("invalid container name")
    info = inspect_container(name)
    labels = (info.get("Config") or {}).get("Labels") or {}
    if labels.get(MARKER) != BACKEND:
        die("not a standalone distrobox-secure container; refusing unmanaged entry")
    user, target_home, shell = (labels.get("io.distrobox-secure." + key) for key in ("user", "home", "shell"))
    if not user or not target_home or not shell:
        die("missing validated container identity metadata")
    if info.get("State", {}).get("Status") != "running":
        run(["podman", "start", name])
    args = ["podman", "exec"]
    if sys.stdin.isatty():
        args.append("-i")
    if sys.stdin.isatty() and sys.stdout.isatty():
        args.append("-t")
    args += ["--user", user, "--workdir", target_home, name] + (command or [shell])
    raise SystemExit(subprocess.call(args))


def main():
    if len(sys.argv) < 3:
        die("usage: backend.py create|check NAME IMAGE ISOLATED_HOME | enter NAME [-- COMMAND...]")
    action, name = sys.argv[1:3]
    if action == "managed" and len(sys.argv) == 3:
        managed(name)
    elif action == "enter":
        extra = sys.argv[3:]
        enter(name, extra[1:] if extra[:1] == ["--"] else extra)
    elif action in {"create", "check"} and len(sys.argv) == 5:
        create_or_check(action, name, sys.argv[3], sys.argv[4])
    else:
        die("invalid action or arguments")


if __name__ == "__main__":
    main()
