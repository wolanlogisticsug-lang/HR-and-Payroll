"""Approve/Finalize/PDF integration test (run after main pytest)."""
import re, requests, sys
BASE='https://489d41fa-fbc6-49f2-9560-ced4ced3827a.preview.emergentagent.com'

def login(u,p):
    s=requests.Session(); s.headers.update({'Referer': BASE+'/accounts/login/'})
    r=s.get(BASE+'/accounts/login/')
    csrf=re.search(r'name=["\']csrfmiddlewaretoken["\']\s+value=["\']([^"\']+)', r.text).group(1)
    s.post(BASE+'/accounts/login/', data={'username':u,'password':p,'csrfmiddlewaretoken':csrf,'next':'/dashboard/'})
    return s

md=login('md_wolan Hr','adminpassword123')

# Get fresh CSRF
r=md.get(BASE+'/payroll/?year=2026&month=8')
csrf=re.search(r'name=["\']csrfmiddlewaretoken["\']\s+value=["\']([^"\']+)', r.text).group(1)

# Approve pk=5 (HR Aug2026)
ra=md.post(BASE+'/payroll/approve/5/', data={'action':'approve','csrfmiddlewaretoken':csrf},
           headers={'Referer':BASE+'/payroll/'}, allow_redirects=False)
print('APPROVE status_code=', ra.status_code, 'Location=', ra.headers.get('Location'))
assert ra.status_code in (302,303), 'approve failed'

# Slip PDF as MD with profile_id=2 (HR)
rs=md.get(BASE+'/payroll/slip/2026/8/?profile_id=2')
print('SLIP status=', rs.status_code, 'CT=', rs.headers.get('Content-Type'), 'size=', len(rs.content))
assert rs.status_code == 200
assert rs.headers.get('Content-Type','').startswith('application/pdf')
assert rs.content[:4] == b'%PDF'
assert len(rs.content) > 1000
print('PDF OK')

# Finalize
r=md.get(BASE+'/payroll/?year=2026&month=8')
csrf=re.search(r'name=["\']csrfmiddlewaretoken["\']\s+value=["\']([^"\']+)', r.text).group(1)
rf=md.post(BASE+'/payroll/approve/5/', data={'action':'finalize','csrfmiddlewaretoken':csrf},
           headers={'Referer':BASE+'/payroll/'}, allow_redirects=False)
print('FINALIZE status=', rf.status_code)
assert rf.status_code in (302,303)

# Add incentive as MD
r=md.get(BASE+'/payroll/?year=2026&month=8')
csrf=re.search(r'name=["\']csrfmiddlewaretoken["\']\s+value=["\']([^"\']+)', r.text).group(1)
ri=md.post(BASE+'/payroll/incentive/add/', data={
    'profile_id':'2','incentive_type':'BONUS','amount':'500','year':'2026','month':'8',
    'csrfmiddlewaretoken':csrf,
}, headers={'Referer':BASE+'/payroll/'}, allow_redirects=False)
print('INCENTIVE_ADD status=', ri.status_code, 'Location=', ri.headers.get('Location'))
assert ri.status_code in (302,303)

print('ALL APPROVE/FINALIZE/PDF/INCENTIVE FLOWS OK')
