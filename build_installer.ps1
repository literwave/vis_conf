param(
    [string]$Version = "1.0.0"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$compiler = Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"
$appPackage = Join-Path $projectRoot "dist\package\star_map"
$portableOutput = Join-Path $projectRoot "dist\portable"
$portableZip = Join-Path $portableOutput "StarMap-Portable-$Version.zip"
$portableStaging = Join-Path $projectRoot "dist\portable-staging-$PID"

if (-not (Test-Path -LiteralPath $compiler -PathType Leaf)) {
    throw "Inno Setup compiler not found: $compiler"
}

Push-Location $projectRoot
try {
    & flet pack app.py `
        --onedir `
        --name star_map `
        --product-name "星图 游戏配置导表工具" `
        --file-description "星图 游戏配置导表工具" `
        --product-version $Version `
        --file-version "$Version.0" `
        --icon "assets\assistant-icon.ico" `
        --add-data "plugin_catalog;plugin_catalog" `
        --distpath "dist\package" `
        --yes
    if ($LASTEXITCODE -ne 0) {
        throw "Flet packaging failed with exit code $LASTEXITCODE."
    }

    & $compiler "/DMyAppVersion=$Version" "installer.iss"
    if ($LASTEXITCODE -ne 0) {
        throw "Inno Setup compilation failed with exit code $LASTEXITCODE."
    }

    if (Test-Path -LiteralPath $portableStaging) {
        Remove-Item -LiteralPath $portableStaging -Recurse -Force
    }
    New-Item -ItemType Directory -Path $portableStaging | Out-Null
    $portableApp = Join-Path $portableStaging "star_map"
    Copy-Item -LiteralPath $appPackage -Destination $portableApp -Recurse
    $examplesTest = Join-Path $portableApp "examples\test"
    $examplesAssets = Join-Path $portableApp "examples\assets"
    New-Item -ItemType Directory -Path $examplesTest, $examplesAssets -Force | Out-Null
    Copy-Item -Path (Join-Path $projectRoot "test\*") -Destination $examplesTest -Recurse
    Copy-Item -LiteralPath (Join-Path $projectRoot "assets\assistant-icon.png") `
        -Destination $examplesAssets

    New-Item -ItemType Directory -Path $portableOutput -Force | Out-Null
    if (Test-Path -LiteralPath $portableZip) {
        Remove-Item -LiteralPath $portableZip -Force
    }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [System.IO.Compression.ZipFile]::CreateFromDirectory(
        $portableStaging,
        $portableZip,
        [System.IO.Compression.CompressionLevel]::Optimal,
        $false
    )
}
finally {
    if (Test-Path -LiteralPath $portableStaging) {
        Remove-Item -LiteralPath $portableStaging -Recurse -Force
    }
    Pop-Location
}

Write-Output "Installer created: $projectRoot\dist\installer\StarMap-Setup-$Version.exe"
Write-Output "Portable ZIP created: $portableZip"
