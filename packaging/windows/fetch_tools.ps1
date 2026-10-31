# Stage Tesseract and Ghostscript for the Windows build, into packaging/windows/tools/,
# from where kosmicpdf.spec copies them into the app folder (tools/tesseract, tools/gs).
#
#     pwsh packaging/windows/fetch_tools.ps1
#
# Both come as NSIS installers (there are no plain archives), run silently into a
# temporary folder; only the pieces OCRmyPDF needs are kept: the two programs, their
# libraries, and English plus orientation detection for Tesseract. The checksums pin the
# exact files.
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$tools = Join-Path $here "tools"
$tmp = if ($env:RUNNER_TEMP) { $env:RUNNER_TEMP } else { $env:TEMP }

$tesseractUrl = "https://github.com/UB-Mannheim/tesseract/releases/download/v5.4.0.20240606/tesseract-ocr-w64-setup-5.4.0.20240606.exe"
$tesseractSha = "c885fff6998e0608ba4bb8ab51436e1c6775c2bafc2559a19b423e18678b60c9"
$gsUrl = "https://github.com/ArtifexSoftware/ghostpdl-downloads/releases/download/gs10080/gs10080w64.exe"
$gsSha = "52a91b8bf09298788d7a57b9206127026c23eacd75405f0a131e26dc381dce50"

function Fetch($name, $url, $sha256) {
    $file = Join-Path $tmp "$name-setup.exe"
    if (-not (Test-Path $file) -or (Get-FileHash $file -Algorithm SHA256).Hash -ne $sha256) {
        Write-Host "Downloading $url"
        Invoke-WebRequest -Uri $url -OutFile $file
    }
    $hash = (Get-FileHash $file -Algorithm SHA256).Hash
    if ($hash -ne $sha256) { throw "$name installer: checksum $hash, expected $sha256" }
    return $file
}

# /S installs silently, into the folder after /D= (which must be the last argument, unquoted).
function InstallSilently($setup, $dir) {
    if (Test-Path $dir) { Remove-Item -Recurse -Force $dir }
    $p = Start-Process -Wait -PassThru -FilePath $setup -ArgumentList "/S", "/D=$dir"
    if ($p.ExitCode -ne 0) { throw "$setup exited with $($p.ExitCode)" }
}

if (Test-Path $tools) { Remove-Item -Recurse -Force $tools }

Write-Host "==> Tesseract"
$tessDir = Join-Path $tmp "tesseract-install"
InstallSilently (Fetch "tesseract" $tesseractUrl $tesseractSha) $tessDir
$dest = Join-Path $tools "tesseract"
New-Item -ItemType Directory -Force (Join-Path $dest "tessdata") | Out-Null
Copy-Item (Join-Path $tessDir "tesseract.exe") $dest
Copy-Item (Join-Path $tessDir "*.dll") $dest
foreach ($f in "eng.traineddata", "osd.traineddata", "pdf.ttf") {
    Copy-Item (Join-Path $tessDir "tessdata\$f") (Join-Path $dest "tessdata")
}
foreach ($d in "configs", "tessconfigs") {
    $src = Join-Path $tessDir "tessdata\$d"
    if (Test-Path $src) { Copy-Item -Recurse $src (Join-Path $dest "tessdata") }
}
$env:TESSDATA_PREFIX = Join-Path $dest "tessdata"
& (Join-Path $dest "tesseract.exe") --version
if ($LASTEXITCODE -ne 0) { throw "tesseract.exe does not run" }

Write-Host "==> Ghostscript"
$gsDir = Join-Path $tmp "gs-install"
InstallSilently (Fetch "ghostscript" $gsUrl $gsSha) $gsDir
$dest = Join-Path $tools "gs"
New-Item -ItemType Directory -Force (Join-Path $dest "bin") | Out-Null
Copy-Item (Join-Path $gsDir "bin\gswin64c.exe") (Join-Path $dest "bin")
Copy-Item (Join-Path $gsDir "bin\gsdll64.dll") (Join-Path $dest "bin")
foreach ($d in "lib", "Resource") {
    $src = Join-Path $gsDir $d
    if (Test-Path $src) { Copy-Item -Recurse $src $dest }
}
$copying = Join-Path $gsDir "doc\COPYING"
if (Test-Path $copying) { Copy-Item $copying $dest }
& (Join-Path $dest "bin\gswin64c.exe") --version
if ($LASTEXITCODE -ne 0) { throw "gswin64c.exe does not run" }

Write-Host "==> Staged in $tools"
Get-ChildItem -Recurse $tools | Measure-Object -Property Length -Sum | ForEach-Object { "{0:N0} MB" -f ($_.Sum / 1MB) }
