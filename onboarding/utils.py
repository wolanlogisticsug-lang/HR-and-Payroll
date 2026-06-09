import os
from io import BytesIO
from django.conf import settings
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from django.urls import reverse

def send_onboarding_email(candidate, request=None):
    """Sends onboarding email to candidate with unique link."""
    # Assuming twofa.emails.send_html_mail is available
    try:
        from twofa.emails import send_html_mail
        path = reverse('onboarding:candidate_form', kwargs={'token': candidate.id})
        if request:
            link = request.build_absolute_uri(path)
        else:
            link = f"http://127.0.0.1:8000{path}"
        send_html_mail(
            subject="wolan Hr - Onboarding Invitation",
            template_name="onboarding/email_invite.html", # Optional if template doesn't exist it might fail, fallback:
            context={'candidate': candidate, 'link': link},
            to=[candidate.email]
        )
        return True, ""
    except Exception as e:
        print(f"Failed to send email: {e}")
        return False, str(e)
def generate_official_joining_letter(profile):
    """
    Generates a PDF official joining letter for the employee.
    Returns the binary PDF data.
    """
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    # wolan Hr Branding
    c.setFillColor(colors.HexColor('#1a56db')) # Tailwind blue-600
    c.setFont("Helvetica-Bold", 24)
    c.drawString(50, height - 80, "wolan Hr")
    
    c.setFillColor(colors.black)
    c.setFont("Helvetica", 12)
    c.drawString(50, height - 100, f"Department: {profile.department.name}")

    c.setFont("Helvetica-Bold", 16)
    c.drawString(50, height - 150, "OFFICIAL JOINING LETTER")

    c.setFont("Helvetica", 12)
    c.drawString(50, height - 190, f"Date: {profile.date_of_joining.strftime('%Y-%m-%d') if profile.date_of_joining else 'N/A'}")
    c.drawString(50, height - 210, f"To: {profile.user.get_full_name()}")
    c.drawString(50, height - 230, f"Employee ID: {profile.employee_id}")

    text = c.beginText(50, height - 270)
    text.setFont("Helvetica", 12)
    text.setLeading(18)
    
    body = [
        f"Dear {profile.user.first_name},",
        "",
        f"We are pleased to welcome you to wolan Hr in the {profile.department.name} department.",
        "Your employment is subject to the terms and conditions discussed.",
        "",
        "Key terms:",
        "1. Probation Period: You are currently on probation. Salary will be",
        f"   credited to your personal account: {profile.personal_account}.",
        "2. Notice Period: A hardcoded 1-month (30 days) notice period applies",
        "   to all employees prior to resignation.",
        "3. Standard operations and policies apply as per wolan Hr norms.",
        "",
        "Welcome aboard!",
        "",
        "Authorized Signatory",
        "Managing Director / HR",
        "wolan Hr"
    ]
    
    for line in body:
        text.textLine(line)
        
    c.drawText(text)
    c.showPage()
    c.save()
    
    pdf_data = buffer.getvalue()
    buffer.close()
    
    # Optionally save to disk as well
    filename = f"joining_letter_{profile.employee_id}.pdf"
    file_path = os.path.join(settings.MEDIA_ROOT, 'joining_letters', filename)
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with open(file_path, 'wb') as f:
        f.write(pdf_data)
        
    return pdf_data, os.path.join('media', 'joining_letters', filename)
