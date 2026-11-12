{
  description = "Local Charybdis ZMK Bluetooth/USB development environment";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";
    zephyr-nix.url = "github:nix-community/zephyr-nix/5ef0903c5fcdbbce55af2732fad1011e90b6ff47";
    zephyr-nix.inputs.nixpkgs.follows = "nixpkgs";
  };

  outputs =
    { nixpkgs, zephyr-nix, ... }:
    let
      system = "x86_64-linux";
      pkgs = nixpkgs.legacyPackages.${system};
      # ZMK 0.3 uses Zephyr 3.5. Keep SDK 0.16 rather than the latest SDK.
      sdk = zephyr-nix.packages.${system}.sdk-0_16.override {
        targets = [ "arm-zephyr-eabi" ];
      };
      # Only Zephyr's requirements-base.txt, not documentation/test tooling.
      python = pkgs.python3.withPackages (ps: [
        ps.west
        ps.pyelftools
        ps.pyyaml
        ps.pykwalify
        ps.canopen
        ps.packaging
        ps.progress
        ps.psutil
        ps.pylink-square
        ps.pyserial
        ps.requests
        ps.anytree
        ps.intelhex
        # ZMK Studio's nanopb generator needs both this module and protoc below.
        ps.protobuf
        # The pinned nanopb loader still imports pkg_resources.
        ps.setuptools
      ]);
      build = pkgs.writeShellScriptBin "zmk-build" ''
        exec ${python}/bin/python3 -I ${./scripts/build.py} --repo "$PWD" "$@"
      '';
      flash = pkgs.writeShellApplication {
        name = "zmk-flash";
        runtimeInputs = [
          pkgs.udisks
          pkgs.util-linux
        ];
        text = ''
          exec ${pkgs.python3}/bin/python3 -I ${./scripts/flash.py} "$@"
        '';
      };
      clean = pkgs.writeShellScriptBin "zmk-clean" ''
        exec ${python}/bin/python3 -I ${./scripts/clean.py} --repo "$PWD" "$@"
      '';
    in
    {
      # Exercise source contracts and failure handling without downloading West
      # projects or accessing devices. Full firmware builds stay an explicit step.
      checks.${system}.keyboard =
        pkgs.runCommand "charybdis-keyboard-tests"
          {
            nativeBuildInputs = [
              python
              pkgs.gcc
            ];
            src = ./.;
          }
          ''
            python3 -I "$src/scripts/test_keymaps.py"
            python3 -I "$src/scripts/test_build.py"
            python3 -I "$src/scripts/test_flash.py"
            python3 -I "$src/scripts/test_clean.py"
            python3 -I "$src/scripts/test_manifest.py"
            python3 -I "$src/scripts/test_usb_host.py"
            python3 -I "$src/scripts/test_usb_firmware.py"
            touch "$out"
          '';

      # A desktop user can run only the flasher without loading the compiler SDK.
      apps.${system}.flash = {
        type = "app";
        program = "${flash}/bin/zmk-flash";
      };

      devShells.${system}.default = pkgs.mkShell {
        packages = [
          sdk
          python
          pkgs.cmake
          pkgs.ninja
          pkgs.dtc
          pkgs.protobuf
          pkgs.git
          pkgs.gcc
          pkgs.nixfmt
          build
          flash
          clean
        ];
        ZEPHYR_TOOLCHAIN_VARIANT = "zephyr";
      };
    };
}
