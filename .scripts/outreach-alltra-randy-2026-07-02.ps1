# ALLtra / Randy in-area outreach - Thursday, July 2, 2026
# Follow-up on open ALLtra plasma opportunities + re-engage existing older ALLtra plasma owners (UCC-1 EDA report)
# Generated 2026-06-26. Confirm email addresses marked NEEDEMAIL before running.
#
# HOW TO RUN (on Chris's Windows machine, classic Outlook open, normal PowerShell - NOT admin):
#   . "c:\Users\Chris\Documents\GitHub\dex\.scripts\outreach-alltra-randy-2026-07-02.ps1"

$outlook = New-Object -ComObject Outlook.Application

$emails = @(
    # ===== TIER 1 - OPEN ALLtra OPPORTUNITIES (active quotes) =====
    @{
        # SMF Truck Equipment - "ALL - plasma" $298,147 - Quote 00019355 (Customer) - NextStep: schedule virtual mtg w/ Randy
        To      = "NEEDEMAIL@smftruck.com"   # Al Billig - confirm address
        Subject = "ALLtra Plasma Quote + Randy On-Site Thursday 7/2"
        Body    = "Hi Al,`n`nFollowing up on the ALLtra plasma quote (00019355) we put together - I'd like to keep it moving before the end of the quarter. Good timing on my end: Randy from ALLtra will be back in our area on Thursday, July 2.`n`nThat's a great chance to walk through the US-612 in person, get any technical questions answered straight from the factory, and lock in the final configuration. Would Thursday 7/2 work for a meeting or a live demo? Tell me a window that fits your day and I'll coordinate it with Randy.`n`nThanks,`nChris Barsanti`nMid Atlantic Machinery"
    },
    @{
        # Gambone Steel Company - "ALL - US-612 Plasma - Gambone" $220,873 - Vendor: ALLtra Corp.
        To      = "NEEDEMAIL@gambonesteel.com"   # Ralph Gambone - confirm address
        Subject = "ALLtra US-612 Plasma - Randy Visiting Thursday 7/2"
        Body    = "Hi Ralph,`n`nWanted to circle back on the ALLtra US-612 plasma proposal for Gambone Steel. Randy from ALLtra is going to be back in the area on Thursday, July 2 - perfect timing to get him in front of you to review the system, talk through your throughput, and answer anything still open on the quote.`n`nCould we grab some time Thursday 7/2 for a meeting or demo? Let me know what works and I'll set it up with Randy.`n`nThanks,`nChris Barsanti`nMid Atlantic Machinery"
    },

    # ===== TIER 2 - EXISTING ALLtra PLASMA OWNERS, OLDER MACHINES (2021, ~5 yrs) - UCC-1 EDA report =====
    @{
        # Atlantic Metal Products Inc - ALLtra HG-16-10, installed/purchased 2021-09-20
        To      = "NEEDEMAIL@atlanticmetalproducts.com"   # confirm contact + address
        Subject = "ALLtra Back in the Area Thursday 7/2 - Your HG-16-10"
        Body    = "Hi [Contact],`n`nHope the ALLtra HG-16-10 has been earning its keep since 2021. Randy from ALLtra will be back in our area on Thursday, July 2, and I wanted to give you first crack at some of his time.`n`nWhether it's a tune-up conversation, consumables and parts, or looking at added capacity as the work grows, it's a good chance to have the factory rep on-site. Would Thursday 7/2 work for a quick visit or a look at the latest ALLtra systems? Let me know and I'll set it up.`n`nThanks,`nChris Barsanti`nMid Atlantic Machinery"
    },
    @{
        # Delaware Valley Steel Co - ALLtra HG16-12S-480v, 2021-02-05
        To      = "NEEDEMAIL@dvsteel.com"   # confirm contact + address
        Subject = "Randy from ALLtra in the Area Thursday 7/2"
        Body    = "Hi [Contact],`n`nYour ALLtra HG16-12S has been cutting for a few years now - hope it's still running strong. Randy from ALLtra is going to be back in our area Thursday, July 2, so I wanted to reach out.`n`nIt's a good window to talk service, consumables, or where ALLtra's current 12-ft machines have come since you bought. Any interest in a short visit or demo on Thursday 7/2? Happy to work around your schedule.`n`nThanks,`nChris Barsanti`nMid Atlantic Machinery"
    },
    @{
        # Protech Mechanical Inc - ALLtra US-612 480V, 2021-12-06
        To      = "NEEDEMAIL@protechmechanical.com"   # confirm contact + address
        Subject = "ALLtra On-Site Thursday 7/2 - Checking In on Your US-612"
        Body    = "Hi [Contact],`n`nWanted to touch base on the ALLtra US-612 you've been running since 2021. Randy from ALLtra will be back in the area on Thursday, July 2.`n`nIf you've been thinking about parts, a refresh, or adding capacity, it's a good chance to get time with the factory rep face to face. Would Thursday 7/2 work for a quick meeting or demo? Let me know and I'll get it on the calendar.`n`nThanks,`nChris Barsanti`nMid Atlantic Machinery"
    },
    @{
        # Steel Corp (Parent-RedGuard) - ALLtra PG-14 (sn 7217), 2021-09-27
        To      = "NEEDEMAIL@redguard.com"   # confirm contact + address
        Subject = "Randy from ALLtra Visiting Thursday 7/2"
        Body    = "Hi [Contact],`n`nHope the ALLtra PG-14 has been treating you well. Randy from ALLtra is going to be back in our area Thursday, July 2, and I wanted to see if you'd like to connect while he's here.`n`nGood opportunity to talk service, consumables, or what's new in the ALLtra lineup if you're weighing more capacity. Would Thursday 7/2 work for a short visit or demo? Just say the word and I'll line it up.`n`nThanks,`nChris Barsanti`nMid Atlantic Machinery"
    },
    @{
        # Wiker Welding - ALLtra PG 14-6 Premium, 2021-05-26
        To      = "NEEDEMAIL@wikerwelding.com"   # confirm contact + address
        Subject = "ALLtra in the Area Thursday 7/2 - Your PG 14-6"
        Body    = "Hi [Contact],`n`nThe ALLtra PG 14-6 has a few years on it now - hope it's still cutting clean. Randy from ALLtra will be back in our area Thursday, July 2, so I wanted to reach out.`n`nWhether it's consumables, a service check, or a look at the newer ALLtra systems, it's a good chance to get the factory rep in front of you. Any interest in a quick visit or demo Thursday 7/2? Let me know what works.`n`nThanks,`nChris Barsanti`nMid Atlantic Machinery"
    },
    @{
        # LaserForm & Machine, Inc. - ALLtra PG-14, 2021-06-07
        To      = "NEEDEMAIL@laserformmachine.com"   # confirm contact + address
        Subject = "Randy from ALLtra Back Thursday 7/2 - Quick Hello"
        Body    = "Hi [Contact],`n`nWanted to check in on the ALLtra PG-14 you've had since 2021. Randy from ALLtra is going to be back in the area on Thursday, July 2.`n`nIf parts, service, or added cutting capacity have been on your mind, it's a good time to get the factory rep on-site. Would Thursday 7/2 work for a short visit or demo? Happy to fit your schedule.`n`nThanks,`nChris Barsanti`nMid Atlantic Machinery"
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
        Write-Host "OK: $($email.Subject)" -ForegroundColor Green
        $created++
    } catch {
        Write-Host "FAIL: $($email.Subject) - $_" -ForegroundColor Red
        $skipped++
    }
}

Write-Host ""
Write-Host "Done: $created drafts created, $skipped failed." -ForegroundColor Cyan
Write-Host "Reminder: replace all NEEDEMAIL@ addresses and [Contact] names before sending." -ForegroundColor Yellow
