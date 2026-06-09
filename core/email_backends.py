import json
import urllib.request
import base64
import email.utils
from django.core.mail.backends.base import BaseEmailBackend
from django.conf import settings

class BrevoEmailBackend(BaseEmailBackend):
    def send_messages(self, email_messages):
        if not email_messages:
            return 0
        
        api_key = getattr(settings, 'BREVO_API_KEY', None)
        if not api_key:
            print("BREVO_API_KEY not set in settings")
            return 0
            
        num_sent = 0
        for message in email_messages:
            try:
                # Process sender ("Name <email>" -> name, email)
                sender_name, sender_email = email.utils.parseaddr(message.from_email)
                if not sender_email:
                    sender_email = message.from_email
                if not sender_name:
                    sender_name = "wolan Hr HR"

                sender_payload = {"name": sender_name, "email": sender_email}

                # Process recipients
                to_payload = []
                for rcpt in message.to:
                    r_name, r_email = email.utils.parseaddr(rcpt)
                    if not r_email:
                        r_email = rcpt
                    to_payload.append({"email": r_email})
                
                if not to_payload:
                    continue

                payload = {
                    "sender": sender_payload,
                    "to": to_payload,
                    "subject": message.subject,
                }
                
                # Check for HTML alternative
                html_body = None
                if hasattr(message, 'alternatives'):
                    for alt in message.alternatives:
                        if alt[1] == 'text/html':
                            html_body = alt[0]
                            break
                            
                if html_body:
                    payload["htmlContent"] = html_body
                    payload["textContent"] = message.body
                else:
                    payload["textContent"] = message.body

                # Process attachments
                attachments = []
                if hasattr(message, 'attachments') and message.attachments:
                    for attachment in message.attachments:
                        if isinstance(attachment, tuple):
                            filename, content, mimetype = attachment
                            if isinstance(content, str):
                                content = content.encode('utf-8')
                            b64_content = base64.b64encode(content).decode('ascii')
                            attachments.append({
                                "content": b64_content,
                                "name": filename
                            })
                
                if attachments:
                    payload["attachment"] = attachments

                req = urllib.request.Request(
                    "https://api.brevo.com/v3/smtp/email",
                    data=json.dumps(payload).encode('utf-8'),
                    headers={
                        "api-key": api_key,
                        "Content-Type": "application/json",
                        "Accept": "application/json"
                    },
                    method="POST"
                )
                
                with urllib.request.urlopen(req, timeout=15) as response:
                    if response.status in [200, 201, 202]:
                        num_sent += 1
                    else:
                        print(f"Brevo API failed with status {response.status}: {response.read()}")
            except Exception as e:
                print(f"Brevo API error: {e}")
                if not self.fail_silently:
                    raise e
                    
        return num_sent
