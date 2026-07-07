$outlook = New-Object -ComObject Outlook.Application

$emails = @(
    @{
        To      = "kwieland@polymershapes.com"
        Subject = "Checking in - Chris Barsanti / Mid Atlantic"
        Body    = "Hey Kevin - just wanted to touch base and see how things are going at Polymershapes. We had talked a bit about routing solutions - curious if that's still on your radar or if priorities have shifted. Happy to reconnect whenever the timing makes sense.`n`nChris Barsanti`nMid Atlantic Machinery"
    },
    @{
        To      = "matt@standardironworks.com"
        Subject = "Quick check-in - Mid Atlantic Machinery"
        Body    = "Matt - hope summer's treating you well. It's been a while since we connected - wanted to see if there's anything on the equipment side we could help with. No agenda, just staying in touch.`n`nChris Barsanti`nMid Atlantic Machinery"
    },
    @{
        To      = "ken@gottsteincorporation.com"
        CC      = "skuntz@gottsteincorporation.com; rlorince@gottsteincorporation.com; jmorell@gottsteincorporation.net"
        Subject = "Gottstein - quick check-in"
        Body    = "Ken - wanted to pop in and see where things stand on the waterjet and the TRUMPF discussion. I know there's been a lot on your plate - just want to make sure we're supporting you the right way as things develop. Give me a call whenever works.`n`nChris Barsanti`nMid Atlantic Machinery"
    },
    @{
        To      = "gmt81423@gmail.com"
        Subject = "Nazareth Machine - staying in touch"
        Body    = "Grant - Chris Barsanti from Mid Atlantic. Hope things are going well at the shop. Wanted to follow up on our conversation about the roll - curious if that's something you're still looking at or if the timeline has changed. No pressure either way.`n`nChris Barsanti`nMid Atlantic Machinery"
    },
    @{
        To      = "jwall@fcej.com"
        Subject = "Mid Atlantic - checking in"
        Body    = "Jim - it's been a while. Chris Barsanti from Mid Atlantic. Just wanted to touch base and see how things are going at Flexcom. If anything's come up on the equipment side I'd love to reconnect.`n`nChris Barsanti`nMid Atlantic Machinery"
    },
    @{
        To      = "anibalweldingllc@gmail.com"
        Subject = "Following up - Mid Atlantic Machinery"
        Body    = "Anibal - Chris from Mid Atlantic. We had talked a while back about a used press brake - wanted to check in and see if that's something you're still interested in or if your needs have changed. Happy to chat anytime.`n`nChris Barsanti`nMid Atlantic Machinery"
    },
    @{
        To      = "chuck@ccmfabricators.com"
        Subject = "Quick check-in - Chris Barsanti"
        Body    = "Chuck - Chris Barsanti here from Mid Atlantic. It's been a while since we talked - wanted to see how things are at CCM and if there's anything we can help with on the equipment side.`n`nChris Barsanti`nMid Atlantic Machinery"
    },
    @{
        To      = "lee@radickcorp.com"
        Subject = "Radick - plasma check-in"
        Body    = "Lee - Chris Barsanti from Mid Atlantic. Wanted to follow up on the CNC plasma conversation - has that moved forward at all or is it still in the early stages? Either way, happy to help when the time is right.`n`nChris Barsanti`nMid Atlantic Machinery"
    },
    @{
        To      = "beam@accu-machine.com"
        Subject = "Staying in touch - Mid Atlantic Machinery"
        Body    = "Manjit - Chris Barsanti from Mid Atlantic. Just wanted to check in and see how things are going at Accu Machine. Let me know if there's anything on the equipment front we can help with.`n`nChris Barsanti`nMid Atlantic Machinery"
    },
    @{
        To      = "nyeremian@hmidoors.com"
        Subject = "Mid Atlantic - quick hello"
        Body    = "Noubar - Chris Barsanti from Mid Atlantic. It's been a while - just reaching out to stay on your radar and see if there's anything we can help with on the fabrication equipment side.`n`nChris Barsanti`nMid Atlantic Machinery"
    },
    @{
        To      = "jeff@zellnerwelding.com"
        Subject = "Zellner - plasma follow-up"
        Body    = "Jeff - Chris from Mid Atlantic. Wanted to follow up on the Lonestar plasma - I know we had put together some numbers a while back. Has that moved forward or changed direction? Happy to revisit if it's still on the table.`n`nChris Barsanti`nMid Atlantic Machinery"
    },
    @{
        To      = "paull@activeradiator.com"
        Subject = "Checking in - Mid Atlantic Machinery"
        Body    = "Paul - Chris Barsanti from Mid Atlantic. Hope things are going well at Active Radiator. Just wanted to touch base and see if there's anything on the equipment or processing side we could help with.`n`nChris Barsanti`nMid Atlantic Machinery"
    },
    @{
        To      = "primesheet@aol.com"
        Subject = "Prime Sheet Metal - coil line follow-up"
        Body    = "Dominic - Chris Barsanti from Mid Atlantic. Just wanted to circle back on the coil line conversation - wanted to see if that's still something you're exploring. No rush - just want to make sure I'm helpful when the timing's right.`n`nChris Barsanti`nMid Atlantic Machinery"
    },
    @{
        To      = "martyj@formansign.com"
        Subject = "Mid Atlantic - staying in touch"
        Body    = "Marty - Chris Barsanti from Mid Atlantic. It's been a while - just wanted to check in and see how things are going at Forman Sign. If anything's come up on the equipment side, happy to reconnect.`n`nChris Barsanti`nMid Atlantic Machinery"
    },
    @{
        To      = "dmassari@cfsigns.com"
        Subject = "Quick hello - Mid Atlantic Machinery"
        Body    = "Don - Chris Barsanti from Mid Atlantic. Just reaching out to stay in touch and see if there's anything on the equipment side we can help with at Custom Finishers. Hope things are going well.`n`nChris Barsanti`nMid Atlantic Machinery"
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
