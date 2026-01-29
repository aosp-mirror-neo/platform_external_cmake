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
  if [ "$(uname -m)" == "aarch64" ]; then
    host=linux-arm64
  else
    host=linux-x86
    . /opt/rh/gcc-toolset-10/enable
  fi
else
  echo "Unrecognized uname -s: $(uname -s)"
  exit 1
fi

rm -fr $out

python3 --version
python3 $cmake_src/kokoro/build.py $cmake_src $out $out/artifact "${KOKORO_BUILD_ID:-dev}" \
  --cmake=$top/prebuilts/cmake/$host/bin/cmake \
  --ninja=$top/prebuilts/ninja/$host/ninja \
  --android-cmake=$top/external/android-cmake

$top/toolchain/ndk-kokoro/gen_manifest.py --root $top \
  -o "$out/artifact/manifest-${KOKORO_BUILD_ID:-dev}.xml"
