$top       = (Resolve-Path "$PSScriptRoot\..\..\..")
$out       = "$top\out\cmake"
$cmake_src = "$top\external\cmake"

Remove-Item $out -Recurse -ErrorAction Ignore

try {
  echo "Searching in Program Files"
  $vcvarsall = (Resolve-Path "C:\Program Files*\Microsoft Visual Studio\2022\*\VC\Auxiliary\Build\vcvarsall.bat")[-1]
} catch {
  # Kokoro installs MSVC to C:\VS\VC instead, so look there too.
  echo "Searching in C:\VS"
  $vcvarsall = (Resolve-Path "C:\VS\VC\Auxiliary\Build\vcvarsall.bat")[-1]
}

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

& py -3 --version
& py -3 "$PSScriptRoot\build.py", $cmake_src, $out, "$out\artifact", $build_id,
  "--cmake=$top\prebuilts\cmake\windows-x86\bin\cmake.exe",
  "--ninja=$top\prebuilts\ninja\windows-x86\ninja.exe",
  "--android-cmake=$top\external\android-cmake"

if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& py -3 "$top\toolchain\ndk-kokoro\gen_manifest.py" --root "$top" -o "$out\artifact\manifest-$build_id.xml"

exit $LASTEXITCODE
