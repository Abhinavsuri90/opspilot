"""Send a fictional test email with a PDF attachment to the local Mailpit SMTP server.

The worker's email intake polls Mailpit for ``<slug>@opspilot.local``; this script is the
development stand-in for a vendor emailing a document. Run it on the host (Mailpit listens
on localhost:1025) or inside the compose network (``--host mailpit``).
"""

import argparse
import os
import smtplib
import sys
from email.message import EmailMessage
from pathlib import Path

DEFAULT_PDF = Path(__file__).resolve().parents[1] / "examples" / "northwind-invoice.pdf"


def build_message(
    *, sender: str, recipient: str, subject: str, body: str, pdf_path: Path
) -> EmailMessage:
    message = EmailMessage()
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)
    message.add_attachment(
        pdf_path.read_bytes(),
        maintype="application",
        subtype="pdf",
        filename=pdf_path.name,
    )
    return message


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--org", default="northwind", help="Organization slug (recipient)")
    parser.add_argument("--to", help="Explicit recipient address; overrides --org")
    parser.add_argument("--from", dest="sender", default="vendor@example.com")
    parser.add_argument("--subject", default="Invoice attached")
    parser.add_argument(
        "--body", default="Hello,\nplease find the document attached.\nRegards, Accounts"
    )
    parser.add_argument("--pdf", type=Path, default=DEFAULT_PDF)
    parser.add_argument("--host", default=os.environ.get("MAILPIT_SMTP_HOST", "localhost"))
    parser.add_argument(
        "--port", type=int, default=int(os.environ.get("MAILPIT_SMTP_PORT", "1025"))
    )
    args = parser.parse_args()
    if not args.pdf.exists():
        print(f"PDF not found: {args.pdf}", file=sys.stderr)
        return 2
    recipient = args.to or f"{args.org}@opspilot.local"
    message = build_message(
        sender=args.sender,
        recipient=recipient,
        subject=args.subject,
        body=args.body,
        pdf_path=args.pdf,
    )
    with smtplib.SMTP(args.host, args.port, timeout=10) as smtp:
        smtp.send_message(message)
    print(f"Sent {args.pdf.name} to {recipient} via {args.host}:{args.port}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
