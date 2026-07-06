# Sent-Mail Tracking — Power Automate Setup

This is a **manual, one-time setup** you do inside [make.powerautomate.com](https://make.powerautomate.com) — there's no code to run. It adds a second flow that feeds your **Sent Items** into the `mam-email-triage` worker so Dex can tell you which customer emails are still waiting on a reply.

Outlook's connector has no "when an email is sent" trigger, so this flow polls Sent Items on a schedule instead of firing instantly like the inbound flow does.

---

## Step 1 — Update the existing inbound flow first

Open your current "Email Triage" flow (the one that fires on **When a new email arrives**) and set the JSON body it POSTs to `/ingest-email` to this. The two additions that matter for reply tracking are `message_id` and `conversation_id`:

```json
{
  "received_at": "@{triggerOutputs()?['body/receivedDateTime']}",
  "sender_email": "@{triggerOutputs()?['body/from']}",
  "sender_name": "@{triggerOutputs()?['body/sender']?['name']}",
  "subject": "@{triggerOutputs()?['body/subject']}",
  "body_preview": "@{triggerOutputs()?['body/bodyPreview']}",
  "full_body": "@{triggerOutputs()?['body/body']}",
  "message_id": "@{triggerOutputs()?['body/internetMessageId']}",
  "conversation_id": "@{triggerOutputs()?['body/conversationId']}",
  "has_attachment": @{if(equals(triggerOutputs()?['body/hasAttachments'], true), true, false)}
}
```

**Use Internet Message Id, not Message Id.** The picker offers both:

| Field | What it is | Use it? |
|-------|-----------|---------|
| **Message Id** (`messageId`/`id`) | Microsoft Graph's internal id | ❌ Mailbox- and folder-scoped — changes when the message moves, and differs between your mailbox and the recipient's. Useless for correlating a send with its reply. |
| **Internet Message Id** (`internetMessageId`) | The RFC 2822 `Message-ID` header | ✅ Globally stable, identical across mailboxes, survives folder moves. The canonical identifier for threading. |

The underlying JSON path for these varies by connector version, so **pick "Internet Message Id" and "Conversation Id" from the dynamic-content chip** rather than trusting the hand-typed path — that guarantees they resolve instead of silently posting `null`. Both are exposed by the Office 365 Outlook trigger with no extra permissions.

Reply matching keys on `conversation_id` (with an email-address fallback), so that's the field that actually flips a sent email to "replied." `message_id` is stored for audit and future message-level threading — which is exactly why it needs to be the durable Internet Message Id.

Save the flow.

---

## Step 2 — Create the new "Sent Mail Sync" flow

1. **Create** → **Automated cloud flow** → name it `Sent Mail Sync` → skip the trigger picker, click **Skip**.
2. **Trigger:** Add **Recurrence** — Interval `30`, Frequency `Minute`.
3. **Action:** Add **Get emails (V3)** (Office 365 Outlook connector)
   - Folder: `Sent Items`
   - Top: `15`
   - Fetch Only Unread Items: `No`
   - **Leave Search Query empty.** It uses KQL, which filters only by *date* (it can't express "last N minutes"), and a malformed query makes the whole action fail — which then skips the loop with "No dependent action succeeded."

4. **Action:** Add a single **Apply to each** loop (**Control → Apply to each**) — the *only* loop you need; don't nest a second one.
   - In **"Select an output from previous steps,"** pick **value** from "Get emails (V3)" (the array of email records).
   - **Inside** that loop, add **one HTTP** action — nothing else. It fires one POST per sent email. If you added an HTTP action earlier that sits *before* the loop, delete it.

   The finished tail:
   ```
   Get emails (V3)
   Apply to each          ← over Get emails "value"
      └─ HTTP             ← the only action inside
   ```

   No checkpoint, no Condition. Every run re-fetches the last 15 sent items and POSTs them; the worker rejects anything already stored with a harmless **409** (its UNIQUE key is the email's receive timestamp + sender + subject + direction). Because dedup relies on that timestamp being stable, `received_at` **must** be the email's real date field (below) — not `utcNow()`, which would change every run and create duplicates.

   **Confirmed field names** (from live "Get emails (V3)" output): `receivedDateTime`, `from` (plain email string), `toRecipients` (semicolon-separated string), `subject`, `bodyPreview`, `body`, `internetMessageId`, `conversationId`. Note there is **no** `sentDateTime` and **no** `sentDateTime`-style array of recipient objects.

   **Optional — skip re-posts with a Condition:** if the re-posting bothers you (each repeat costs one Salesforce lookup on the worker), add an **Initialize variable** `checkpoint` = `@{addMinutes(utcNow(),-35)}` before the loop, then wrap the HTTP in a **Condition**: `ticks(item()?['receivedDateTime'])` **is greater than** `ticks(variables('checkpoint'))`, HTTP in the **If yes** branch. Use `receivedDateTime` here too — not `sentDateTime`.

   Now configure the HTTP action:
     - Method: `POST`
     - URI: `https://mam-email-triage.cbarsanti.workers.dev/ingest-email`
     - Headers — **the key is just the name, with no trailing colon** (the colon you see below is the display separator, not part of the key):

       | Key | Value |
       |-----|-------|
       | `Authorization` | `Bearer <same API_KEY used by the inbound flow>` |
       | `Content-Type` | `application/json` |
     - Body:
       ```json
       {
         "received_at": "@{item()?['receivedDateTime']}",
         "sender_email": "@{item()?['from']}",
         "subject": "@{item()?['subject']}",
         "body_preview": "@{item()?['bodyPreview']}",
         "full_body": "@{item()?['body']}",
         "direction": "sent",
         "recipient_email": "@{trim(first(split(item()?['toRecipients'], ';')))}",
         "message_id": "@{item()?['internetMessageId']}",
         "conversation_id": "@{item()?['conversationId']}"
       }
       ```

     **`item()` vs `items('Apply_to_each')`:** `item()` means "the current loop item" and doesn't depend on the loop's name, so it can't break if the designer titled the loop "For each" instead of "Apply to each." Prefer it.

     **Don't trust the field names above — confirm them with the picker.** The property names vary by connector version; a wrong one silently resolves to `null`. For each value, click the field, open **Dynamic content**, and pick it from "Get emails (V3)" so Power Automate inserts the exact property. The three that most often differ:
     - **`received_at`** — use **`receivedDateTime`.** "Get emails (V3)" does **not** return a `sentDateTime` field at all (confirmed against live output), so any reference to it resolves to `null` and fails `ticks()`/the POST. This field is required *and* is the dedup key, so a null here fails the whole POST (400).
     - **`message_id`** — use **Internet Message Id**, not Message Id (see the table in Step 1).
     - **`recipient_email`** — "Get emails (V3)" exposes **To** as a *semicolon-separated string* (e.g. `a@b.com; c@d.com`), not an array. `trim(first(split(..., ';')))` pulls the first address. If the path differs, insert **To** from the chip and wrap it the same way.

5. **Save** the flow, then run it manually once (**Run** → **Run flow**) to confirm it completes without errors.

---

## Step 3 — Test it end-to-end

1. Send a real email to a known Salesforce contact.
2. Wait for the next "Sent Mail Sync" run (up to 30 min), or trigger it manually.
3. Confirm the email shows up:
   ```bash
   curl -H "Authorization: Bearer <API_KEY>" \
     "https://mam-email-triage.cbarsanti.workers.dev/emails?direction=sent&limit=5"
   ```
   You should see `"reply_status": "awaiting_reply"` on the row (only if the recipient matched a Salesforce contact — unmatched recipients aren't tracked).
4. Have that contact (or reply from a second mailbox you control) reply to the same thread.
5. Wait for the **inbound** flow to process the reply, then re-check the same email — `reply_status` should now read `"replied"`.

---

## Troubleshooting

- **"No dependent action succeeded" on Apply to each:** the loop wasn't the failure — it got *skipped* because the step before it (Get emails (V3)) didn't succeed. Open the run and click **Get emails (V3)** to see the real error. The usual culprit is a leftover **Search Query** (see Step 3 — it should be empty).
- **`ticks`/`received_at` fails with "provided value is of type 'Null'":** a date field resolved to `null`. "Get emails (V3)" doesn't return `sentDateTime` at all — use **`receivedDateTime`** everywhere (both the Condition, if you added one, and `received_at` in the body). Check the Condition expression specifically; it's easy to fix `received_at` in the body but leave `sentDateTime` in the Condition.
- **Every body field posts empty / worker returns 400 on required fields:** the dynamic-content expressions got cleared from the HTTP body (a common paste artifact). Re-enter the body and confirm each value is an actual `@{item()?['…']}` expression, not blank. Only `direction` is a literal string.
- **Duplicate ingestion errors (409):** normal if the recurrence overlap picks up an email already sent — safe to ignore, the worker's UNIQUE constraint rejects the dupe.
- **`recipient_email is required for sent emails` (400):** the `recipient_email` expression returned `null` or empty. Usually the **To** field path is wrong for your connector version — re-insert **To** from the dynamic-content chip and keep the `trim(first(split( … , ';')))` wrapper. (A genuinely empty To, e.g. a BCC-only send, will also hit this; those are rare and safe to let fail.)
- **`message_id` is blank on stored rows:** you picked "Message Id" instead of "Internet Message Id", or the hand-typed `internetMessageId` path doesn't match your connector. Re-insert it from the chip. This won't break reply matching (that runs on `conversation_id`), but the stored id won't be useful for threading.
- **`reply_status` stays `awaiting_reply` after a real reply:** check that both flows are actually passing `conversation_id` — if either one drops it, the worker falls back to matching on `recipient_email`, which still works but only ties to the most recent unanswered thread with that contact.
- **Flow run history shows the HTTP action failing with 401:** two common causes — (1) the header key was entered as `Authorization:` with a trailing colon (it must be just `Authorization`; the colon is the separator, not part of the name); or (2) the token doesn't match the worker's `API_KEY`. Confirm which secrets are set with `npx wrangler secret list` from `extensions/mam-email-triage/` (the value itself isn't retrievable, only the name).

See also: `POWER_AUTOMATE.md` and `INTEGRATION.md` in this folder for the original inbound-flow setup this builds on.
