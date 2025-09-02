import boto3
import json
import os
from typing import Tuple, Optional
from email import message_from_string
from email.policy import default

# --- Config (edit these for your env) ---
DEFAULT_EMAIL = "catchall@example.com"
ADMIN_EMAIL   = "admin@example.awsapps.com"
VERIFIED_EMAILS = {"catchall@example.com"}
IGNORE_EMAILS   = set("spammer@gmail.com")

S3_BUCKET = os.getenv("SES_S3_BUCKET", "")
S3_PREFIX = os.getenv("SES_S3_PREFIX", "")

FILTER_HEADERS = {
    "Return-Path",
    "Reply-To",
    "DKIM-Signature",
    "Received-SPF",
    "Authentication-Results",
    "X-SES-RECEIPT",
    "X-SES-DKIM-SIGNATURE",
}

ses = boto3.client("ses")
s3  = boto3.client("s3")

def parse_from_and_subject(mail_obj: dict) -> Tuple[str, str, str]:
    headers = mail_obj.get("headers", [])
    from_header = next((h for h in headers if h["name"].lower() == "from"), None)
    subject_header = next((h for h in headers if h["name"].lower() == "subject"), None)

    from_value = from_header["value"] if from_header else "unknown@domain.com"
    subject    = subject_header["value"] if subject_header else "No Subject"

    label = from_value
    if "<" in from_value and ">" in from_value:
        parts = from_value.split("<", 1)
        label = parts[0].strip()
        from_value = parts[1].split(">", 1)[0].strip()
    return label, from_value, subject

def filter_content_mime_safe(raw_content: str, new_from: str, reply_to: str) -> str:
    msg = message_from_string(raw_content, policy=default)

    if msg["From"]:
        msg.replace_header("From", f"{reply_to} <{new_from}>")
    else:
        msg["From"] = f"{reply_to} <{new_from}>"

    if msg["Reply-To"]:
        msg.replace_header("Reply-To", reply_to)
    else:
        msg["Reply-To"] = reply_to

    for h in list(msg.keys()):
        if h in FILTER_HEADERS:
            del msg[h]

    return msg.as_string()

def send_raw_email(content: bytes | str, source: str, destination: str):
    if isinstance(content, str):
        content = content.encode("utf-8", errors="replace")
    return ses.send_raw_email(
        Source=source,
        Destinations=[destination],
        RawMessage={"Data": content},
    )

def load_raw_from_s3(message_id: str) -> str:
    if not S3_BUCKET:
        raise RuntimeError("SES_S3_BUCKET not set")
    key = f"{S3_PREFIX}{message_id}"
    print(f"Fetching from S3: s3://{S3_BUCKET}/{key}")
    obj = s3.get_object(Bucket=S3_BUCKET, Key=key)
    return obj["Body"].read().decode("utf-8", errors="replace")

def extract_ses_event(event: dict) -> Tuple[dict, dict, Optional[str]]:
    if event.get("Records") and "Sns" in event["Records"][0]:
        msg = json.loads(event["Records"][0]["Sns"]["Message"])
        return msg.get("mail", {}), msg.get("receipt", {}), msg.get("content")
    if event.get("Records") and "ses" in event["Records"][0]:
        ses_obj = event["Records"][0]["ses"]
        return ses_obj.get("mail", {}), ses_obj.get("receipt", {}), None
    return event.get("mail", {}), event.get("receipt", {}), event.get("content")

def lambda_handler(event, context):
    try:
        mail, receipt, content = extract_ses_event(event)

        destinations = mail.get("destination", [])
        original_destination = destinations[0] if destinations else None
        original_label, original_from, original_subject = parse_from_and_subject(mail)

        verified = set(VERIFIED_EMAILS) | {ADMIN_EMAIL, DEFAULT_EMAIL}

        if not original_from or not original_destination:
            print("Missing required fields")
            return {"disposition": "STOP_RULE"}

        if original_from == ADMIN_EMAIL:
            print("Already forwarded; stopping.")
            return {"disposition": "STOP_RULE"}

        if original_destination in verified:
            print(f"Verified email to {original_destination}; letting it pass.")
            return {"disposition": "CONTINUE"}

        if original_from in IGNORE_EMAILS:
            print(f"Ignoring from: {original_from}")
            return {"disposition": "STOP_RULE"}

        raw_content = content
        if raw_content is None:
            message_id = mail.get("messageId")
            if not message_id:
                raise RuntimeError("No raw content (no SNS content and no messageId).")
            raw_content = load_raw_from_s3(message_id)

        new_content = filter_content_mime_safe(raw_content, ADMIN_EMAIL, original_from)

        print(f"Forwarding {original_destination} → {DEFAULT_EMAIL}")
        resp = send_raw_email(new_content, source=original_destination, destination=DEFAULT_EMAIL)
        print("SES send_raw_email response:", resp)
        return {"disposition": "STOP_RULE"}

    except Exception as e:
        print("Error processing SES message:", repr(e))
        raise
