#!/usr/bin/env python3

import argparse
import glob
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile
import textwrap


CMAKE_SRC = Path(__file__).parent.parent
TOP = CMAKE_SRC.parent.parent

sys.path.append(str(TOP / 'toolchain/ndk-kokoro'))
from build_utils import Host, get_default_host, run_cmd, zip_dir_to_zip


def parse_arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument('src')
    parser.add_argument('out_dir')
    parser.add_argument('dest_dir')
    parser.add_argument('build_id')
    parser.add_argument('--cmake',
                        default='cmake',
                        help='Path to cmake binary.')
    parser.add_argument('--ninja',
                        default='ninja',
                        help='Path to ninja binary.')
    parser.add_argument('--android-cmake',
                        help='Path to android-cmake repository.')
    parser.add_argument('--extra-notices',
                        default='',
                        help='Extra license files to install.')
    return parser.parse_args()


def get_toolchain_flags(host):
    cflags = []
    ldflags = []
    if host == Host.Windows:
        cflags.append('/EHs')
    if host == Host.Linux:
        ldflags.append('-static-libstdc++')
        ldflags.append('-static-libgcc')
        ldflags.append('-pthread')
    return (cflags, ldflags)


def normalize_cmake_path(path):
    return path.replace('\\', '/')


def get_cmake_defines(host, args):
    defines = {}
    defines['CMAKE_BUILD_TYPE'] = 'Release'

    cflags, ldflags = get_toolchain_flags(host)
    cflags_str = ' '.join(cflags)
    ldflags_str = ' '.join(ldflags)

    defines['CMAKE_ASM_FLAGS'] = cflags_str
    defines['CMAKE_C_FLAGS'] = cflags_str
    defines['CMAKE_CXX_FLAGS'] = cflags_str

    defines['CMAKE_EXE_LINKER_FLAGS'] = ldflags_str
    defines['CMAKE_SHARED_LINKER_FLAGS'] = ldflags_str
    defines['CMAKE_MODULE_LINKER_FLAGS'] = ldflags_str

    if host == Host.Windows:
        defines['CMAKE_MSVC_RUNTIME_LIBRARY'] = 'MultiThreaded$<$<CONFIG:Debug>:Debug>'

    if host == Host.Linux:
        defines['OPENSSL_USE_STATIC_LIBS'] = 'ON'

    if host == Host.Darwin:
        # This will be used to set -mmacosx-version-min. And helps to choose SDK.
        # To specify a SDK, set CMAKE_OSX_SYSROOT or SDKROOT environment variable.
        defines['CMAKE_OSX_DEPLOYMENT_TARGET'] = '10.9'
        defines['CMAKE_OSX_ARCHITECTURES'] = 'x86_64;arm64'
    return defines


def build_cmake_target(host, args):
    build_dir = os.path.join(args.out_dir, 'build')
    install_dir = os.path.join(args.out_dir, 'install')

    print('## Building ##')
    print('## Out Dir     : {}'.format(args.out_dir))
    print('## Src         : {}'.format(args.src))
    sys.stdout.flush()

    os.makedirs(build_dir, exist_ok=True)
    os.makedirs(install_dir, exist_ok=True)

    defines = get_cmake_defines(host, args)
    defines['CMAKE_INSTALL_PREFIX'] = install_dir
    if args.ninja:
        defines['CMAKE_MAKE_PROGRAM'] = args.ninja

    config_cmd = [args.cmake, '-G', 'Ninja', args.src]
    for key, value in defines.items():
        config_cmd.append("-D{}={}".format(key, value))

    run_cmd(config_cmd, cwd=build_dir)

    if host == Host.Windows:
        ninja_target = 'install'
    else:
        ninja_target = 'install/strip'
    run_cmd([args.ninja, ninja_target], cwd=build_dir)

    # e.g.: /path/to/openssl-1.1.1k/LICENSE:doc/openssl-1.1.1k/LICENSE
    for notice in args.extra_notices.split():
        (src, dst) = notice.split(':')
        dst = os.path.join(install_dir, dst)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)

    return install_dir


def package_target(install_dir, dest_dir):
    os.makedirs(dest_dir, exist_ok=True)
    package_path = os.path.join(dest_dir, 'cmake.zip')

    print('## Packaging ##')
    print('## Package     : {}'.format(package_path))
    print('## Install Dir : {}'.format(install_dir))
    sys.stdout.flush()

    with zipfile.ZipFile(package_path, 'w', zipfile.ZIP_DEFLATED) as zip:
        zip_dir_to_zip(install_dir, zip)


def package_target_for_studio(install_dir, cmake_version, ninja_path,
                              android_cmake, dest_dir):
    """Create a package with ninja.exe and source.properties for Android SDK"""
    os.makedirs(dest_dir, exist_ok=True)
    package_path = os.path.join(dest_dir, 'cmake-for-studio.zip')
    source_properties = get_source_properties(cmake_version)

    print('## Packaging with Ninja ##')
    print('## Package     : {}'.format(package_path))
    print('## Install Dir : {}'.format(install_dir))
    sys.stdout.flush()

    module_path = glob.glob(os.path.join(install_dir, 'share', 'cmake-*'))[0]
    module_path = os.path.basename(module_path)
    with zipfile.ZipFile(package_path, 'w', zipfile.ZIP_DEFLATED) as zip:
        zip_dir_to_zip(install_dir, zip)
        zip.writestr("source.properties", source_properties)
        zip.write(ninja_path, os.path.join("bin",
                                           os.path.basename(ninja_path)))
        ninja_license_path = os.path.join(os.path.dirname(ninja_path),
                                          "LICENSE")
        zip.write(ninja_license_path, os.path.join("doc", "ninja", "LICENSE"))

        for cmake_file in ["AndroidNdkModules.cmake", "AndroidNdkGdb.cmake"]:
            file_path = os.path.join(android_cmake, cmake_file)
            zip.write(
                file_path,
                os.path.join("share", module_path, "Modules", cmake_file))


def get_source_properties(cmake_target_version):
    """Return a source.properties for CMake version and build ID"""

    source_properties = textwrap.dedent("""\
        Pkg.Revision = {cmake_target_version}
        Pkg.Path = cmake;{cmake_target_version}
        Pkg.Desc = CMake {cmake_target_version}
    """.format(cmake_target_version=cmake_target_version))
    return source_properties


def get_cmake_version(install_dir):
    """Return result of 'cmake --version'"""
    cmake_bin = os.path.join(install_dir, "bin")
    if get_default_host() == Host.Windows:
        cmake_exe = os.path.join(cmake_bin, "cmake.exe")
    else:
        cmake_exe = os.path.join(cmake_bin, "cmake")
    cmd = [cmake_exe, "--version"]
    print(subprocess.list2cmdline(cmd))
    output_bytes = subprocess.check_output(cmd)
    text = output_bytes.decode("UTF-8")
    # Should be like 'cmake version 3.17.0-g6cb76b9'
    first_line = text.splitlines()[0]
    # Should be like '3.17.0-g6cb76b9'
    version_with_sha = first_line.split()[2]
    version = version_with_sha.split("-")[0]  # Should be like '3.17.0'
    print("## CMake Version = '{}'".format(version))
    return version


def main():
    args = parse_arguments()
    host = get_default_host()
    install_dir = build_cmake_target(host, args)
    cmake_target_version = get_cmake_version(install_dir)
    package_target(install_dir, args.dest_dir)
    package_target_for_studio(install_dir, cmake_target_version, args.ninja,
                              args.android_cmake, args.dest_dir)


if __name__ == '__main__':
    main()
