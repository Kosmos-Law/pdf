# Stage Tesseract and Ghostscript for the Windows build, into packaging/windows/tools/,
# from where kosmicpdf.spec copies them into the app folder (tools/tesseract, tools/gs).
#
#     pwsh packaging/windows/fetch_tools.ps1
#
# Both come as NSIS installers (there are no plain archives). 7-Zip can unpack an NSIS
# installer, which is more predictable than running it, so that is tried first; where
# 7-Zip can't (the Ghostscript installer, with some 7-Zip versions), the installer is run
# silently and its files found. Only the pieces OCRmyPDF needs are kept: the two
# programs, their libraries, and English plus orientation detection for Tesseract. The
# checksums pin the exact files.
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

# Unpack an installer with 7-Zip into $dir, or failing that run it silently (/S installs
# into the folder after /D=, which must be the last argument, unquoted). Returns the
# folder that holds $marker (a file the install must contain), wherever it landed.
function Unpack($name, $setup, $dir, $marker) {
    if (Test-Path $dir) { Remove-Item -Recurse -Force $dir }
    & 7z x -y "-o$dir" $setup *> (Join-Path $tmp "$name-7z.log")
    Write-Host "7z exit code $LASTEXITCODE (1 is warnings only)"
    $found = Get-ChildItem -Path $dir -Recurse -Filter $marker -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $found) {
        Write-Host "7-Zip didn't unpack $marker; running the installer silently"
        if (Test-Path $dir) { Remove-Item -Recurse -Force $dir }
        $p = Start-Process -Wait -PassThru -FilePath $setup -ArgumentList "/S", "/D=$dir"
        Write-Host "installer exit code $($p.ExitCode)"
        $places = @($dir, "$env:ProgramFiles\gs", "$env:ProgramFiles\Tesseract-OCR", "${env:ProgramFiles(x86)}\gs", "$env:LOCALAPPDATA\Programs")
        foreach ($place in $places) {
            if (Test-Path $place) {
                $found = Get-ChildItem -Path $place -Recurse -Filter $marker -ErrorAction SilentlyContinue | Select-Object -First 1
                if ($found) { break }
            }
        }
    }
    if (-not $found) {
        Write-Host "Contents of $tmp and Program Files:"
        Get-ChildItem $tmp | ForEach-Object { "  $($_.Name)" }
        Get-ChildItem $env:ProgramFiles | ForEach-Object { "  $($_.Name)" }
        throw "$name: $marker not found after unpacking $setup"
    }
    Write-Host "$name files at $($found.DirectoryName)"
    return $found.DirectoryName
}

Write-Host "==> Tesseract"
$tessDir = Unpack "tesseract" (Fetch "tesseract" $tesseractUrl $tesseractSha) (Join-Path $tmp "tesseract-install") "tesseract.exe"
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
# The marker is in bin\; the Ghostscript folder is the one above it.
$gsDir = Split-Path -Parent (Unpack "ghostscript" (Fetch "ghostscript" $gsUrl $gsSha) (Join-Path $tmp "gs-install") "gswin64c.exe")
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
