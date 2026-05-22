import os
import base64
import uuid
from django.shortcuts import render, redirect
from django.views import View
from django.http import JsonResponse
from django.utils import timezone
from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.files.base import ContentFile

from core.models import Attendance, EmployeeProfile, User
from .utils import haversine_distance

class ClockInOutView(LoginRequiredMixin, View):
    def get(self, request):
        try:
            profile = request.user.employee_profile
        except EmployeeProfile.DoesNotExist:
            return render(request, 'attendance/error.html', {'message': 'No employee profile linked.'})
            
        today = timezone.now().date()
        attendance = Attendance.objects.filter(profile=profile, date=today).first()
        
        status = 'in' if attendance and attendance.in_time and not attendance.out_time else 'out'
        
        context = {
            'status': status,
            'department': profile.department,
            'attendance': attendance
        }
        return render(request, 'attendance/clock.html', context)

    def post(self, request):
        try:
            profile = request.user.employee_profile
        except EmployeeProfile.DoesNotExist:
            return JsonResponse({'success': False, 'message': 'No profile found'}, status=400)

        data = request.POST
        action = data.get('action') # 'in' or 'out'
        lat = data.get('latitude')
        lon = data.get('longitude')
        face_b64 = data.get('face_image')
        
        dept = profile.department

        # 1. Validity: Strict Geofence for GPS
        is_valid = True
        location_name = "AEC Group"
        
        AUTHORIZED_LOCATIONS = [
            {"name": "AEC Group", "lat": 9.967283003625232, "lon": 76.28662859325976},
            {"name": "AEC Group", "lat": 9.967283003625232, "lon": 76.28662859325976},
            {"name": "AEC Group", "lat": 9.967283003625232, "lon": 76.28662859325976},
            {"name": "AEC Group", "lat": 9.498526389705322, "lon": 76.34305504232113},
            {"name": "AEC Group", "lat": 9.506290068630923, "lon": 76.34089742310876},
            {"name": "AEC Group", "lat": 9.506567290951638, "lon": 76.34080264948254},
        ]
        
        if lat and lon:
            from .utils import haversine_distance
            min_dist = float('inf')
            closest_loc_name = None
            
            for loc in AUTHORIZED_LOCATIONS:
                d_dist = haversine_distance(float(lat), float(lon), loc['lat'], loc['lon'])
                if d_dist < min_dist:
                    min_dist = d_dist
                    closest_loc_name = loc['name']
                    
            if min_dist <= 250:
                is_valid = True
                location_name = closest_loc_name
            else:
                return JsonResponse({
                    'success': False, 
                    'message': 'You are not within the 250-meter radius of an authorized location. Please ensure you are on-site to Clock In/Out.'
                }, status=400)
        else:
            # No GPS (desktop / laptop) → check IP whitelist
            if dept.allowed_ips:
                client_ip = request.META.get('REMOTE_ADDR', '')
                allowed = [ip.strip() for ip in dept.allowed_ips.split(',') if ip.strip()]
                is_valid = client_ip in allowed
                if not is_valid:
                    return JsonResponse({
                        'success': False, 
                        'message': 'You are not on the authorized office network.'
                    }, status=400)
            else:
                # Require GPS if no IP restriction is set to prevent remote bypass
                return JsonResponse({
                    'success': False, 
                    'message': 'Location access is required. Please enable GPS to Clock In/Out.'
                }, status=400)

        # 2. Save Face Image
        face_image_path = ""
        if face_b64:
            try:
                format, imgstr = face_b64.split(';base64,') 
                ext = format.split('/')[-1]
                filename = f"{profile.employee_id}_{timezone.now().strftime('%Y%m%d%H%M%S')}.{ext}"
                file_path = os.path.join(settings.MEDIA_ROOT, 'attendance_faces', filename)
                os.makedirs(os.path.dirname(file_path), exist_ok=True)
                with open(file_path, "wb") as fh:
                    fh.write(base64.b64decode(imgstr))
                face_image_path = os.path.join('media', 'attendance_faces', filename)
            except Exception:
                pass

        user_agent = request.META.get('HTTP_USER_AGENT', '').lower()
        is_mobile = 'mobi' in user_agent or 'android' in user_agent or 'iphone' in user_agent

        # 3. Create or Update Attendance
        today = timezone.now().date()
        attendance, created = Attendance.objects.get_or_create(
            profile=profile,
            date=today,
            defaults={
                'source': Attendance.ClockSource.MOBILE if is_mobile else Attendance.ClockSource.DESKTOP,
                'ip_address': request.META.get('REMOTE_ADDR')
            }
        )
        
        attendance.gps_latitude = lat
        attendance.gps_longitude = lon
        attendance.face_image_path = face_image_path
        attendance.is_valid = is_valid
        attendance.location_name = location_name
        
        if action == 'in':
            if not attendance.in_time:
                attendance.in_time = timezone.now()
                # Late-coming logic: Shift start at 9:30 AM. 15 mins grace (up to 9:45 AM is not late)
                if not dept.is_cinema:
                    local_in = timezone.localtime(attendance.in_time)
                    shift_start_local = local_in.replace(hour=9, minute=30, second=0, microsecond=0)
                    from datetime import timedelta
                    grace = timedelta(minutes=15)
                    
                    if local_in > (shift_start_local + grace):
                        attendance.is_late = True
                        late_diff = local_in - shift_start_local
                        attendance.late_minutes = int(late_diff.total_seconds() / 60)
                    else:
                        attendance.is_late = False
                        attendance.late_minutes = 0
                    
                    # Count occurrences
                    late_count = Attendance.objects.filter(
                        profile=profile,
                        date__year=today.year,
                        date__month=today.month,
                        is_late=True
                    ).count()
                    
                    if late_count == 1:  # This will be the 2nd occurrence once saved
                        try:
                            from twofa.emails import send_html_mail
                            send_html_mail(
                                subject="Warning: Repeated Late Coming",
                                template_name="attendance/email_late_warning.html",
                                context={'profile': profile, 'time': local_time.strftime("%I:%M %p")},
                                to=[profile.user.email]
                            )
                        except Exception:
                            pass
        elif action == 'out':
            attendance.out_time = timezone.now()
            
        attendance.save()
        
        return JsonResponse({
            'success': True, 
            'message': f"Clocked {action} successfully",
            'is_valid': is_valid
        })

class DashboardView(LoginRequiredMixin, View):
    def get(self, request):
        user = request.user
        context = {}

        if user.role in [User.Role.MD, User.Role.HR, User.Role.DEPT_HEAD]:
            from core.models import Department
            import datetime

            today = timezone.now().date()
            first_of_month = today.replace(day=1)

            # --- Filters ---
            dept_filter = request.GET.get('dept_filter', '')
            date_from_str = request.GET.get('date_from', '')
            date_to_str = request.GET.get('date_to', '')

            try:
                date_from = datetime.date.fromisoformat(date_from_str) if date_from_str else first_of_month
            except ValueError:
                date_from = first_of_month
            try:
                date_to = datetime.date.fromisoformat(date_to_str) if date_to_str else today
            except ValueError:
                date_to = today

            # Clamp ordering
            if date_from > date_to:
                date_from, date_to = date_to, date_from

            qs = Attendance.objects.filter(
                date__gte=date_from, date__lte=date_to
            ).exclude(profile__user__role=User.Role.MD).select_related('profile__user', 'profile__department')

            if user.role == User.Role.DEPT_HEAD:
                depts = Department.objects.filter(is_active=True, head=user).order_by('name')
                qs = qs.filter(profile__department__in=depts)
            else:
                depts = Department.objects.filter(is_active=True).order_by('name')

            if dept_filter:
                qs = qs.filter(profile__department_id=dept_filter)

            qs = qs.order_by('profile__department__name', 'profile__employee_id', '-date')

            context['attendances'] = qs
            context['is_manager'] = True
            context['date_from'] = date_from
            context['date_to'] = date_to
            context['dept_filter'] = dept_filter

            # Departments for filter dropdown
            context['departments'] = depts

            # Manageable employees for manual attendance entry (exclude MD)
            if user.role == User.Role.DEPT_HEAD:
                context['manageable_employees'] = EmployeeProfile.objects.filter(is_active=True, probation_status__in=[EmployeeProfile.ProbationStatus.PROBATION, EmployeeProfile.ProbationStatus.PERMANENT], department__in=depts).exclude(user__role=User.Role.MD).select_related('user').order_by('user__first_name')
            else:
                context['manageable_employees'] = EmployeeProfile.objects.filter(is_active=True, probation_status__in=[EmployeeProfile.ProbationStatus.PROBATION, EmployeeProfile.ProbationStatus.PERMANENT]).exclude(user__role=User.Role.MD).select_related('user').order_by('user__first_name')

            # Heatmap aggregation: per department -> present vs total active (always today)
            today_att = Attendance.objects.filter(date=today).select_related(
                'profile__department'
            )
            labels, presents, totals = [], [], []
            for d in depts:
                total_emp = d.employees.filter(is_active=True, probation_status__in=[EmployeeProfile.ProbationStatus.PROBATION, EmployeeProfile.ProbationStatus.PERMANENT]).exclude(user__role=User.Role.MD).count()
                if total_emp == 0:
                    continue
                present_emp = today_att.filter(
                    profile__department=d,
                    in_time__isnull=False,
                    is_valid=True,
                ).count()
                labels.append(d.code)
                presents.append(present_emp)
                totals.append(total_emp)
            context['heatmap_labels'] = labels
            context['heatmap_present'] = presents
            context['heatmap_total'] = totals

            # --- Monthly Summary Department-wise Report ---
            monthly_summary_by_dept = []
            target_depts = depts.filter(id=dept_filter) if dept_filter else depts

            for dept in target_depts:
                work_days_set = set(dept.get_work_days_list())
                curr_date = date_from
                total_work_days = 0
                while curr_date <= date_to:
                    if curr_date.weekday() in work_days_set:
                        total_work_days += 1
                    curr_date += datetime.timedelta(days=1)

                dept_employees = dept.employees.filter(is_active=True, probation_status__in=[EmployeeProfile.ProbationStatus.PROBATION, EmployeeProfile.ProbationStatus.PERMANENT]).exclude(user__role=User.Role.MD).select_related('user')
                dept_att = qs.filter(profile__department=dept)

                emp_summaries = []
                for emp in dept_employees:
                    emp_att = dept_att.filter(profile=emp)
                    days_present = emp_att.filter(in_time__isnull=False).count()
                    days_absent = max(0, total_work_days - days_present)
                    late_count = emp_att.filter(is_late=True).count()
                    att_percentage = round((days_present / total_work_days * 100)) if total_work_days > 0 else 0

                    emp_summaries.append({
                        'employee': emp,
                        'days_present': days_present,
                        'days_absent': days_absent,
                        'late_count': late_count,
                        'total_work_days': total_work_days,
                        'att_percentage': att_percentage,
                    })

                if emp_summaries:
                    monthly_summary_by_dept.append({
                        'department': dept,
                        'emp_summaries': emp_summaries,
                        'total_work_days': total_work_days,
                    })

            context['monthly_summary_by_dept'] = monthly_summary_by_dept

        else:
            # Staff View: Personal history
            try:
                profile = user.employee_profile
                context['attendances'] = Attendance.objects.filter(profile=profile).order_by('-date')[:30]
                context['is_manager'] = False
            except EmployeeProfile.DoesNotExist:
                context['attendances'] = []
                context['is_manager'] = False

        return render(request, 'attendance/dashboard.html', context)


class LivePresenceView(LoginRequiredMixin, View):
    """JSON endpoint polled every 30s by the dashboard to refresh
    the heatmap / map without a page reload."""
    def get(self, request):
        from core.models import Department

        if request.user.role not in [User.Role.MD, User.Role.HR, User.Role.DEPT_HEAD]:
            return JsonResponse({'error': 'forbidden'}, status=403)

        today = timezone.now().date()
        todays = Attendance.objects.filter(date=today, in_time__isnull=False).exclude(
            profile__user__role=User.Role.MD
        ).select_related(
            'profile__user', 'profile__department'
        )
        if request.user.role == User.Role.DEPT_HEAD:
            todays = todays.filter(profile__department__head=request.user)

        depts = Department.objects.filter(is_active=True).order_by('name')
        labels, presents, totals = [], [], []
        for d in depts:
            total_emp = d.employees.filter(is_active=True, probation_status__in=[EmployeeProfile.ProbationStatus.PROBATION, EmployeeProfile.ProbationStatus.PERMANENT]).exclude(user__role=User.Role.MD).count()
            if total_emp == 0:
                continue
            labels.append(d.code)
            presents.append(todays.filter(profile__department=d, is_valid=True).count())
            totals.append(total_emp)

        markers = [
            {
                'name': r.profile.user.get_full_name(),
                'dept': r.profile.department.code,
                'lat': float(r.gps_latitude) if r.gps_latitude else None,
                'lon': float(r.gps_longitude) if r.gps_longitude else None,
                'in': r.in_time.isoformat() if r.in_time else None,
                'out': r.out_time.isoformat() if r.out_time else None,
                'is_late': r.is_late,
            }
            for r in todays if r.gps_latitude and r.gps_longitude
        ]

        return JsonResponse({
            'as_of': timezone.now().isoformat(),
            'labels': labels,
            'present': presents,
            'total': totals,
            'markers': markers,
        })


class ManualAttendanceView(LoginRequiredMixin, View):
    def post(self, request):
        from django.contrib import messages
        import datetime

        if request.user.role not in [User.Role.MD, User.Role.HR, User.Role.DEPT_HEAD]:
            messages.error(request, "Unauthorized access.")
            return redirect('attendance:dashboard')

        profile_id = request.POST.get('profile_id')
        date_str = request.POST.get('date')
        in_time_str = request.POST.get('in_time')
        out_time_str = request.POST.get('out_time')
        reason = request.POST.get('reason', '').strip()

        if not (profile_id and date_str and in_time_str):
            messages.error(request, "Employee, Date, and In Time are required.")
            return redirect('attendance:dashboard')

        try:
            target_profile = EmployeeProfile.objects.get(pk=profile_id, is_active=True, probation_status__in=[EmployeeProfile.ProbationStatus.PROBATION, EmployeeProfile.ProbationStatus.PERMANENT])
        except EmployeeProfile.DoesNotExist:
            messages.error(request, "Selected employee profile not found.")
            return redirect('attendance:dashboard')

        # Check permissions for DEPT_HEAD
        if request.user.role == User.Role.DEPT_HEAD:
            if target_profile.department.head != request.user:
                messages.error(request, "You can only edit attendance for your own department staff.")
                return redirect('attendance:dashboard')

        # Parse date and times
        try:
            att_date = datetime.date.fromisoformat(date_str)
            in_time_parsed = datetime.datetime.combine(att_date, datetime.time.fromisoformat(in_time_str))
            in_time_aware = timezone.make_aware(in_time_parsed) if timezone.is_naive(in_time_parsed) else in_time_parsed
            
            out_time_aware = None
            if out_time_str:
                out_time_parsed = datetime.datetime.combine(att_date, datetime.time.fromisoformat(out_time_str))
                out_time_aware = timezone.make_aware(out_time_parsed) if timezone.is_naive(out_time_parsed) else out_time_parsed
        except ValueError:
            messages.error(request, "Invalid date or time format.")
            return redirect('attendance:dashboard')

        attendance, created = Attendance.objects.get_or_create(
            profile=target_profile,
            date=att_date,
            defaults={
                'source': Attendance.ClockSource.MANUAL,
            }
        )

        attendance.in_time = in_time_aware
        attendance.out_time = out_time_aware
        attendance.source = Attendance.ClockSource.MANUAL
        attendance.is_valid = True

        # Check late logic
        from datetime import time
        local_in_time = timezone.localtime(attendance.in_time).time()
        if local_in_time > time(9, 15) and not target_profile.department.is_cinema:
            attendance.is_late = True
        else:
            attendance.is_late = False

        # Note format requested by user
        role_display = request.user.get_role_display()
        note = f"Manually added by {request.user.get_full_name()} ({role_display}). Reason: {reason}"
        attendance.location_name = note[:200]
        attendance.save()

        # Log audit action
        from core.models import AuditLog
        try:
            AuditLog.objects.create(
                profile=target_profile,
                performed_by=request.user,
                action=AuditLog.ActionType.ATTENDANCE_IN,
                details={'note': note, 'date': date_str, 'in_time': in_time_str, 'out_time': out_time_str}
            )
        except Exception:
            pass

        messages.success(request, f"Manual attendance successfully logged for {target_profile.user.get_full_name()} on {date_str}.")
        return redirect('attendance:dashboard')