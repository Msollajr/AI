param(
    [string]$OutputDir = "."
)

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

function Take-Screenshot {
    param([string]$Filename)
    $path = Join-Path -Path $OutputDir -ChildPath $Filename
    $bounds = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
    $bitmap = New-Object System.Drawing.Bitmap $bounds.Width, $bounds.Height
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    $graphics.CopyFromScreen($bounds.X, $bounds.Y, 0, 0, $bounds.Size)
    $bitmap.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
    $graphics.Dispose()
    $bitmap.Dispose()
    Write-Output "Saved: $path"
}

# Start with a clean screenshot dir
Take-Screenshot "00_initial_screen.png"

Write-Output "Screenshot function ready. Output dir: $OutputDir"
