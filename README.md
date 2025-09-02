# workmail-catchall

A fully serverless, MIME-safe catch-all email forwarding system for Amazon WorkMail using AWS-native services.

Many organizations using Amazon WorkMail want a way to catch emails sent to **any address** at their domain — even if that address doesn’t exist — and forward them to a single inbox. Unfortunately, WorkMail does not support native catch-all routing.

**`workmail-catchall`** solves this by combining:

- ✅ **Amazon SES (Email Receiving)** to accept and route mail
- ✅ **Amazon S3** to store raw MIME email content
- ✅ **AWS Lambda** to rewrite and forward email using SES
- ✅ **Amazon WorkMail** to also deliver locally

This setup provides:

- 🔁 Reliable forwarding from any `*@example.com` address
- 🔒 Header rewriting to avoid spoofing and bounce loops
- 💌 Clean delivery of HTML emails and attachments

Whether you're migrating from another email provider or just want a better way to consolidate inbound email, this project gives you a battle-tested, cloud-native solution — with no third-party services, and no user management required.

---

## Architecture

Incoming email to *@example.com
│
▼
Amazon SES (Receipt Rule)

S3 action → saves raw MIME to s3://`ses-inbound-bucket-example`/<messageId>\
Lambda → rewrites headers safely and forwards with SES SendRawEmail\
WorkMail → (optional) also deliver to catchall@example.com

Why S3?
- Direct SES→Lambda events don’t include the raw MIME.
- Reliable copy for debugging/auditing, plus easy lifecycle cleanup.

---

## Prerequisites

- `example.com` **verified** in SES for **Email Receiving** (MX records set to SES in your region).
- An **Amazon WorkMail** org with user `catchall@example.com`.
- SES sending identity: either the **domain** `example.com` or the **address** `admin@example.awsapps.com` (used for technical `From:` rewrite) is **verified** in SES.
- IAM access to create S3 policies, Lambda role/policies, and SES receipt rules.

---

## WorkMail Setup
Create an Amazon WorkMail organization (if you don’t have one)\
Create a user, e.g., catchall@example.com

## S3 Setup
Go to S3 → Create Bucket
- Name: `ses-inbound-bucket-example`
- Region: Same as SES email receiving region

Add bucket policy to allow SES + Lambda access
- Use **policies/s3-bucket-policy-ses-put.json**
- also add **policies/s3-bucket-policy-lambda-read.json**

(Optional) Add lifecycle rule to auto-delete emails after N days

## Lambda Setup
Create a new Lambda function:
- Name: `ses-catchall-forwarder`
- Runtime: Python 3.11 or newer
- Paste in **lambda/lambda_function.py** code

Set environment variables:
- SES_S3_BUCKET = `ses-inbound-bucket-example`
- (optional) SES_S3_PREFIX = (empty unless using prefixes)

Attach IAM role lambda-ses-catchall-role with:
- policies/lambda-exec-inline.json
- policies/lambda-exec-trust.json

## SES Setup
Go to SES → Configuration → Email Receiving\
Create or edit a receipt rule:
- Recipients: *@example.com
- Add actions (in order):
- - S3 — store to `ses-inbound-bucket-example`
- - Lambda — call `ses-catchall-forwarder`
- - WorkMail — optionally also deliver to catchall@example.com

Enable the rule set (if not already active)

## Lambda behavior

- Forwards **all recipients** at example.com to catchall@example.com.
- **Skips forwarding** when:
  - Destination is already catchall@example.com (prevents loops).
  - Sender equals admin@example.awsapps.com (technical forwarder identity).
  - Sender is in IGNORE_EMAILS.
- **MIME-safe** header rewrite using Python’s email library:
  - Sets From: "<original_sender> <admin@example.awsapps.com>"
  - Sets/overwrites Reply-To: <original_sender>
  - Removes transport/auth headers: Return-Path, DKIM-Signature, X-SES-*, etc.

---

## Testing

- **Real test**: send an email to any non-existent user at `example.com`, e.g. `random123@example.com`.  
  Expect delivery to `catchall@example.com`.
- **Manual Lambda test event**: use `examples/ses-event-test.json` (matches SES→Lambda structure).  
  The function will try to fetch the raw MIME from S3 using `mail.messageId`.

---

## Debug

If emails aren't forwarding or you need to troubleshoot:

**Access Lambda logs**:
- Go to **AWS Lambda** → `ses-catchall-forwarder` function
- Click **Monitor** tab → **View CloudWatch logs**
- Or go directly to **CloudWatch** → **Log groups** → `/aws/lambda/ses-catchall-forwarder`

**Check S3 bucket**:
- Verify emails are being stored in `ses-inbound-bucket-example`
- Each email creates an object with the SES message ID

---

## Cleanup & costs

- Enable an S3 **Lifecycle rule** to auto-delete stored emails after N days.  
- SES receiving, S3 storage/requests, Lambda invocations, and WorkMail mailbox incur standard AWS charges.

---

## Security notes

- Bucket policy grants `ses.amazonaws.com` **PutObject** limited by your **account ID**.
- Lambda role only needs `s3:GetObject` (and maybe `s3:ListBucket`) for that bucket and `ses:SendRawEmail`.
- If S3 uses **SSE-KMS**, grant `kms:Decrypt` to the Lambda role and include the role in the KMS key policy.

---

## Final Thoughts

This solution fills a surprising gap in AWS WorkMail's feature set. Catch-all email forwarding is such a fundamental need for organizations that it's puzzling why it's not built-in.

The workaround using SES + Lambda works well, but it does feel like we're engineering around a missing feature. Perhaps there are business reasons since WorkMail's per-user pricing model might make catch-all less attractive from AWS's perspective.

That said, this serverless approach has some advantages over traditional catch-all implementations. You get a complete audit trail in S3, flexible header rewriting to prevent delivery issues, and easy modification of forwarding logic without touching mail server configs.

While it requires a bit of setup, once running it's been reliable and maintenance-free. The combination of AWS services creates a robust solution that handles MIME complexity better than simple forwarding rules.

Hopefully this helps other organizations bridge the gap until AWS adds native catch-all support. If you find this useful or have improvements, contributions are welcome!

---

## License

MIT
