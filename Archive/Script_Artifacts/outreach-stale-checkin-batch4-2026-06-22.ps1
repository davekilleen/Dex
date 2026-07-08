$outlook = New-Object -ComObject Outlook.Application

$emails = @(
    @{
        To      = "lszoke@szokebrothers.com"
        Subject = "Szoke Brothers - Alltra plasma follow-up"
        Body    = "Luke - Chris Barsanti from Mid Atlantic. Wanted to check back in on the Alltra plasma - were you guys able to get the power upgrades sorted out in the building? That was the last piece we were waiting on. Let me know where things stand and we can go from there.`n`nChris Barsanti`nMid Atlantic Machinery"
    },
    @{
        To      = "jfendrock@jkftechnologies.com"
        Subject = "JKF Technologies - Mid Atlantic check-in"
        Body    = "Joe - Chris Barsanti from Mid Atlantic. Just wanted to stay on your radar and see how things are going at JKF. If there's anything on the equipment or fabrication side we could help with, happy to reconnect.`n`nChris Barsanti`nMid Atlantic Machinery"
    },
    @{
        To      = "evanm@demcoautomation.com"
        Subject = "Demco - checking in"
        Body    = "Evan - Chris Barsanti from Mid Atlantic. It's been a while since we talked about the TRUMPF - wanted to see if that's still something worth exploring or if things have moved in a different direction. Happy to reconnect.`n`nChris Barsanti`nMid Atlantic Machinery"
    },
    @{
        To      = "jesse@landiswelding.com"
        Subject = "Landis Welding - quick check-in"
        Body    = "Jesse - Chris Barsanti from Mid Atlantic. Wanted to touch base on a few things - the knee mill, the CNC lathe, and the 2060 manual lathe are all in play and I want to make sure we keep the ball moving. Give me a call when you have a few minutes.`n`nChris Barsanti`nMid Atlantic Machinery"
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
