# Serves the trainer on http://localhost:8770 (this computer only). Stop with Ctrl+C.
param([int]$Port = 8770, [string]$Root = $PSScriptRoot)
& (Join-Path $PSScriptRoot 'build-index.ps1') | Out-Null
$l = New-Object System.Net.HttpListener; $l.Prefixes.Add("http://localhost:$Port/"); $l.Start()
Write-Host "Trainer: http://localhost:$Port/"
$types = @{ '.html'='text/html; charset=utf-8'; '.json'='application/json; charset=utf-8'; '.js'='text/javascript'; '.css'='text/css';
            '.mp3'='audio/mpeg'; '.m4a'='audio/mp4'; '.mp4'='video/mp4'; '.wav'='audio/wav'; '.ogg'='audio/ogg';
            '.pdf'='application/pdf'; '.png'='image/png'; '.jpg'='image/jpeg' }
$rootFull = [IO.Path]::GetFullPath($Root)
while ($l.IsListening) {
  $c = $l.GetContext()
  try {
    $p = [Uri]::UnescapeDataString($c.Request.Url.AbsolutePath.TrimStart('/')); if ($p -eq '') { $p = 'index.html' }
    $f = [IO.Path]::GetFullPath((Join-Path $Root $p))
    if (-not $f.StartsWith($rootFull) -or -not (Test-Path $f -PathType Leaf)) { $c.Response.StatusCode = 404; continue }
    $b = [IO.File]::ReadAllBytes($f); $ext = [IO.Path]::GetExtension($f).ToLower()
    $c.Response.ContentType = $(if ($types[$ext]) { $types[$ext] } else { 'application/octet-stream' })
    $c.Response.AddHeader('Accept-Ranges', 'bytes')
    $r = $c.Request.Headers['Range']
    if ($r -and $r -match 'bytes=(\d*)-(\d*)') {
      $s = [int64]$(if ($Matches[1]) { $Matches[1] } else { 0 }); $e = [int64]$(if ($Matches[2]) { $Matches[2] } else { $b.Length - 1 })
      $c.Response.StatusCode = 206; $c.Response.AddHeader('Content-Range', "bytes $s-$e/$($b.Length)")
      $c.Response.ContentLength64 = $e - $s + 1; $c.Response.OutputStream.Write($b, $s, $e - $s + 1)
    } else { $c.Response.ContentLength64 = $b.Length; $c.Response.OutputStream.Write($b, 0, $b.Length) }
  } catch {} finally { $c.Response.Close() }
}
