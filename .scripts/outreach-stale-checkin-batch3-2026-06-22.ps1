$outlook = New-Object -ComObject Outlook.Application

$emails = @(
    @{
        To      = "nick@njsco.com"
        Subject = "Mid Atlantic - checking in"
        Body    = "Nick - Chris Barsanti from Mid Atlantic. Just wanted to touch base and see how things are going at NJS. If there's anything on the equipment side we could help with, I'd love to reconnect.`n`nChris Barsanti`nMid Atlantic Machinery"
    },
    @{
        To      = "ralphmaffucci@phoenixtube.com"
        Subject = "Phoenix Tube - staying in touch"
        Body    = "Ralph - Chris Barsanti from Mid Atlantic. Just reaching out to check in - wanted to see if there's been any movement on the laser discussion or anything else we could help with at Phoenix Tube.`n`nChris Barsanti`nMid Atlantic Machinery"
    },
    @{
        To      = "scott@phoenixforge.com"
        Subject = "Phoenix Forge - NC1 Press follow-up"
        Body    = "Scott - Chris Barsanti from Mid Atlantic. Wanted to check in on the press - I know we had been working through the details. Are we still on track to move forward this month? Happy to jump on a call this week if helpful.`n`nChris Barsanti`nMid Atlantic Machinery"
    },
    @{
        To      = "shop@nationalsteelfab.com"
        Subject = "National Steel - checking in"
        Body    = "Mike - Chris Barsanti from Mid Atlantic. Just wanted to follow up and see where things stand on the equipment discussion. Happy to reconnect whenever the timing works.`n`nChris Barsanti`nMid Atlantic Machinery"
    },
    @{
        To      = "scrowder@sencillosystems.com"
        Subject = "Sencillo - Carif saw follow-up"
        Body    = "Steve - Chris Barsanti from Mid Atlantic. Wanted to follow up on the Carif 320 - has that moved forward or are you still working through it? Happy to answer any questions on the quote.`n`nChris Barsanti`nMid Atlantic Machinery"
    },
    @{
        To      = "colin.phelps@victaulic.com"
        Subject = "Mid Atlantic - staying in touch"
        Body    = "Colin - Chris Barsanti from Mid Atlantic. Just wanted to check in and see how things are going at Victaulic. If there's anything on the equipment or manufacturing side we can help with, I'm around.`n`nChris Barsanti`nMid Atlantic Machinery"
    },
    @{
        To      = "glenn@craftweldfab.com"
        Subject = "Craftweld - FL4200 check-in"
        Body    = "Glenn - Chris Barsanti from Mid Atlantic. Just wanted to touch base on the FL4200 - wanted to make sure everything's on track and see if there's anything you need from us as things progress.`n`nChris Barsanti`nMid Atlantic Machinery"
    },
    @{
        To      = "wdocker@flowserve.com"
        Subject = "Checking in - Mid Atlantic Machinery"
        Body    = "Wayne - Chris Barsanti from Mid Atlantic. It's been a while - just wanted to stay on your radar and see if there's anything on the equipment side we could help with at Flowserve.`n`nChris Barsanti`nMid Atlantic Machinery"
    },
    @{
        To      = "rseiple@gerhart.com"
        Subject = "Gerhart - waterjet update"
        Body    = "Randy - Chris Barsanti from Mid Atlantic. Just checking in on the waterjet project - wanted to make sure things are progressing smoothly on your end and see if there's anything you need from us.`n`nChris Barsanti`nMid Atlantic Machinery"
    },
    @{
        To      = "dan@rybnickmechanical.com"
        Subject = "Rybnick - quick check-in"
        Body    = "Dan - Chris Barsanti from Mid Atlantic. Wanted to touch base on both the waterjet and the GEKA - a lot moving at once and just want to make sure we're keeping things on track. Give me a call when you get a chance.`n`nChris Barsanti`nMid Atlantic Machinery"
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
