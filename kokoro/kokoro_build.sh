#!/bin/bash
set -e

top=$(cd $(dirname $0)/../../.. && pwd)

out=$top/out/cmake
cmake_src=$top/external/cmake

case $(uname -s) in
  Linux) host=linux-x86 ;;
  Darwin) host=darwin-x86 ;;
  *) echo "Unrecognized uname -s: $(uname -s)"; exit 1 ;;
esac

rm -fr $out

$top/prebuilts/python/$host/bin/python3 \
  $cmake_src/kokoro/build.py $cmake_src $out $out/artifact "${KOKORO_BUILD_ID:-dev}" \
  --cmake=$top/prebuilts/cmake/$host/bin/cmake \
  --ninja=$top/prebuilts/ninja/$host/ninja \
  --android-cmake=$top/external/android-cmake \
  --clang-repo=$top/prebuilts/clang/host/$host
