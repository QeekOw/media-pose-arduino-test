# Export every slide of a deck to PNG through PowerPoint, so the deck can be reviewed as it renders.
# Usage: .\slides\export-pngs.ps1 [-Deck slides\final-deck.pptx] [-OutDir report\deck\slides]
param(
    [string]$Deck = "slides\final-deck.pptx",
    [string]$OutDir = "report\deck\slides"
)
$ErrorActionPreference = "Stop"
$deckPath = (Resolve-Path $Deck).Path
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$outPath = (Resolve-Path $OutDir).Path
Get-ChildItem $outPath -Filter "slide-*.png" | Remove-Item

$app = New-Object -ComObject PowerPoint.Application
try {
    # ReadOnly, Untitled, WithWindow = false
    $pres = $app.Presentations.Open($deckPath, -1, 0, 0)
    try {
        foreach ($slide in $pres.Slides) {
            $file = Join-Path $outPath ("slide-{0:D2}.png" -f $slide.SlideIndex)
            $slide.Export($file, "PNG", 1920, 1080)
            Write-Output $file
        }
    } finally {
        $pres.Close()
    }
} finally {
    if ($app.Presentations.Count -eq 0) { $app.Quit() }
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($app) | Out-Null
}
