Add-Type -AssemblyName PresentationFramework

$window = New-Object System.Windows.Window
$window.Title = "Operational Memory Ambiguity Fixture"
$window.Width = 900
$window.Height = 520
$window.WindowStartupLocation = "CenterScreen"

$root = New-Object System.Windows.Controls.StackPanel
$root.Margin = "36"

$navigation = New-Object System.Windows.Controls.StackPanel
$navigation.Orientation = "Horizontal"

1..2 | ForEach-Object {
    $button = New-Object System.Windows.Controls.Button
    $button.Content = "Documentation"
    $button.Width = 210
    $button.Height = 58
    $button.Margin = "0,0,24,0"
    $button.FontSize = 18
    [void]$navigation.Children.Add($button)
}

$heading = New-Object System.Windows.Controls.TextBlock
$heading.Text = "Current-capture ambiguity fixture"
$heading.FontSize = 28
$heading.FontWeight = "Bold"
$heading.Margin = "0,64,0,12"

$description = New-Object System.Windows.Controls.TextBlock
$description.Text = "The two controls intentionally share the same accessible label."
$description.FontSize = 16

[void]$root.Children.Add($navigation)
[void]$root.Children.Add($heading)
[void]$root.Children.Add($description)
$window.Content = $root
[void]$window.ShowDialog()
