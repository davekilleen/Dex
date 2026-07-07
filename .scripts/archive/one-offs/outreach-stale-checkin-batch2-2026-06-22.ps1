$outlook = New-Object -ComObject Outlook.Application

$emails = @(
    @{
        To      = "vaddesa@loadrite.com"
        Subject = "Staying in touch - Mid Atlantic Machinery"
        Body    = "Vito - Chris Barsanti from Mid Atlantic. Just checking in to see how things are going at Load Rite. If any equipment needs have come up, I'd love to reconnect.`n`nChris Barsanti`nMid Atlantic Machinery"
    },
    @{
        To      = "jjmiga@jl-precision.com"
        Subject = "Mid Atlantic - checking in"
        Body    = "John - Chris Barsanti from Mid Atlantic. It's been a bit since we talked - just wanted to see how things are at J&L and if there's anything on the machining or fabrication equipment side we could support.`n`nChris Barsanti`nMid Atlantic Machinery"
    },
    @{
        To      = "mlines@winholt.com"
        Subject = "Mid Atlantic Machinery - quick check-in"
        Body    = "Malcolm - Chris Barsanti from Mid Atlantic. Just wanted to touch base and see how things are running at Winholt. Anything on the equipment or processing side we could help with, happy to chat.`n`nChris Barsanti`nMid Atlantic Machinery"
    },
    @{
        To      = "gtfab@comcast.net"
        Subject = "GT Fab - checking in"
        Body    = "Gene - Chris Barsanti from Mid Atlantic. Hope things are busy at the shop. Just wanted to stay in touch and see if there's anything we can help with on the equipment side.`n`nChris Barsanti`nMid Atlantic Machinery"
    },
    @{
        To      = "c.karpyn@kingindustrials.com"
        Subject = "Mid Atlantic - staying in touch"
        Body    = "Chet - Chris Barsanti from Mid Atlantic. Just reaching out to check in and see how things are going at King Coatings. If there's anything on the equipment front we can help with, I'm around.`n`nChris Barsanti`nMid Atlantic Machinery"
    },
    @{
        To      = "ericd@laminarflowinc.com"
        Subject = "Checking in - Mid Atlantic Machinery"
        Body    = "Eric - Chris Barsanti from Mid Atlantic. It's been a while - wanted to see how things are going at Laminar Flow and if there's anything on the equipment side we could help with.`n`nChris Barsanti`nMid Atlantic Machinery"
    },
    @{
        To      = "nick@custommfgcorp.com"
        Subject = "Mid Atlantic - quick hello"
        Body    = "Nick - Chris Barsanti from Mid Atlantic. Just wanted to touch base and see how things are going at Custom Manufacturing. If anything's come up on the equipment side, happy to reconnect.`n`nChris Barsanti`nMid Atlantic Machinery"
    },
    @{
        To      = "dmuller@eecinc.net"
        Subject = "Staying in touch - Mid Atlantic Machinery"
        Body    = "Doug - Chris Barsanti from Mid Atlantic. It's been a while since we connected - just wanted to check in and see if there's anything on the equipment or fabrication side we could help with at Eastern Environmental.`n`nChris Barsanti`nMid Atlantic Machinery"
    }
)

$created = 0
$skipped = 0

foreach ($email in $emails) {
    try {
        $mail = $outlook.CreateItem(0)
        $mail.To = $email.To
        if ($email.CC) { $mail.CC = $email.CC }
        $mail.Subject = $email.Subject
        $mail.Body = $email.Body
        $mail.Save()
        Write-Host "OK: $($email.Subject) -> $($email.To)" -ForegroundColor Green
        $created++
    } catch {
        Write-Host "FAIL: $($email.Subject) - $_" -ForegroundColor Red
        $skipped++
    }
}

Write-Host ""
Write-Host "Done: $created drafts created, $skipped failed." -ForegroundColor Cyan
