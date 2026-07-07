$outlook = New-Object -ComObject Outlook.Application

$emails = @(
    @{
        To      = "aaron.fry@myerseps.com"
        Subject = "Thursday Summer Demo Days - Stop by this week"
        Body    = "Hi Aaron,`n`nI wanted to personally invite you to stop by our showroom this Thursday for our Summer Demo Days from 10:00am to 2:00pm. We will have live equipment running and a chance to see some of the latest cutting and bending options up close. Given the work your team does, I think it could be a useful visit if you are evaluating equipment or looking at productivity improvements. If you are interested, I can reserve a spot for you and help coordinate around your schedule.`n`nThanks,`nChris Barsanti`nMid Atlantic Machinery"
    },
    @{
        To      = "matthew.orehek@myerseps.com"
        Subject = "Thursday Summer Demo Days - Invitation"
        Body    = "Hi Matthew,`n`nI wanted to invite you to our Summer Showroom Demo Days this Thursday from 10:00am to 2:00pm. We will have live equipment running and our team on hand to answer technical questions. It is a good chance to compare what is new in the market without any pressure and see a few different solutions side by side. If you have a few hours to stop by, I would be glad to help you plan around it.`n`nThanks,`nChris Barsanti`nMid Atlantic Machinery"
    },
    @{
        To      = "NEEDEMAIL@bgcinc.com"
        Subject = "Thursday Summer Demo Days - Invitation for BGC"
        Body    = "Hi [Contact Name],`n`nI wanted to invite the BGC team to our Summer Showroom Demo Days this Thursday from 10:00am to 2:00pm. We will have live equipment running and our team on hand to answer questions about cutting and bending solutions. Since your team is active in water and wastewater work and has had recent equipment conversations, I thought this could be a useful low-pressure chance to see what is new and compare options. If you would like to stop by, let me know and I can reserve a spot for you.`n`nThanks,`nChris Barsanti`nMid Atlantic Machinery"
    },
    @{
        To      = "NEEDEMAIL@delmotorized.com"
        Subject = "Thursday Summer Demo Days - Invitation"
        Body    = "Hi [Contact Name],`n`nI wanted to personally invite you to our Summer Showroom Demo Days this Thursday from 10:00am to 2:00pm. We will have live equipment running and a chance to look at current options for cutting and bending without any pressure. Given the equipment conversations we have had, I thought this could be a good opportunity to reconnect and see what is new in the showroom. If you are interested, I would be happy to reserve a spot for you.`n`nThanks,`nChris Barsanti`nMid Atlantic Machinery"
    }
)

$created = 0
$skipped = 0

foreach ($email in $emails) {
    try {
        $mail = $outlook.CreateItem(0)
        $mail.To = $email.To
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
