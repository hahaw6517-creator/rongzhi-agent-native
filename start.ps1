param(
    [int]$Port = 8787,
    [string]$ListenAddress = '127.0.0.1'
)

$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'start-native.ps1') -Port $Port -ListenAddress $ListenAddress
