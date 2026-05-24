# awesome-nftable-conf

**Fireproof nftables for Linux** — kill-switch, Tor HTTP/HTTPS redirect, VPN WAN bootstrap (ProtonVPN and similar), Tailscale, Docker bridges. One Jinja2 template, many YAML profiles.

Write a small profile, run one command, get a ruleset you can load with `nft -f`.

---

## What you get

| Layer | Purpose |
|-------|---------|
| **Kill-switch** | `output` policy `drop` — traffic stops if VPN/Tor path dies |
| **WAN bootstrap** | Allows `ct state new,established` on WAN so VPN can connect first |
| **Tor proxy chain** | Marks web traffic → NAT redirect to local Tor SOCKS |
| **`proxy_mark`** | Mangle hook; keeps DNS out of the redirect path |
| **Input hardening** | Default drop; LAN + Tailscale + ICMP only |

### Traffic flow (Proton over Tor profile)

```
App → HTTP/HTTPS
  → proxy_mark sets mark 0x1
  → NAT redirect → Tor SOCKS (:9050)
  → mark 0x2 allowed through kill-switch
  → exits via VPN interface (proton0)

VPN connect (bootstrap)
  → new flows allowed on WAN (enp3s0) until tunnel is up
  → then normal traffic uses proton0
```

---

## Quick start (3 steps)

**1. Install generator deps**

```bash
make deps
# or: pip install -r requirements.txt
```

**2. Create or pick a profile**

```bash
make list

# scaffold a new one — only set what differs from defaults
make init NAME=mybox WAN=enp3s0 VPN=proton0 LAN=192.168.1.0/24
# → profiles/mybox.yaml (merged with profiles/_defaults.yaml)
```

**3. Generate and apply**

```bash
make render PROFILE=mybox
make check PROFILE=mybox          # optional: nft -c syntax check
sudo make apply PROFILE=mybox     # load into running nftables

# or install to /etc for boot persistence
sudo make install PROFILE=mybox NFT_DEST=/etc/nftables/fireproof.nft
```

**One-liner preview** (no files written):

```bash
./bin/fireproof default --print
python3 scripts/render.py default --print
```

---

## How profiles work

Every profile in `profiles/*.yaml` is **deep-merged** with `profiles/_defaults.yaml`. You only override what your machine needs:

```yaml
# profiles/mybox.yaml — minimal real-world profile
profile:
  name: mybox
  description: "Desktop"

interfaces:
  wan: enp3s0

network:
  lan_cidr: "192.168.1.0/24"
```

Everything else (Tor marks, kill-switch, feature flags, Docker bridges) comes from defaults.

| Profile | Overrides | Use case |
|---------|-----------|----------|
| `default` | WAN + LAN | Home — Proton over Tor, Tailscale, Docker |
| `laptop` | Wi-Fi WAN, no bridges | Portable machine |
| `minimal` | No VPN/Tailscale | Tor redirect + kill-switch only |
| `server` | No Tor, no LAN access | Headless VPN + Tailscale admin |

---

## Configuration reference

Full key list: `profiles/schema.yaml`. Common options:

### Interfaces & network

| Key | Example | Notes |
|-----|---------|-------|
| `interfaces.wan` | `enp3s0` | Physical uplink — **required** |
| `interfaces.vpn` | `proton0` | ProtonVPN / WireGuard tunnel |
| `interfaces.tailscale` | `tailscale0` | Tailscale interface |
| `network.lan_cidr` | `192.168.1.0/24` | Single LAN shorthand |
| `network.lan_cidrs` | list | Multiple LAN subnets |

Find your WAN: `ip -br link` or `ip route show default`

### Tor & proxy

| Key | Default | Notes |
|-----|---------|-------|
| `tor.socks_port` | `9050` | Tor TransPort/SOCKS listen port |
| `redirect_ports` | `[80, 443]` | Ports redirected to Tor |
| `marks.proxy` | `0x1` | Mark for redirect |
| `marks.tor` | `0x2` | Mark for Tor connections |
| `proxy.mark_new_only_ports` | `[443]` | Only mark *new* flows (avoids TLS re-mark noise) |

### Feature flags

| Flag | Default | When to disable |
|------|---------|-----------------|
| `killswitch` | `true` | Debugging only — **leaks traffic** |
| `proton_wan_bootstrap` | `true` | Static VPN or no VPN |
| `tor_proxy` | `true` | Server/admin hosts (`server` profile) |
| `vpn` | `true` | Tor-only setup (`minimal`) |
| `tailscale` | `true` | No mesh VPN |
| `docker_forward` | `true` | No containers/VMs |
| `block_ipv6` | `false` | Set `true` to drop all IPv6 egress |
| `lan_input` / `lan_output` | `true` | Lock down LAN access on servers |

### Extra rules (escape hatch)

Append raw nftables lines without editing the template:

```yaml
output_extra:
  - 'udp dport 53 ip daddr 192.168.1.1 accept'   # DNS via router
  - 'udp dport 123 accept'                        # NTP

input_extra:
  - 'tcp dport 22 ip saddr 192.168.1.0/24 accept' # SSH from LAN
```

More copy-paste examples: `examples/snippets.yaml`

---

## CLI reference

```bash
./bin/fireproof --list
./bin/fireproof default                    # → generated/default.nft
./bin/fireproof --all                      # → generated/*.nft
./bin/fireproof default --print            # stdout preview
./bin/fireproof default -o /tmp/out        # custom output dir
./bin/fireproof init mybox --wan enp3s0 --vpn proton0 --lan 192.168.1.0/24
```

Makefile shortcuts: `make list`, `make render`, `make render-all`, `make init`, `make check`, `make apply`, `make install`

---

## Boot persistence (systemd)

```bash
make render PROFILE=default
sudo make install PROFILE=default NFT_DEST=/etc/nftables/fireproof.nft
sudo cp examples/nftables.service /etc/systemd/system/nftables-fireproof.service
# edit ExecStart path if needed
sudo systemctl enable --now nftables-fireproof.service
```

---

## Validate before apply

```bash
make check PROFILE=default
nft -c -f generated/default.nft
```

Always keep a console session open when testing kill-switch rules — a bad ruleset can lock you out.

---

## Repository layout

```
profiles/
  _defaults.yaml      shared defaults (merged into every profile)
  *.yaml              one file per host / role
  schema.yaml         key reference (not rendered)

templates/
  fireproof.nft.jinja Jinja2 source — {{ variables }} and {% feature flags %}

scripts/render.py     generator
bin/fireproof         CLI wrapper
examples/             systemd unit + rule snippets
generated/            output .nft files (gitignored)
```

---

## Requirements on the host

- Python 3.10+ (generator only — not needed on target if you copy `generated/*.nft`)
- [`nftables`](https://wiki.nftables.org/) (`nft`) on the Linux host
- **Tor** listening on `tor.socks_port` when `tor_proxy: true`
- **VPN client** creating `interfaces.vpn` when `features.vpn: true`

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| VPN won't connect | Kill-switch blocks WAN | Ensure `proton_wan_bootstrap: true` |
| No web at all | Tor not running | Start Tor; check port `9050` |
| LAN unreachable | Wrong CIDR | Fix `network.lan_cidr` |
| Docker broken | Bridges missing | Add interface to `bridge_interfaces` |
| Locked out of SSH | `input_drop` + no LAN rule | Use console; add `input_extra` for SSH |
| `nft -c` netlink error | Permission / container | Run on host with appropriate caps |

---

## What you can extend next

This repo is a **base layer** — the template and `*_extra` hooks are meant to grow. Ideas that fit the current design:

### Near-term (profile YAML only)

- **DNS leak protection** — allow DNS only to your router or a trusted resolver via `output_extra`
- **NTP / mDNS / local discovery** — targeted `output_extra` / `input_extra` rules
- **IPv6 full lockdown** — `features.block_ipv6: true` (already supported)
- **Multiple LANs / VLANs** — `network.lan_cidrs` list
- **Extra Tor ports** — add to `redirect_ports` (8080, 8443, …)
- **Per-host allowlists** — `output_extra` for update servers, package mirrors

### Template additions (contributions welcome)

- **DNS chain** — optional dedicated `chain dns` instead of raw extras
- **WireGuard / OpenVPN variants** — different bootstrap patterns per VPN type
- **Inbound DNAT** — port forwards with kill-switch-safe defaults
- **Rate limiting** — `limit rate` on input for SSH
- **Set-based blocklists** — `set blocked_ips { … }` fed from external lists
- **Separate `table ip6`** — granular IPv6 policy vs. blanket drop
- **Mark-based split routing** — integrate with `ip rule` / policy routing docs
- **TransPort vs SOCKS** — support Tor TransPort redirect target separately from SOCKS

### Tooling & ops

- **CI render check** — GitHub Action: render all profiles on push
- **Pre-commit hook** — auto-render and `nft -c` before commit
- **Ansible / cloud-init role** — deploy profile + systemd unit to fleet
- **Profile validation** — JSON Schema for YAML profiles
- **Diff command** — show effective config after defaults merge

### Advanced networking stacks

- **ProtonVPN + Tor + obfs4** — document bridge bootstrap in `output_extra`
- **Network namespaces** — per-container policies alongside bridge rules
- **Fail-closed watchdog** — systemd path unit re-applies rules if flushed
- **Integration with `iptables-nft` legacy** — migration notes from iptables

If you add a feature, prefer a **feature flag** in `_defaults.yaml` plus a block in `fireproof.nft.jinja` — keeps one template, many profiles.

---

## Contributing

1. Fork → create `profiles/yourhost.yaml` (overrides only)
2. `make render-all && make check`
3. Open a PR with profile + any template/defaults changes

---

## License

MIT — see [LICENSE](LICENSE).
