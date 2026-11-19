# Standalone secure backend (experimental)

The standalone backend does not execute `distrobox-init` and is not compatible
with `distrobox enter`. Use `distrobox-secure enter NAME [-- COMMAND ...]`.
Legacy Distrobox containers are **not** automatically migrated/recreated.

## Image requirements

* Linux image with `/bin/sh`, `id`, and `sleep`.
* Non-root image user (`Config.User`) and absolute `HOME` in image environment,
  or an explicit per-container profile.
* The resolved image UID:GID must match the invoking rootless host UID:GID
  (`--userns=keep-id`). Images with different ownership are rejected, not chowned.
* No implicit hardware, GUI, session sockets, or `/run/host` mounts.

Optional `~/.config/distrobox-secure/containers/NAME.conf`:

```ini
user=node
home=/home/node
shell=/bin/sh
```

The above is an **example for the OpenCode image**, not a global default.
Other images must specify their own values if image metadata is incomplete.

## Filesystem and XDG

The managed host home at `~/.local/share/distrobox-secure/NAME-home` is
mounted at the resolved image HOME. `XDG_*` directories default beneath HOME.
Explicit grants targeting HOME or its descendants are rejected to avoid
nested bind-mount shadowing. Use external destinations (`/workspace/Source`,
`/mnt/data`, etc.). Host data mounts default to **no SELinux relabel**;
`ro,z` or `rw,z` must be deliberately selected and alter host labels.

For a shared OpenCode database/auth configuration, first test dedicated
external bind mounts and XDG environment settings separately; the backend
**does not yet merge or remap existing OpenCode databases**.

## Workflow

```bash
distrobox-secure create example IMAGE
distrobox-secure enter example -- sh -c 'id; pwd'
distrobox-secure check example
```

## Known limits

* This is a new standalone OCI backend rather than standard Distrobox init.
* `recreate` performs preflight but is not transactional; it can lose the
  container on failed replacement (managed home persists). Back up first.
* The existing automatic updater should be disabled/pinned until it can test
  images and manage rollback, and `localhost/...` images require local rebuild.
* The old embedded Distrobox creator remains in the shell script but is no
  longer called. It can be removed after the pre-existing local capability
  audit fix is committed; this patch intentionally does not edit that block.
