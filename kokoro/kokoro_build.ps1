$top       = (Resolve-Path "$PSScriptRoot\..\..\..")
$out       = "$top\out\cmake"
$cmake_src = "$top\external\cmake"
$python    = "$top\prebuilts\python\windows-x86\python.exe"

Remove-Item $out -Recurse -ErrorAction Ignore

$vcvarsall = (Resolve-Path "C:\Program Files*\Microsoft Visual Studio\2017\*\VC\Auxiliary\Build\vcvarsall.bat")[-1]
echo "Invoking $vcvarsall to configure clang-cl"

pushd (Split-Path $vcvarsall)
cmd /c "vcvarsall.bat amd64 & set" |
foreach {
  if ($_ -match "=") {
    $v = $_.split("=")
    set-item -force -path "ENV:\$($v[0])"  -value "$($v[1])"
  }
}
popd

if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$toolkit_path = (Resolve-Path "C:\Program Files*\Windows Kits\10\bin\*\x64\rc.exe")[-1] | Split-Path
echo "Adding $toolkit_path to end of PATH"
$ENV:PATH += ";$toolkit_path"

# Remove cygwin from path so that cmake will not detect its compiler.
$ENV:PATH = ($ENV:PATH.Split(';') | Where-Object { $_ -notmatch 'cygwin' }) -join ';'

$build_id = $ENV:KOKORO_BUILD_ID
$build_id = if ($build_id -eq $null) { "dev" } else { $build_id }

& $python "$PSScriptRoot\build.py", $cmake_src, $out, "$out\artifact", $build_id,
  "--cmake=$top\prebuilts\cmake\windows-x86\bin\cmake.exe",
  "--ninja=$top\prebuilts\ninja\windows-x86\ninja.exe",
  "--android-cmake=$top\external\android-cmake"

# TODO: We use our Clang prebuilt on Linux and Darwin, but it doesn't currently work on Windows.
# Consider making it work on Windows, or maybe just use the default C++ compilers (g++, XCode
# clang++, MSVC). See http://fusion2/0a310044-d597-497b-9f5e-9ee4b880748b, which fails with:
#     ninja: fatal: CreateProcess: This version of %1 is not compatible with the version of Windows
#     you're running.
# The likely problem is that clang-cl.exe is a symlink with newer Android Clang prebuilts, and
# kokoro isn't creating an NTFS symlink (e.g. maybe because mklink requires elevation).
# "--clang-repo=$top\prebuilts\clang\host\windows-x86"

exit $LASTEXITCODE
