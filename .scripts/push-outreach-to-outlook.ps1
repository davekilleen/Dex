# Push Outreach Drafts to Outlook
# Reads Outreach_Drafts_Week_July_7-11_2026.md and creates draft emails in Outlook
# Run with classic Outlook open (NOT admin PowerShell)
#   . "c:\Users\Chris\Documents\GitHub\dex\.scripts\push-outreach-to-outlook.ps1"

$outlook = New-Object -ComObject Outlook.Application

# Email templates - add as many as needed
$emails = @(
    # URGENT - Monday AM
    @{
        To      = "aaron.fry@myerseps.com"
        Subject = "Cidan CNC Folder — Pricing Extension + ROI Review"
        Body    = @"
Hi Aaron,

Following up on our discussion regarding the Cidan CNC folder ($526,400). Your ROI analysis was due June 30th, and I want to make sure we're still on track to move this forward.

Here's where I am:
- Cidan's discounted pricing was locked through 6/30, but I can check with Doug if we need a brief extension
- I have sample ROI data from similar shops if that would be helpful for your analysis
- Ready to schedule a demo or site visit whenever you need it

Can you give me a quick status? Are we looking at an LOI this week, or do we need to regroup?

Thanks,
Chris Barsanti
Mid Atlantic Machinery
"@
    },

    # HIGH PRIORITY
    @{
        To      = "pfk@kellyiron.com"
        Subject = "Kelly Iron Works — Equipment Roadmap Discussion"
        Body    = @"
Hi Padraig,

I wanted to reach out and see what your roadmap looks like for this year on cutting and fabrication equipment.

I've been tracking a few opportunities that could be a fit for Kelly's growth. Worth a quick call this week to talk through your priorities?

Let me know what works for you.

Thanks,
Chris Barsanti
Mid Atlantic Machinery
"@
    },

    @{
        To      = "gambonesteel@aol.com"
        Subject = "Gambone Steel — EMI Equipment + ALLtra Plasma"
        Body    = @"
Hi Ralph,

Just checking in on two fronts:

1. ALLtra Plasma — Did you get a chance to connect with Randy when he was in the area Thursday 7/2? Still interested in setting up a demo?

2. EMI Equipment — Any updates on the machinery we discussed?

Let me know how I can help move either of these forward.

Thanks,
Chris Barsanti
Mid Atlantic Machinery
"@
    },

    # REPLACEMENT TIMING - SUMMER DEMO DAYS
    @{
        To      = "markb@mbihvac.com"
        Subject = "Time to look at your plasma table, Mark? Fiber has changed the math"
        Body    = @"
Hi Mark,

Your Plasma-Pro table has put in a lot of good years, but it is now past the point where most shops start evaluating a replacement. The move from plasma to fiber laser has changed the economics in a big way - faster cuts, tighter tolerances, and far less consumable cost.

We are running Summer Demo Days every other Thursday this summer, 10am to 2pm, where you can see fiber cutting in person and ask our experts anything. No pressure - just a chance to see where the technology has gone.

Would you be open to stopping by, or should I bring the details to you? Full schedule here: https://midatlanticmachinery.com/events/

Chris Barsanti
Mid Atlantic Machinery
"@
    },

    @{
        To      = "roy.shelton@verizon.net"
        Subject = "Been a while, Roy - lets reconnect"
        Body    = @"
Hi Roy,

It has been too long since we last worked together. I wanted to check in and see what you have going on this year and whether there is any equipment on your radar.

We are hosting Summer Demo Days every other Thursday, 10am to 2pm - a relaxed chance to see our machines run and catch up in person. We are also holding our annual MAM Classic charity golf outing on Monday, September 28th, benefiting the future fabricators at Thaddeus Stevens College. Would love to have you join.

Details on both: https://midatlanticmachinery.com/events/

Give me a call or reply and lets find a time.

Chris Barsanti
Mid Atlantic Machinery
"@
    },

    @{
        To      = "whartman@swmetalproducts.com"
        Subject = "Whitney - press brake bending course + Summer Demo Days"
        Body    = @"
Hi Whitney,

Following up on the press brake conversations we have had. Two things you may want on your calendar:

First, we are hosting a Foundational and Advanced Techniques of Press Brake Bending course at 8:00am on Wednesday, August 26th with expert John Moran - a great fit for your team.

Second, our Summer Demo Days run every other Thursday, 10am to 2pm, if you want to see the latest bending and cutting equipment in person.

Details and registration: https://midatlanticmachinery.com/events/

Want me to hold a couple of spots for your team?

Chris Barsanti
Mid Atlantic Machinery
"@
    },

    @{
        To      = "vaddesa@loadrite.com"
        Subject = "Vito - your plasma table is due for a look"
        Body    = @"
Hi Vito,

Your Praxair plasma table dates back over a decade, which puts it in the window where most shops start weighing a replacement. Fiber laser has come a long way for trailer and plate work - faster throughput, cleaner edges, and much lower operating cost.

We are running Summer Demo Days every other Thursday this summer, 10am to 2pm, where you can see fiber cutting in person. Worth the trip if a replacement is anywhere on your horizon.

Full schedule: https://midatlanticmachinery.com/events/

Want me to walk you through the numbers for your volume?

Chris Barsanti
Mid Atlantic Machinery
"@
    },

    @{
        To      = "tad@fabtechcorp.com"
        Subject = "Todd - fiber vs your ShopSabre plasma"
        Body    = @"
Hi Todd,

Your ShopSabre plasma has served you well, but it is now at the age where a fiber laser upgrade can pay for itself quickly - faster cuts, tighter tolerances, and far less consumable and maintenance cost.

We are hosting Summer Demo Days every other Thursday this summer, 10am to 2pm, where you can see fiber cutting side by side and ask our experts anything. No pressure, just a good look at where things have moved.

Schedule: https://midatlanticmachinery.com/events/

Would you be open to stopping in? I can also come to you.

Chris Barsanti
Mid Atlantic Machinery
"@
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
Write-Host ""
Write-Host "Next steps:"
Write-Host "1. Open Outlook and check your Drafts folder"
Write-Host "2. Review each draft and personalize with specific deal details"
Write-Host "3. Update contact info where needed"
Write-Host "4. Send throughout the week per priority order"
