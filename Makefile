.PHONY: help list init render render-all deps check apply install deploy clean

PROFILE ?= default
PYTHON ?= python3
RENDER := $(PYTHON) scripts/render.py
NFT_DEST ?= /etc/nftables/fireproof.nft

help:
	@echo "awesome-nftable-conf"
	@echo ""
	@echo "  make deps         install Python deps (PyYAML, Jinja2)"
	@echo "  make list         list available profiles"
	@echo "  make init NAME=x  scaffold profiles/x.yaml (WAN=$(WAN))"
	@echo "  make render       render PROFILE=$(PROFILE)"
	@echo "  make render-all   render every profile → generated/"
	@echo "  make check        render + nft -c syntax check"
	@echo "  make apply        render and load into running nftables (sudo)"
	@echo "  make install      render + copy to $(NFT_DEST) (sudo)"
	@echo "  make clean        remove generated/"

deps:
	$(PYTHON) -m pip install --user -r requirements.txt 2>/dev/null || \
	$(PYTHON) -m pip install -r requirements.txt

list: deps
	$(RENDER) --list

init: deps
	@test -n "$(NAME)" || (echo "Usage: make init NAME=mybox WAN=enp3s0"; exit 1)
	$(RENDER) init $(NAME) $(if $(WAN),--wan $(WAN),) $(if $(VPN),--vpn $(VPN),) $(if $(LAN),--lan $(LAN),) $(if $(DESC),--desc "$(DESC)",)

render: deps
	$(RENDER) $(PROFILE)

render-all: deps
	$(RENDER) --all

check: render
	@command -v nft >/dev/null || { echo "nft not installed; skipping syntax check"; exit 0; }
	nft -c -f generated/$(PROFILE).nft && echo "syntax OK: generated/$(PROFILE).nft"

apply: render
	sudo nft -f generated/$(PROFILE).nft

install: render
	sudo install -Dm644 generated/$(PROFILE).nft $(NFT_DEST)
	@echo "installed $(NFT_DEST) — enable examples/nftables.service or run: sudo nft -f $(NFT_DEST)"

clean:
	rm -rf generated
