#!/bin/bash
set -e

top=$(cd $(dirname $0)/../../.. && pwd)

out=$top/out/cmake
cmake_src=$top/external/cmake

# On Linux, enter the Docker container and reinvoke this script.
if [ "$(uname)" == "Linux" -a "$SKIP_DOCKER" == "" ]; then
  docker build -t ndk-cmake $cmake_src/kokoro
  export SKIP_DOCKER=1
  docker run -v$top:$top -eKOKORO_BUILD_ID -eSKIP_DOCKER \
    --entrypoint $cmake_src/kokoro/kokoro_build.sh \
    ndk-cmake
  exit $?
fi

extra_notices=

if [ "$(uname)" == "Darwin" ]; then
  host=darwin-x86
  echo "Selected Xcode: $(xcode-select -p)"
elif [ "$(uname)" == "Linux" ]; then
  host=linux-x86
  . /opt/rh/devtoolset-10/enable

  # Build openssl and link it statically.
  #  * We can't use libssl.so from the host because it might not be installed,
  #    and filenames vary (libssl.so.10 and libssl.so.1.0.2k on CentOS 7,
  #    libssl.so.1.0.0 on Ubuntu 16.04, libssl.so.1.1 on Ubuntu 20.04).
  #  * We can't use the CentOS openssl-static package because it has too many
  #    dependencies (e.g. libcom_err and various kerberos libraries).
  openssl_top=$top/out/openssl
  rm -fr $openssl_top
  mkdir -p $openssl_top/build
  tar -C $openssl_top -xf $top/tools/ndkports/openssl/src.tar.gz
  openssl_src=$(echo $openssl_top/openssl-*)
  pushd $openssl_top/build
  $openssl_src/Configure linux-x86_64 no-shared
  make -j$(nproc)
  # Use install_sw to skip installing OpenSSL docs, which is slow.
  make install_sw
  extra_notices="$extra_notices $openssl_src/LICENSE:doc/$(basename $openssl_src)/LICENSE"
  popd
else
  echo "Unrecognized uname -s: $(uname -s)"
  exit 1
fi

rm -fr $out

$top/prebuilts/python/$host/bin/python3 \
  $cmake_src/kokoro/build.py $cmake_src $out $out/artifact "${KOKORO_BUILD_ID:-dev}" \
  --cmake=$top/prebuilts/cmake/$host/bin/cmake \
  --ninja=$top/prebuilts/ninja/$host/ninja \
  --android-cmake=$top/external/android-cmake \
  --extra-notices="$extra_notices"
