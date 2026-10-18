{
  description = "VoxFox — screen reader, dictation, and OCR tool (offline, GTK4)";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachSystem [ "x86_64-linux" "aarch64-linux" ] (system:
      let
        pkgs = import nixpkgs { inherit system; };
      in
      {
        packages = rec {
          voxfox = pkgs.callPackage ./packaging/nix/voxfox.nix { };
          default = voxfox;
        };

        apps = rec {
          voxfox = flake-utils.lib.mkApp { drv = self.packages.${system}.voxfox; };
          default = voxfox;
        };

        # `nix develop` for hacking on VoxFox itself: the same pytest/ruff
        # setup described in README.md's "For developers" section, plus a
        # GTK4/PyGObject environment so voxfox_ui imports too. This does
        # NOT need `nix build` to have succeeded first -- it is independent
        # of the `voxfox` package output above.
        devShells.default = pkgs.mkShell {
          packages = [
            (pkgs.python3.withPackages (ps: with ps; [
              pygobject3
              pyatspi
              numpy
              pillow
              pytesseract
              pytest
            ]))
            pkgs.ruff # standalone binary in nixpkgs, not part of a Python set
            pkgs.gtk4
            pkgs.at-spi2-core
            pkgs.wmctrl
            pkgs.xdotool
            pkgs.maim
            pkgs.tesseract
            pkgs.poppler-utils
          ];
        };
      });
}
