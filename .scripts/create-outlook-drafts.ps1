$outlook = New-Object -ComObject Outlook.Application

$emails = @(
    @{
        To      = "c.noll@gwyneddmfg.com"
        Subject = "TruLaser 1030 - Two In-Stock Machines Available Now"
        Body    = "Hi Cody,`n`nGood timing on our call last week - I just got the latest TRUMPF availability list and wanted to reach out right away.`n`nThere are two TruLaser 1030 fiber machines in-stock and ready to ship. Both come configured with the Flame Cutting Pack, Internal Mixer, and Gas Mix Pack - production-ready, no wait on a build slot.`n`nGiven where you are in the process, I'd like to get these in front of you before they get reserved. Can we connect this week to go over specs and confirm fit?`n`nTalk soon,`nChris Barsanti`nMid Atlantic Machinery"
    },
    @{
        To      = "rpesotini@psasystems.com"
        CC      = "mduffy@psasystems.com"
        Subject = "TruLaser 1030 - Two In-Stock Machines Available Now"
        Body    = "Hi Ron,`n`nWanted to reach out with a timely update on the TL1030 project.`n`nTRUMPF has two TruLaser 1030 fiber machines in-stock and ready to ship - both configured with the Flame Cutting Pack, Internal Mixer, and Gas Mix Pack. No wait on a production slot; these can move on your timeline.`n`nGiven where we are on the Active Project, this is exactly the kind of opportunity to take advantage of. I'd like to get the details in front of you and Mike before these get reserved by someone else.`n`nAre you available for a quick call this week?`n`nTalk soon,`nChris Barsanti`nMid Atlantic Machinery"
    },
    @{
        To      = "rdepack@asgco.com"
        Subject = "TruLaser 3030 - Available Slots and Freeze Dates"
        Body    = "Hi Ron,`n`nI wanted to share a quick update on TruLaser 3030 availability as we're working through your quote.`n`nThe earliest open (unreserved) delivery slots are November 5 and November 10, with configuration freeze points of August 17 and August 22 respectively. Once we hit those freeze dates, the slots lock - either to us or someone else.`n`nWith a decision this size, I want to make sure you have the runway you need to move. If November delivery works for your timeline, I'd recommend we move to confirm the slot in the next few weeks.`n`nWorth a call this week to align on timing?`n`nBest,`nChris Barsanti`nMid Atlantic Machinery"
    },
    @{
        To      = "jflorig@rjflorig.com"
        Subject = "TruLaser 3030 - Delivery Slots Filling Up"
        Body    = "Hi Jack,`n`nChecking in on the TruLaser 3030 quote - I just pulled the latest availability and wanted to flag timing for you.`n`nThe open delivery slots are going fast. The earliest available dates are November 5 and November 10, with freeze points in mid-August. If you want a Q4 delivery, we need to move on a slot in the next few weeks.`n`nI know you're still evaluating, but I don't want you to end up pushed to Q1 2027 because the Q4 slots filled while we were deciding. Can we jump on a quick call to talk through where you are?`n`nThanks,`nChris Barsanti`nMid Atlantic Machinery"
    },
    @{
        To      = "NEEDEMAIL@ssindustries.com"
        Subject = "TruLaser 5030 - In-Stock Machine, Special Configuration Available"
        Body    = "Hi [Name],`n`nQuick heads-up on something that may be relevant to your laser search.`n`nTRUMPF has a TruLaser 5030 in-stock and ready for immediate shipment - this one is a special configuration with ASC (automatic sorting), EdgeLine Bevel cutting, Camera 2, and SCP. It's a step above the standard build, and because it's in-stock, there's no wait on a production slot.`n`nIf bevel cutting or automated sorting is relevant to what you're running, this could be a unique opportunity to get a higher-spec machine on a shorter timeline. Happy to send over the full spec sheet.`n`nWorth a conversation?`n`nChris Barsanti`nMid Atlantic Machinery`n`nNOTE TO CHRIS: Update recipient before sending - SS Industries contact email needed."
    },
    @{
        To      = "brush@crystalmetalworks.com"
        Subject = "TruLaser 3030/5000 - Availability Update"
        Body    = "Hi Brian,`n`nFollowing up on the TL3000/TL5000 discussion - I pulled the latest TRUMPF availability and wanted to share what's open.`n`nTL3030 (L95 series): Open slots from November 5 onward, freeze points in mid-August.`nTL5030 (L76 series): Open slots from September 9 onward, and there's actually an in-stock 5030 ready for immediate shipment.`n`nIf you've gotten closer to a decision on format, this would be a good time to talk - the slots with near-term delivery are the first to go.`n`nCan we reconnect this week?`n`nChris Barsanti`nMid Atlantic Machinery"
    },
    @{
        To      = "b.leonard@rjrfabrication.com"
        Subject = "Press Brake Training Course - August 26 at Our Showroom"
        Body    = "Hi Bob,`n`nAs we work through the TruBend details, I wanted to extend a personal invite to something that might be useful for you and your team.`n`nWe're hosting a Press Brake Training Course on Tuesday, August 26 at our Mid Atlantic Machinery showroom. It's a hands-on session covering bending fundamentals, tooling selection, part program setup, and tips for getting the most out of a modern CNC press brake.`n`nWhether you're training an operator on a new machine or sharpening your existing team's skills, it's a great day - no cost, just bring the people who run your brake work.`n`nLet me know if you'd like to reserve a few spots. Happy to send details.`n`nTalk soon,`nChris Barsanti`nMid Atlantic Machinery"
    },
    @{
        To      = "jcarr@coxsheetmetal.com"
        Subject = "Press Brake Training - August 26, MAM Showroom"
        Body    = "Hi Joe,`n`nGood talking last week. Wanted to get this on your radar while we're working through the TruBend 1100 decision.`n`nWe're hosting a free Press Brake Training Course on August 26 at our showroom - hands-on, operator-focused, covering everything from tooling setup to programming tips. If you're bringing a new machine in, this is exactly the kind of training your team will want before it hits the floor.`n`nSpots are limited - want me to hold a couple for you?`n`nBest,`nChris Barsanti`nMid Atlantic Machinery"
    },
    @{
        To      = "rfischer@swmetalproducts.com"
        CC      = "whartman@swmetalproducts.com"
        Subject = "Press Brake Training Course - August 26"
        Body    = "Hi Rob,`n`nWith the TruBend Cell 5000 project in progress, I wanted to personally invite you and your team to a Press Brake Training Course we're hosting on August 26 at the Mid Atlantic Machinery showroom.`n`nIt's a hands-on day - bending theory, tooling, programming, and operator best practices. For a system like the Cell 5000, having well-trained operators from day one makes a real difference in ROI. No charge, just bring the people who'll be running it.`n`nWould love to have you there. Can I hold a few spots?`n`nChris Barsanti`nMid Atlantic Machinery"
    },
    @{
        To      = "toddb@ziamatic.com"
        Subject = "Press Brake Training - August 26 @ MAM Showroom"
        Body    = "Hi Todd,`n`nFollowing up on our brake conversation - wanted to make sure you saw this.`n`nWe're hosting a Press Brake Training Course on Tuesday, August 26 at our showroom. Hands-on, no cost - covers tooling, bending fundamentals, CNC programming, and getting consistent results. Great for operators whether they're on a new machine or an older one.`n`nGiven where you are in evaluating options, it's also a nice chance to come see what's new on the showroom floor. Let me know if you want to bring a couple people - happy to hold spots.`n`nTalk soon,`nChris Barsanti`nMid Atlantic Machinery"
    },
    @{
        To      = "sbearden@alpinemetal.com"
        Subject = "Press Brake Training Course - August 26"
        Body    = "Hi Steve,`n`nGreat connecting on the WILA tooling last week. Since you're clearly running active brake work, I wanted to make sure you knew about this:`n`nWe're hosting a free Press Brake Training Course on August 26 at our showroom. Hands-on day - tooling selection (including WILA best practices), bending fundamentals, and CNC setup tips. The kind of session that helps your operators get more consistent results and reduce scrap.`n`nWant to bring your brake team? Happy to hold a couple spots.`n`nChris Barsanti`nMid Atlantic Machinery"
    },
    @{
        To      = "aaron.fry@myerseps.com"
        CC      = "ray.brue@myerseps.com"
        Subject = "Press Brake Training - August 26, MAM Showroom"
        Body    = "Hi Aaron,`n`nGood talking last week. Wanted to loop you in on this while we're in the middle of the TruBend conversation.`n`nWe're running a Press Brake Training Course on August 26 at our showroom - hands-on, no charge. Great for operators getting ready to step up to a new CNC brake or anyone looking to tighten up their bending process.`n`nWould be a great chance for your team to get a feel for the equipment before a purchase decision too. Want me to hold a few spots?`n`nBest,`nChris Barsanti`nMid Atlantic Machinery"
    },
    @{
        To      = "bcrist@haletrailer.com"
        Subject = "Press Brake Training Course - August 26 @ MAM Showroom"
        Body    = "Hi Bryan,`n`nAs we get closer on the press brake, I wanted to flag an event you might find useful for your team.`n`nWe're hosting a Press Brake Training Course on August 26 at the Mid Atlantic Machinery showroom - hands-on, free, covering bending fundamentals, tooling, and getting the most out of a modern CNC brake.`n`nPerfect timing before a new machine comes in. Want me to hold a couple spots for you?`n`nChris Barsanti`nMid Atlantic Machinery"
    },
    @{
        To      = "chad.pantelich@dvmpower.com"
        CC      = "rob.schmidt@dvmpower.com"
        Subject = "Press Brake Training - August 26, MAM Showroom"
        Body    = "Hi Chad,`n`nWith the press brake projects we've been working on, I thought this might be great timing.`n`nWe're hosting a free Press Brake Training Course on Tuesday, August 26 at our showroom. Hands-on day - tooling, programming, bending fundamentals. Ideal for operators who'll be running new equipment.`n`nWant to bring your team? Can hold a few spots.`n`nChris Barsanti`nMid Atlantic Machinery"
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
Write-Host "NOTE: Update SS Industries recipient before sending." -ForegroundColor Yellow
