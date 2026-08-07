$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $MyInvocation.MyCommand.Path)
if (-not (Test-Path ".venv")) { py -3.12 -m venv .venv; .\.venv\Scripts\python.exe -m pip install -r requirements.txt }
if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env" }
.\.venv\Scripts\python.exe app\main.py
