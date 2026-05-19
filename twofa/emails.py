"""HTML email helper. Renders a Django template + sends via Django's
EmailMultiAlternatives. In dev (DEBUG=True), the console backend prints
both plain-text and html parts."""
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags


def send_html_mail(subject, template_name, context, to, from_email=None, attachments=None):
    """
    template_name: template path under /app/templates (e.g. "email/leave_request.html")
    context:       dict passed to the template
    to:            list of recipient emails
    """
    from django.conf import settings
    from_email = from_email or f"AEC HR <{settings.DEFAULT_FROM_EMAIL}>"
    html_body = render_to_string(template_name, context)
    text_body = strip_tags(html_body)
    msg = EmailMultiAlternatives(str(subject), text_body, from_email, to)
    msg.attach_alternative(html_body, "text/html")
    for fname, content, mime in (attachments or []):
        msg.attach(fname, content, mime)
    def send_task():
        try:
            msg.send(fail_silently=False)
        except Exception as e:
            print(f"Background email failed: {e}")
            
    import threading
    threading.Thread(target=send_task, daemon=True).start()
    return True
