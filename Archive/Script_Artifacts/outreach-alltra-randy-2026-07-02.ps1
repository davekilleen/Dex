# ALLtra / Randy in-area outreach - Thursday, July 2, 2026
# YOUR accounts only (Account.OwnerId = Chris Barsanti). Colleagues' accounts excluded per territory rule.
# Tier 1: open ALLtra plasma opportunities. Tier 2: your accounts with aging plasma (upgrade/see ALLtra w/ Randy).
# Generated 2026-06-26. Contacts pulled from Salesforce.
#
# HOW TO RUN (classic Outlook open, normal PowerShell - NOT admin):
#   . "c:\Users\Chris\Documents\GitHub\dex\.scripts\outreach-alltra-randy-2026-07-02.ps1"

$outlook = New-Object -ComObject Outlook.Application

$emails = @(
    # ===== TIER 1 - OPEN ALLtra OPPORTUNITIES (active quotes) =====
    @{
        # SMF Truck Equipment - "ALL - plasma" $298,147 - Quote 00019355 - NextStep: schedule virtual mtg w/ Randy
        To      = "abillig@smftruck.com"   # Al Billig
        Subject = "ALLtra Plasma Quote + Randy On-Site Thursday 7/2"
        Body    = "Hi Al,`n`nFollowing up on the ALLtra plasma quote (00019355) we put together - I'd like to keep it moving before the end of the quarter. Good timing on my end: Randy from ALLtra will be back in our area on Thursday, July 2.`n`nThat's a great chance to walk through the US-612 in person, get any technical questions answered straight from the factory, and lock in the final configuration. Would Thursday 7/2 work for a meeting or a live demo? Tell me a window that fits your day and I'll coordinate it with Randy.`n`nThanks,`nChris Barsanti`nMid Atlantic Machinery"
    },
    @{
        # Gambone Steel Company - "ALL - US-612 Plasma - Gambone" $220,873 - Vendor: ALLtra Corp.
        To      = "gambonesteel@aol.com"   # Ralph Gambone
        Subject = "ALLtra US-612 Plasma - Randy Visiting Thursday 7/2"
        Body    = "Hi Ralph,`n`nWanted to circle back on the ALLtra US-612 plasma proposal for Gambone Steel. Randy from ALLtra is going to be back in the area on Thursday, July 2 - perfect timing to get him in front of you to review the system, talk through your throughput, and answer anything still open on the quote.`n`nCould we grab some time Thursday 7/2 for a meeting or demo? Let me know what works and I'll set it up with Randy.`n`nThanks,`nChris Barsanti`nMid Atlantic Machinery"
    },

    # ===== TIER 2 - YOUR ACCOUNTS WITH AGING PLASMA (upgrade / see ALLtra with Randy) =====
    @{
        # Delaware Valley Steel Co - existing ALLtra owner (HG16-12S, ~2021)
        To      = "jerry@delawarevalleysteel.com"   # Jerry Sharpe, President
        Subject = "Randy from ALLtra in the Area Thursday 7/2"
        Body    = "Hi Jerry,`n`nYour ALLtra HG16-12S has been cutting for a few years now - hope it's still running strong. Randy from ALLtra is going to be back in our area Thursday, July 2, so I wanted to reach out.`n`nIt's a good window to talk service, consumables, or where ALLtra's current 12-ft machines have come since you bought. Any interest in a short visit or demo on Thursday 7/2? Happy to work around your schedule.`n`nThanks,`nChris Barsanti`nMid Atlantic Machinery"
    },
    @{
        # Metal Stock, Inc. - Philadelphia PA - Messer plasma 2018
        To      = "tyler@metal-stock.com"   # Tyler Ruth, Operations Manager
        Subject = "ALLtra Plasma - Randy in the Area Thursday 7/2"
        Body    = "Hi Tyler,`n`nYour plasma table dates to 2018, so it's a good time to see how far the technology has come. Randy from ALLtra will be back in our area Thursday, July 2.`n`nALLtra builds a heavy-duty unitized plasma - strong on cut quality, speed, and uptime. If you're open to a quick look or some sample cuts while he's local, I'll set it up. Worth 20 minutes Thursday 7/2?`n`nThanks,`nChris Barsanti`nMid Atlantic Machinery"
    },
    @{
        # Michelman Steel Enterprises - Bethlehem PA - FICEP plasma 2017
        To      = "emichelman@michelmansteel.com"   # Eric Michelman, Owner
        Subject = "ALLtra Plasma - Randy in the Lehigh Valley Thursday 7/2"
        Body    = "Hi Eric,`n`nYour plasma dates to 2017, so it's a good time to benchmark against current tech. Randy from ALLtra will be making visits in the Lehigh Valley area Thursday, July 2.`n`nALLtra's unitized plasma is strong on speed, cut quality, and uptime. Happy to bring him by for a no-pressure look or some sample parts. Worth a quick conversation Thursday 7/2?`n`nThanks,`nChris Barsanti`nMid Atlantic Machinery"
    },
    @{
        # Hazleton Iron, LLC - Hazleton PA - plasma 2019
        To      = "rkrobert@hazletoniron.com"   # Russ Krobert, Shop Supervisor
        Subject = "ALLtra Plasma - Randy in Hazleton Thursday 7/2"
        Body    = "Hi Russ,`n`nYour plasma table is a few years in now (2019), and Randy from ALLtra will be right in the Hazleton area Thursday, July 2.`n`nALLtra builds a rugged unitized plasma - worth a look on cut quality and uptime. If you're open to a quick visit or sample parts, I'll bring him by. Worth 20 minutes Thursday 7/2?`n`nThanks,`nChris Barsanti`nMid Atlantic Machinery"
    },
    @{
        # Kelly Iron Works, Inc. - Hazleton PA - FICEP plasma 2020
        To      = "pfk@kellyiron.com"   # Padraig Kelly, Owner
        Subject = "Randy from ALLtra in Hazleton Thursday 7/2"
        Body    = "Hi Padraig,`n`nYour plasma is fairly recent (2020), but Randy from ALLtra will be in the Hazleton area Thursday, July 2, and I wanted to make the introduction while he's local - useful if you ever weigh a second table or added capacity.`n`nNo pressure at all. Want me to hold a few minutes Thursday 7/2?`n`nThanks,`nChris Barsanti`nMid Atlantic Machinery"
    },
    @{
        # R/J Florig - FICEP plasma 2011 (oldest fab-shop table)
        To      = "jflorig@rjflorig.com"   # Jack Florig, Owner
        Subject = "ALLtra Plasma - Randy in the Area Thursday 7/2"
        Body    = "Hi Jack,`n`nYour plasma table goes back to 2011, so it's really earned a look at what's current. Randy from ALLtra will be back in our area Thursday, July 2.`n`nALLtra builds a heavy-duty unitized plasma - a big step up on cut quality, speed, and uptime versus a table of that vintage. Worth having Randy stop by for a no-pressure look or some sample cuts? Let me know and I'll set it up.`n`nThanks,`nChris Barsanti`nMid Atlantic Machinery"
    },
    @{
        # Chown's Fabrication & Rigging - Promax plasma 2007 (oldest overall)
        To      = "kevinchowns@aol.com"   # Kevin Chowns, President
        Subject = "Time to Look at a New Plasma? Randy from ALLtra Here 7/2"
        Body    = "Hi Kevin,`n`nThat plasma table of yours dates back to 2007 - it's done its time, and the technology has come a long way since. Randy from ALLtra will be back in our area Thursday, July 2.`n`nALLtra's unitized plasma is rugged and a major jump in cut quality and throughput. No pressure - if you'd be open to a look or some sample parts while Randy's local, I'll bring him by. Worth a conversation?`n`nThanks,`nChris Barsanti`nMid Atlantic Machinery"
    },
    @{
        # K & C Machining - Dynatorch plasma 2019
        To      = "kcmach@ptd.net"   # Randy (K & C Machining)
        Subject = "ALLtra Plasma - Randy in the Area Thursday 7/2"
        Body    = "Hi Randy,`n`nYour plasma is a few years in now (2019), and Randy from ALLtra is going to be back in our area Thursday, July 2.`n`nALLtra builds a heavy-duty unitized plasma worth a look on cut quality and uptime. If you're open to a quick visit or some sample cuts while he's local, I'll set it up. Worth 20 minutes Thursday 7/2?`n`nThanks,`nChris Barsanti`nMid Atlantic Machinery"
    },
    @{
        # Gottstein Corporation - Bend-tech plasma 2019 (also active TRUMPF laser discussion)
        To      = "ken@gottsteincorporation.com"   # Ken Gottstein, President
        Subject = "ALLtra Plasma - Randy in the Area Thursday 7/2"
        Body    = "Hi Ken,`n`nAlongside everything else we've been working on, I wanted to flag the plasma side - your table dates to 2019, and Randy from ALLtra will be back in our area Thursday, July 2.`n`nALLtra's unitized plasma is strong on cut quality and uptime if you're ever weighing a refresh or added capacity. Happy to have him stop by for a quick look while he's local. Want me to hold some time Thursday 7/2?`n`nThanks,`nChris Barsanti`nMid Atlantic Machinery"
    },
    @{
        # Goulstone and Roberts Inc - Piranha plasma 2020
        To      = "froberts@goulstoneandrobertsinc.com"   # Francis Roberts, Owner
        Subject = "ALLtra Plasma - Randy in the Area Thursday 7/2"
        Body    = "Hi Francis,`n`nYour plasma is a few years in (2020), and Randy from ALLtra will be back in our area Thursday, July 2.`n`nALLtra builds a rugged unitized plasma worth a look on speed, cut quality, and uptime. No pressure - if a short visit or some sample parts would be useful while Randy's local, I'll bring him by. Worth setting up Thursday 7/2?`n`nThanks,`nChris Barsanti`nMid Atlantic Machinery"
    },
    @{
        # EC Fence & Ironworks - Bend-tech plasma 2020
        To      = "erik@ecfence.net"   # Erik Sims
        Subject = "ALLtra Plasma - Randy in the Area Thursday 7/2"
        Body    = "Hi Erik,`n`nYour plasma is a few years in now (2020), and Randy from ALLtra is going to be back in our area Thursday, July 2.`n`nALLtra's unitized plasma is a strong option on cut quality and uptime as the work grows. If you're open to a quick look or sample cuts while he's local, I'll route him your way. Worth 20 minutes Thursday 7/2?`n`nThanks,`nChris Barsanti`nMid Atlantic Machinery"
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
        Write-Host "OK: $($email.To) - $($email.Subject)" -ForegroundColor Green
        $created++
    } catch {
        Write-Host "FAIL: $($email.To) - $_" -ForegroundColor Red
        $skipped++
    }
}

Write-Host ""
Write-Host "Done: $created drafts created, $skipped failed." -ForegroundColor Cyan
