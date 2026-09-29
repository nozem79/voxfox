# For people not using flakes: `nix-build` in the repo root, or
# `nix-env -if .` to install. Flake users should use `flake.nix` instead
# (`nix build .`, `nix run .`) -- this file exists purely for compatibility
# and just calls the same derivation.
{ pkgs ? import <nixpkgs> { } }:

pkgs.callPackage ./packaging/nix/voxfox.nix { }
