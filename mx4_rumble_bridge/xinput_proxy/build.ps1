$ErrorActionPreference = 'Stop'
$gcc = 'C:\msys64\ucrt64\bin\gcc.exe'
$source = Join-Path $PSScriptRoot 'xinput_proxy.c'

if (-not (Test-Path -LiteralPath $gcc)) {
    throw "MinGW GCC niet gevonden: $gcc"
}

$variants = @('xinput1_4.dll', 'xinput1_3.dll', 'xinput9_1_0.dll')
foreach ($name in $variants) {
    $output = Join-Path $PSScriptRoot $name
    $define = '-DREAL_XINPUT_DLL=L\"' + $name + '\"'
    & $gcc -shared -O2 -o $output $source $define -lws2_32
    if ($LASTEXITCODE -ne 0) {
        throw "Bouwen van $name mislukt."
    }
    Write-Host "Gebouwd: $output"
}
