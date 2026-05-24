#!/usr/bin/env python3
"""Render fireproof.nft.jinja profiles to nftables rulesets."""

from __future__ import annotations

import argparse
import copy
import sys
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = ROOT / "templates"
TEMPLATE_NAME = "fireproof.nft.jinja"
PROFILES_DIR = ROOT / "profiles"
DEFAULTS_FILE = PROFILES_DIR / "_defaults.yaml"
OUTPUT_DIR = ROOT / "generated"
SKIP_PROFILES = {"schema", "_defaults"}


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a YAML mapping at top level")
    return data


def normalize_network(data: dict[str, Any]) -> None:
    network = data.setdefault("network", {})
    if "lan_cidr" in network:
        cidrs = network.setdefault("lan_cidrs", [])
        if network["lan_cidr"] not in cidrs:
            cidrs.insert(0, network["lan_cidr"])
    if not network.get("lan_cidrs"):
        raise ValueError("network.lan_cidrs (or network.lan_cidr) is required")


def load_defaults() -> dict[str, Any]:
    if not DEFAULTS_FILE.is_file():
        return {}
    return load_yaml(DEFAULTS_FILE)


def load_profile(path: Path) -> dict[str, Any]:
    profile = load_yaml(path)
    if "profile" not in profile:
        raise ValueError(f"{path}: missing required 'profile' section")
    data = deep_merge(load_defaults(), profile)
    normalize_network(data)
    return data


def render_profile(profile_data: dict[str, Any], env: Environment) -> str:
    template = env.get_template(TEMPLATE_NAME)
    return template.render(**profile_data)


def profile_paths(name: str | None) -> list[Path]:
    if name:
        path = PROFILES_DIR / f"{name}.yaml"
        if not path.is_file():
            raise FileNotFoundError(f"profile not found: {name} (expected {path})")
        return [path]
    return sorted(
        p for p in PROFILES_DIR.glob("*.yaml") if p.stem not in SKIP_PROFILES
    )


def write_output(name: str, content: str, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"{name}.nft"
    dest.write_text(content, encoding="utf-8")
    return dest


def init_profile(
    name: str,
    *,
    wan: str | None,
    vpn: str | None,
    lan: str | None,
    description: str | None,
) -> Path:
    dest = PROFILES_DIR / f"{name}.yaml"
    if dest.exists():
        raise FileExistsError(f"profile already exists: {dest}")

    body: dict[str, Any] = {
        "profile": {
            "name": name,
            "description": description or f"Custom profile — {name}",
        },
        "interfaces": {"wan": wan or "eth0"},
    }
    if vpn:
        body["interfaces"]["vpn"] = vpn
    if lan:
        body["network"] = {"lan_cidr": lan}

    dest.write_text(
        "# Only overrides — merged with profiles/_defaults.yaml\n"
        + yaml.safe_dump(body, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return dest


def build_init_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create a new profile scaffold")
    parser.add_argument("name", help="profile file name (without .yaml)")
    parser.add_argument("--wan", help="WAN interface, e.g. enp3s0")
    parser.add_argument("--vpn", help="VPN interface, e.g. proton0")
    parser.add_argument("--lan", help="LAN CIDR, e.g. 192.168.1.0/24")
    parser.add_argument("--desc", help="profile description")
    return parser


def build_render_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate nftables configs from Jinja2 profiles",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  %(prog)s default                 render one profile → generated/
  %(prog)s --all                   render every profile
  %(prog)s default --print         preview on stdout
  %(prog)s init mybox --wan enp3s0 scaffold a new profile
  %(prog)s --list                  show available profiles
""".strip(),
    )
    parser.add_argument("profile", nargs="?", help="profile name (without .yaml)")
    parser.add_argument("-a", "--all", action="store_true", help="render all profiles")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=OUTPUT_DIR,
        help=f"output directory (default: {OUTPUT_DIR})",
    )
    parser.add_argument(
        "-p",
        "--print",
        action="store_true",
        dest="print_stdout",
        help="print to stdout instead of writing files",
    )
    parser.add_argument("-l", "--list", action="store_true", help="list profiles")
    return parser


def list_profiles() -> None:
    paths = profile_paths(None)
    if not paths:
        print("No profiles found.", file=sys.stderr)
        return
    print(f"{'PROFILE':<14} DESCRIPTION")
    print("-" * 60)
    for path in paths:
        data = load_profile(path)
        name = data["profile"].get("name", path.stem)
        desc = data["profile"].get("description", "")
        print(f"{path.stem:<14} {desc}")


def run_init(argv: list[str]) -> int:
    args = build_init_parser().parse_args(argv)
    try:
        dest = init_profile(
            args.name,
            wan=args.wan,
            vpn=args.vpn,
            lan=args.lan,
            description=args.desc,
        )
    except FileExistsError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"created {dest}")
    print(f"edit it, then: python3 scripts/render.py {args.name}")
    return 0


def run_render(argv: list[str]) -> int:
    args = build_render_parser().parse_args(argv)

    if args.list:
        list_profiles()
        return 0

    if args.all:
        paths = profile_paths(None)
    elif args.profile:
        paths = profile_paths(args.profile)
    else:
        build_render_parser().print_help()
        return 2

    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )

    for path in paths:
        data = load_profile(path)
        name = data["profile"].get("name", path.stem)
        rendered = render_profile(data, env)

        if args.print_stdout:
            if len(paths) > 1:
                print(f"# --- {name} ---")
            print(rendered.rstrip())
            print()
        else:
            dest = write_output(name, rendered, args.output)
            print(f"generated {dest}")

    return 0


def main() -> int:
    argv = sys.argv[1:]
    if argv and argv[0] == "init":
        return run_init(argv[1:])
    return run_render(argv)


if __name__ == "__main__":
    raise SystemExit(main())
