# Replacement-Timing Outreach - Wave 1 (Tier-2 + aging-plasma Tier-3)
# Part of the H2 2026 Sales Plan / Replacement-Timing campaign.
# Pushes personalized DRAFTS to Outlook. Nothing sends automatically - review each draft, then send.
# Run in a normal PowerShell window (NOT admin), with classic Outlook open:
#   . "c:\Users\Chris\Documents\GitHub\dex\.scripts\outreach-replacement-timing-2026-07-05.ps1"

$outlook = New-Object -ComObject Outlook.Application

$emails = @(
    @{
        To      = "markb@mbihvac.com"
        Subject = "Time to look at your plasma table, Mark? Fiber has changed the math"
        Body    = "Hi Mark,`n`nYour Plasma-Pro table has put in a lot of good years, but it is now past the point where most shops start evaluating a replacement. The move from plasma to fiber laser has changed the economics in a big way - faster cuts, tighter tolerances, and far less consumable cost.`n`nWe are running Summer Demo Days every other Thursday this summer, 10am to 2pm, where you can see fiber cutting in person and ask our experts anything. No pressure - just a chance to see where the technology has gone.`n`nWould you be open to stopping by, or should I bring the details to you? Full schedule here: https://midatlanticmachinery.com/events/`n`nChris Barsanti`nMid Atlantic Machinery"
    },
    @{
        To      = "roy.shelton@verizon.net"
        Subject = "Been a while, Roy - lets reconnect"
        Body    = "Hi Roy,`n`nIt has been too long since we last worked together. I wanted to check in and see what you have going on this year and whether there is any equipment on your radar.`n`nWe are hosting Summer Demo Days every other Thursday, 10am to 2pm - a relaxed chance to see our machines run and catch up in person. We are also holding our annual MAM Classic charity golf outing on Monday, September 28th, benefiting the future fabricators at Thaddeus Stevens College. Would love to have you join.`n`nDetails on both: https://midatlanticmachinery.com/events/`n`nGive me a call or reply and lets find a time.`n`nChris Barsanti`nMid Atlantic Machinery"
    },
    @{
        To      = "tony.sambuca@sutphen.com"
        Subject = "Checking in on Sutphen East fab needs"
        Body    = "Hi Tony,`n`nHope things are busy on the apparatus side. It has been a little while since our last project together and I wanted to see what is coming up for you this year.`n`nWe are running Summer Demo Days every other Thursday, 10am to 2pm - a good chance to see the latest cutting and bending equipment in action. If a machine is on your horizon, this is an easy way to compare options with no pressure.`n`nSchedule and details: https://midatlanticmachinery.com/events/`n`nReply or give me a call and I will get you set up.`n`nChris Barsanti`nMid Atlantic Machinery"
    },
    @{
        To      = "brandongilbert@atube.com"
        Subject = "Anderson Tube - whats on your radar this year?"
        Body    = "Hi Brandon,`n`nWanted to reconnect and see what Anderson Tube has planned for equipment this year. A lot has changed on the cutting and automation side that could be a fit for your tube work.`n`nWe are hosting Summer Demo Days every other Thursday, 10am to 2pm, with hands-on demos and our experts on hand. Worth a look if you are weighing any upgrades.`n`nFull schedule: https://midatlanticmachinery.com/events/`n`nReply or call and lets catch up.`n`nChris Barsanti`nMid Atlantic Machinery"
    },
    @{
        To      = "whartman@swmetalproducts.com"
        Subject = "Whitney - press brake bending course + Summer Demo Days"
        Body    = "Hi Whitney,`n`nFollowing up on the press brake conversations we have had. Two things you may want on your calendar:`n`nFirst, we are hosting a Foundational and Advanced Techniques of Press Brake Bending course at 8:00am on Wednesday, August 26th with expert John Moran - a great fit for your team.`n`nSecond, our Summer Demo Days run every other Thursday, 10am to 2pm, if you want to see the latest bending and cutting equipment in person.`n`nDetails and registration: https://midatlanticmachinery.com/events/`n`nWant me to hold a couple of spots for your team?`n`nChris Barsanti`nMid Atlantic Machinery"
    },
    @{
        To      = "dennis@motorizedsolutions.com"
        Subject = "Reconnecting - DEL Motorized Solutions"
        Body    = "Hi Dennis,`n`nIt has been a bit since we last connected and I wanted to check in on what you have coming up. If any cutting, bending, or automation equipment is on your radar, I would like to help you scope it.`n`nWe are running Summer Demo Days every other Thursday, 10am to 2pm - an easy way to see machines run and ask questions. We also have our MAM Classic charity golf outing on September 28th if you are up for a good cause and a good day out.`n`nDetails: https://midatlanticmachinery.com/events/`n`nReply or call anytime.`n`nChris Barsanti`nMid Atlantic Machinery"
    },
    @{
        To      = "trsweldingandfab@yahoo.com"
        Subject = "TRS Welding - lets catch up"
        Body    = "Hi Mike,`n`nChecking in to see what TRS has going on this year and whether any equipment upgrades are on the table. Happy to be a resource whenever you are planning.`n`nWe are hosting Summer Demo Days every other Thursday, 10am to 2pm, with live demos and our experts available for questions. No pressure - just a chance to see what is new.`n`nSchedule: https://midatlanticmachinery.com/events/`n`nReply or give me a call.`n`nChris Barsanti`nMid Atlantic Machinery"
    },
    @{
        To      = "a.rumovskis@suerteksa.com"
        Subject = "Soti Union - equipment plans for this year?"
        Body    = "Hi Andrius,`n`nWanted to reconnect and learn what Soti Union has planned this year. If cutting or fabrication equipment is on your radar, I would be glad to help you compare options.`n`nWe are running Summer Demo Days every other Thursday, 10am to 2pm - a relaxed way to see the machines in person and talk through your needs.`n`nDetails: https://midatlanticmachinery.com/events/`n`nReply or call and lets set something up.`n`nChris Barsanti`nMid Atlantic Machinery"
    },
    @{
        To      = "vaddesa@loadrite.com"
        Subject = "Vito - your plasma table is due for a look"
        Body    = "Hi Vito,`n`nYour Praxair plasma table dates back over a decade, which puts it in the window where most shops start weighing a replacement. Fiber laser has come a long way for trailer and plate work - faster throughput, cleaner edges, and much lower operating cost.`n`nWe are running Summer Demo Days every other Thursday this summer, 10am to 2pm, where you can see fiber cutting in person. Worth the trip if a replacement is anywhere on your horizon.`n`nFull schedule: https://midatlanticmachinery.com/events/`n`nWant me to walk you through the numbers for your volume?`n`nChris Barsanti`nMid Atlantic Machinery"
    },
    @{
        To      = "tad@fabtechcorp.com"
        Subject = "Todd - fiber vs your ShopSabre plasma"
        Body    = "Hi Todd,`n`nYour ShopSabre plasma has served you well, but it is now at the age where a fiber laser upgrade can pay for itself quickly - faster cuts, tighter tolerances, and far less consumable and maintenance cost.`n`nWe are hosting Summer Demo Days every other Thursday this summer, 10am to 2pm, where you can see fiber cutting side by side and ask our experts anything. No pressure, just a good look at where things have moved.`n`nSchedule: https://midatlanticmachinery.com/events/`n`nWould you be open to stopping in? I can also come to you.`n`nChris Barsanti`nMid Atlantic Machinery"
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
