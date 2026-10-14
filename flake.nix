{
  description = "Miles Morales memory bench: instrumented vkd3d-proton + static RE of MilesMorales.exe";

  # Same nixpkgs rev as ~/Projects/dotfiles, so most of the closure is shared.
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/d6524aaca2ff07876657ae2b323f24be4874944b";

  outputs =
    { nixpkgs, ... }:
    let
      system = "x86_64-linux";
      pkgs = import nixpkgs { inherit system; };
      mingw = pkgs.pkgsCross.mingwW64;

      # vkd3d-proton's build-win64.txt plus a library path for winpthreads: meson's
      # dependency('threads') adds -pthread, and nixpkgs' mingw gcc (mcf thread model)
      # doesn't ship a libpthread.a of its own.
      crossFile = pkgs.writeText "cross-win64.txt" ''
        [binaries]
        c = 'x86_64-w64-mingw32-gcc'
        cpp = 'x86_64-w64-mingw32-g++'
        ar = 'x86_64-w64-mingw32-ar'
        strip = 'x86_64-w64-mingw32-strip'

        [built-in options]
        c_link_args = ['-L${mingw.windows.pthreads}/lib']
        cpp_link_args = ['-L${mingw.windows.pthreads}/lib']

        [properties]
        needs_exe_wrapper = true

        [host_machine]
        system = 'windows'
        cpu_family = 'x86_64'
        cpu = 'x86_64'
        endian = 'little'
      '';
    in
    {
      devShells.${system}.default = pkgs.mkShell {
        MILES_CROSS_FILE = crossFile;

        packages = [
          # vkd3d-proton cross build (d3d12.dll / d3d12core.dll for Proton)
          mingw.buildPackages.gcc
          pkgs.meson
          pkgs.ninja
          pkgs.glslang
          pkgs.wine # widl, same as nixpkgs' own vkd3d-proton package

          # static RE of the game binary
          pkgs.ghidra
          (pkgs.python3.withPackages (ps: [
            ps.pefile
            ps.capstone
            ps.numpy
            ps.pillow
          ]))
        ];
      };
    };
}
