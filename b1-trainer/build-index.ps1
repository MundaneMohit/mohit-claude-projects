# Lists every papers/<id>/paper.json in papers/index.json, which the trainer page reads.
$papers = Join-Path $PSScriptRoot 'papers'
$list = foreach ($f in Get-ChildItem $papers -Recurse -Filter paper.json -ErrorAction SilentlyContinue) {
  try {
    $p = Get-Content $f.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
    [pscustomobject]@{ id = $f.Directory.Name; title = $p.title; exam = $p.exam }
  } catch { Write-Warning "Skipped $($f.FullName): $($_.Exception.Message)" }
}
$json = ConvertTo-Json @($list | Sort-Object exam, title) -Depth 3
[IO.File]::WriteAllText((Join-Path $papers 'index.json'), $json, (New-Object Text.UTF8Encoding $false))
Write-Host "$(@($list).Count) papers in papers/index.json"
