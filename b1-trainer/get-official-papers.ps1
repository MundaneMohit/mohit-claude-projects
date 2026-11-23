# Downloads the free official B1 practice tests to papers/_downloads/ (not part of the repo).
# Sources: Goethe-Institut (goethe.de/de/spr/prf/ueb/pb1.html) and telc (telc.net, Zertifikat Deutsch / telc Deutsch B1).
# After the download, ask Claude: "Importiere die heruntergeladenen Prüfungen" (see IMPORT.md).
$dl = Join-Path $PSScriptRoot 'papers\_downloads'
New-Item -ItemType Directory -Force $dl | Out-Null
$files = [ordered]@{
  'goethe-b1-modellsatz-1.pdf'       = 'https://www.goethe.de/pro/relaunch/prf/materialien/B1/b1_modellsatz_erwachsene.pdf'
  'goethe-b1-modellsatz-1-hoeren.mp4' = 'https://goethemp4s.akamaized.net/resources/files/mp468/pruefungstraining_1_hoeren_b1_erwachsene.mp4'
  'goethe-b1-uebungssatz-2.pdf'      = 'https://www.goethe.de/pro/relaunch/prf/materialien/B1/B1_Uebungssatz_Erwachsene.pdf'
  'goethe-b1-uebungssatz-2-hoeren.mp4' = 'https://goethemp4s.akamaized.net/resources/files/mp468/pruefungstraining_2_hoeren_b1_erwachsene.mp4'
  'telc-deutsch-b1-uebungstest-1.zip' = 'https://www.telc.net/fileadmin/user_upload/mock_exams/Deutsch/telc_deutsch_b1.zip'
}
foreach ($name in $files.Keys) {
  $out = Join-Path $dl $name
  if (Test-Path $out) { Write-Host "have  $name"; continue }
  Write-Host "get   $name"
  curl.exe -s -L -f -A "Mozilla/5.0" -o $out $files[$name]
  if ($LASTEXITCODE -ne 0) { Write-Warning "Download failed: $($files[$name])"; Remove-Item $out -ErrorAction SilentlyContinue }
}
$zip = Join-Path $dl 'telc-deutsch-b1-uebungstest-1.zip'
if ((Test-Path $zip) -and -not (Test-Path (Join-Path $dl 'telc-b1'))) { Expand-Archive $zip (Join-Path $dl 'telc-b1') }
Write-Host "Done. Files in $dl"
