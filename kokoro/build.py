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
from typing import List, Union


CMAKE_SRC = Path(__file__).parent.parent
TOP = CMAKE_SRC.parent.parent

sys.path.append(str(TOP / 'toolchain/ndk-kokoro'))
from build_utils import Host, get_default_host, run_cmd, zip_dir_to_zip, create_new_dir, LinuxArm64Musl


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
    return parser.parse_args()


def build_openssl(host, args) -> (Path, List[str]):
  """ Build openssl and link it statically.
    * We can't use libssl.so from the host because it might not be installed,
      and filenames vary (libssl.so.10 and libssl.so.1.0.2k on CentOS 7,
      libssl.so.1.0.0 on Ubuntu 16.04, libssl.so.1.1 on Ubuntu 20.04).
    * We can't use the CentOS openssl-static package because it has too many
      dependencies (e.g. libcom_err and various kerberos libraries).
  """

  openssl_dir = Path(args.out_dir) / 'openssl'
  build_dir = openssl_dir / 'build'
  install_dir = openssl_dir / 'install'
  create_new_dir(openssl_dir)
  create_new_dir(build_dir)

  run_cmd(['tar', '-C', openssl_dir, '-xf', TOP / 'tools/ndkports/openssl/src.tar.gz'])
  openssl_src = list(openssl_dir.glob('openssl-*'))[0]

  configure = openssl_src / 'Configure'
  configure_cmd = [configure, 'no-shared', f'--prefix={install_dir}']

  env = os.environ.copy()
  if host == Host.Linux:
    configure_cmd += ['linux-x86_64']
  elif host == Host.LinuxArm64:
    configure_cmd += ['linux-aarch64']
    env['CC'] = LinuxArm64Musl.CC
    env['CXX'] = LinuxArm64Musl.CXX
    env['CFLAGS'] = LinuxArm64Musl.CFLAGS
    env['LDFLAGS'] = LinuxArm64Musl.LDFLAGS

  run_cmd(configure_cmd, cwd=build_dir, env=env)

  run_cmd(['make', f'-j{os.cpu_count()}'], cwd=build_dir)
  # Use install_sw to skip installing OpenSSL docs, which is slow.
  run_cmd(['make', 'install_sw'], cwd=build_dir)

  extra_notices=[f'{openssl_src}/LICENSE.txt:doc/{openssl_src.name}/LICENSE.txt']
  return install_dir, extra_notices


def get_toolchain_flags(host):
    cflags = []
    ldflags = []
    if host == Host.Windows:
        cflags.append('/EHs')
    if host == Host.Linux:
        ldflags.append('-static-libstdc++')
        ldflags.append('-static-libgcc')
        ldflags.append('-pthread')
    if host == Host.LinuxArm64:
        cflags.append(LinuxArm64Musl.CFLAGS)
        ldflags.append(LinuxArm64Musl.LDFLAGS)
        ldflags.append('-static-libstdc++')
        ldflags.append('-Wl,-rpath,\$ORIGIN')
        ldflags.append('-Wl,-rpath,\$ORIGIN/../lib')

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

    if host == Host.LinuxArm64:
        defines['CMAKE_SYSROOT'] = LinuxArm64Musl.SYSROOT
        defines['CMAKE_C_COMPILER'] = LinuxArm64Musl.CC
        defines['CMAKE_CXX_COMPILER'] = LinuxArm64Musl.CXX

    if host == Host.Darwin:
        # This will be used to set -mmacosx-version-min. And helps to choose SDK.
        # To specify a SDK, set CMAKE_OSX_SYSROOT or SDKROOT environment variable.
        defines['CMAKE_OSX_DEPLOYMENT_TARGET'] = '10.9'
        defines['CMAKE_OSX_ARCHITECTURES'] = 'x86_64;arm64'
    return defines


def build_cmake_target(host, args, openssl_install_dir: Path, extra_notices: List[str]):
    build_dir = os.path.join(args.out_dir, 'build')
    install_dir = os.path.join(args.out_dir, 'install')

    print('## Building ##')
    print('## Out Dir     : {}'.format(args.out_dir))
    print('## Src         : {}'.format(args.src))
    sys.stdout.flush()

    os.makedirs(build_dir, exist_ok=True)
    os.makedirs(install_dir, exist_ok=True)
    copy_extra_libs(host, args, install_dir)

    defines = get_cmake_defines(host, args)
    defines['CMAKE_INSTALL_PREFIX'] = install_dir
    if args.ninja:
        defines['CMAKE_MAKE_PROGRAM'] = args.ninja
    if openssl_install_dir:
        defines['OPENSSL_ROOT_DIR'] = openssl_install_dir

    config_cmd = [args.cmake, '-G', 'Ninja', args.src]
    for key, value in defines.items():
        config_cmd.append("-D{}={}".format(key, value))

    run_cmd(config_cmd, cwd=build_dir)

    if host == Host.Windows:
        ninja_target = 'install'
    else:
        ninja_target = 'install/strip'

    env = os.environ.copy()
    env['LD_LIBRARY_PATH'] = install_dir + '/lib'

    run_cmd([args.ninja, ninja_target], cwd=build_dir, env=env)

    # e.g.: /path/to/openssl-1.1.1k/LICENSE:doc/openssl-1.1.1k/LICENSE
    if host == Host.LinuxArm64:
        extra_notices += [f'{notice}:doc/musl/{notice.name}' for notice in LinuxArm64Musl.LIBC_MUSL_NOTICES]

    for notice in extra_notices:
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


def copy_extra_libs(host, args, install_dir):
    if host == Host.LinuxArm64:
        os.makedirs(install_dir + '/lib', exist_ok=True)
        shutil.copy(LinuxArm64Musl.LIBC_MUSL, install_dir + '/lib/libc_musl.so')


def main():
    args = parse_arguments()
    host = get_default_host()

    openssl_install_dir = None
    openssl_notices = []
    if host == Host.Linux or host == Host.LinuxArm64:
        openssl_install_dir, openssl_notices = build_openssl(host, args)

    install_dir = build_cmake_target(host, args, openssl_install_dir, openssl_notices)
    cmake_target_version = get_cmake_version(install_dir)
    package_target(install_dir, args.dest_dir)
    package_target_for_studio(install_dir, cmake_target_version, args.ninja,
                              args.android_cmake, args.dest_dir)


if __name__ == '__main__':
    main()
