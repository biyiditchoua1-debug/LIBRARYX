from django.views import View
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse, JsonResponse
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse

from .utils import generate_flyer_preview_bytes, generate_flyer_pdf_bytes, generate_flyer_image
from .models import StudentRegistration, FinancialAdjustment
import difflib
import re


def normalize_name(text):
    text = (text or '').lower()
    text = re.sub(r'[^\w\s]', '', text)
    return ' '.join(text.split())


def compute_name_similarity(name1, name2):
    """
    Computes strict similarity score between two name strings.
    Returns (ratio: float, is_exact: bool).
    """
    norm1 = normalize_name(name1)
    norm2 = normalize_name(name2)

    if not norm1 or not norm2:
        return 0.0, False

    if norm1 == norm2:
        return 1.0, True

    if len(norm1) < 3 or len(norm2) < 3:
        return 0.0, False

    seq_ratio = difflib.SequenceMatcher(None, norm1, norm2).ratio()

    t1 = {t for t in norm1.split() if len(t) > 2}
    t2 = {t for t in norm2.split() if len(t) > 2}

    if t1 and t2:
        if t1 == t2:
            return 0.98, False

        common = t1 & t2
        diff1 = t1 - common
        diff2 = t2 - common

        if diff1 and diff2:
            diff_sim = False
            for d1 in diff1:
                for d2 in diff2:
                    if difflib.SequenceMatcher(None, d1, d2).ratio() >= 0.82:
                        diff_sim = True
                        break
            if not diff_sim:
                return 0.0, False

        overlap_ratio = len(common) / float(max(len(t1), len(t2)))

        if len(common) >= 2 and overlap_ratio >= 0.75 and seq_ratio >= 0.80:
            final_ratio = max(seq_ratio, overlap_ratio)
        elif len(common) == 1 and seq_ratio >= 0.88:
            final_ratio = seq_ratio
        elif seq_ratio >= 0.88:
            final_ratio = seq_ratio
        else:
            final_ratio = 0.0
    else:
        final_ratio = seq_ratio if seq_ratio >= 0.88 else 0.0

    final_ratio = round(final_ratio, 2)
    return final_ratio, (final_ratio == 1.0)


# In-memory ignored duplicate pairs
IGNORED_DUPLICATE_PAIRS = set()


def get_student_amount(student):
    """Calculates individual total fee for a student."""
    total = 0
    if student.toge:
        total += 5000
    if student.echarpe:
        total += 3000
    if student.frais_soutenance:
        total += 2000 if student.niveau == 'N2' else 2500
    return total


# ── AUTHENTICATION VIEWS ───────────────────────────────────────────────

class AdminLoginView(View):
    """Admin Login view."""

    def get(self, request):
        if request.user.is_authenticated:
            return redirect('generator:dashboard')
        next_url = request.GET.get('next', reverse('generator:dashboard'))
        return render(request, 'generator/login.html', {'next_url': next_url})

    def post(self, request):
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '').strip()
        next_url = request.POST.get('next') or reverse('generator:dashboard')

        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            return redirect(next_url)

        return render(request, 'generator/login.html', {
            'error_message': 'Identifiant ou mot de passe incorrect.',
            'next_url': next_url
        })


class AdminLogoutView(View):
    """Admin Logout view."""

    def get(self, request):
        logout(request)
        return redirect('generator:home')

    def post(self, request):
        logout(request)
        return redirect('generator:home')


# ── PUBLIC FLYER GENERATOR VIEWS ──────────────────────────────────────

class FlyerFormView(View):
    """Renders the main flyer generator page."""

    def get(self, request):
        return render(request, 'generator/flyer_form.html')


class FlyerPreviewView(View):
    """Returns a JPEG preview image of the flyer."""

    def post(self, request):
        form_data = {
            'full_name': request.POST.get('full_name', ''),
            'classe': request.POST.get('classe', ''),
            'theme': request.POST.get('theme', ''),
            'academic_supervisor': request.POST.get('academic_supervisor', ''),
            'professional_supervisor': request.POST.get('professional_supervisor', ''),
            'filiere': request.POST.get('filiere', 'SR'),
            'niveau': request.POST.get('niveau', 'N3'),
            'template_choice': request.POST.get('template_choice', ''),
        }
        photo_file = request.FILES.get('photo', None)

        try:
            image_bytes = generate_flyer_preview_bytes(form_data, photo_file)
            return HttpResponse(image_bytes, content_type='image/jpeg')
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)


class FlyerDownloadView(View):
    """Returns a high-quality A4 PNG of the flyer for download."""

    def post(self, request):
        import io
        form_data = {
            'full_name': request.POST.get('full_name', ''),
            'classe': request.POST.get('classe', ''),
            'theme': request.POST.get('theme', ''),
            'academic_supervisor': request.POST.get('academic_supervisor', ''),
            'professional_supervisor': request.POST.get('professional_supervisor', ''),
            'filiere': request.POST.get('filiere', 'SR'),
            'niveau': request.POST.get('niveau', 'N3'),
            'template_choice': request.POST.get('template_choice', ''),
        }
        photo_file = request.FILES.get('photo', None)

        try:
            img = generate_flyer_image(form_data, photo_file)
            buf = io.BytesIO()
            img.save(buf, format='PNG')
            buf.seek(0)
            response = HttpResponse(buf.getvalue(), content_type='image/png')
            response['Content-Disposition'] = 'attachment; filename="soutenance_flyer.png"'
            return response
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)


# ── ADMIN PROTECTED VIEWS ─────────────────────────────────────────────

class DashboardView(LoginRequiredMixin, View):
    """Admin Dashboard view."""

    login_url = '/login/'

    def get(self, request):
        filiere_filter = request.GET.get('filiere', '').strip().upper()
        toge_filter = request.GET.get('toge', '').strip()
        echarpe_filter = request.GET.get('echarpe', '').strip()
        niveau_filter = request.GET.get('niveau', '').strip().upper()
        duplicates_filter = request.GET.get('duplicates', '').strip()
        search_query = request.GET.get('q', '').strip()

        students = StudentRegistration.objects.all()

        if search_query:
            students = students.filter(full_name__icontains=search_query)
        if filiere_filter in ['GL', 'SR', 'SE']:
            students = students.filter(filiere=filiere_filter)
        if toge_filter == '1':
            students = students.filter(toge=True)
        if echarpe_filter == '1':
            students = students.filter(echarpe=True)
        if niveau_filter in ['N2', 'N3']:
            students = students.filter(niveau=niveau_filter)

        # Duplicate detection algorithm across all students
        all_candidates = list(StudentRegistration.objects.all())
        duplicate_pairs = []
        duplicate_student_ids = set()
        student_max_similarity = {}

        for i in range(len(all_candidates)):
            s1 = all_candidates[i]
            for j in range(i + 1, len(all_candidates)):
                s2 = all_candidates[j]

                pair_key = (min(s1.pk, s2.pk), max(s1.pk, s2.pk))
                if pair_key in IGNORED_DUPLICATE_PAIRS:
                    continue

                sim, exact = compute_name_similarity(s1.full_name, s2.full_name)
                if sim >= 0.75:
                    duplicate_pairs.append({
                        'student1': s1,
                        'student2': s2,
                        'similarity': int(sim * 100),
                        'is_exact': exact,
                        'pair_key': f"{pair_key[0]}_{pair_key[1]}"
                    })
                    duplicate_student_ids.add(s1.pk)
                    duplicate_student_ids.add(s2.pk)
                    sim_pct = int(sim * 100)
                    student_max_similarity[s1.pk] = max(student_max_similarity.get(s1.pk, 0), sim_pct)
                    student_max_similarity[s2.pk] = max(student_max_similarity.get(s2.pk, 0), sim_pct)

        duplicate_pairs.sort(key=lambda x: x['similarity'], reverse=True)

        if duplicates_filter == '1':
            students = students.filter(pk__in=duplicate_student_ids)

        students = students.order_by('-created_at')

        # Compute financial summary
        all_regs = StudentRegistration.objects.all()
        raw_total = sum(get_student_amount(s) for s in all_regs)
        adjustments = FinancialAdjustment.objects.all().order_by('-created_at')
        adjustments_sum = sum(a.amount for a in adjustments)
        net_total = raw_total + adjustments_sum

        student_amounts = {s.pk: get_student_amount(s) for s in students}

        return render(request, 'generator/dashboard.html', {
            'students': students,
            'current_filter': filiere_filter,
            'toge_filter': toge_filter,
            'echarpe_filter': echarpe_filter,
            'niveau_filter': niveau_filter,
            'duplicates_filter': duplicates_filter,
            'search_query': search_query,
            'raw_total': f"{raw_total:,}".replace(',', ' '),
            'adjustments_sum': f"{adjustments_sum:,}".replace(',', ' '),
            'net_total': f"{net_total:,}".replace(',', ' '),
            'adjustments': adjustments,
            'duplicate_pairs': duplicate_pairs,
            'duplicate_student_ids': duplicate_student_ids,
            'student_max_similarity': student_max_similarity,
            'duplicate_count': len(duplicate_student_ids),
            'student_amounts': student_amounts,
        })


class StudentListView(LoginRequiredMixin, View):
    """Admin Student List View."""

    login_url = '/login/'

    def get(self, request):
        filiere_filter = request.GET.get('filiere', '').strip().upper()
        search_query = request.GET.get('q', '').strip()

        students = StudentRegistration.objects.all()
        if search_query:
            students = students.filter(full_name__icontains=search_query)
        if filiere_filter in ['GL', 'SR', 'SE']:
            students = students.filter(filiere=filiere_filter)
        students = students.order_by('-created_at')

        return render(request, 'generator/student_list.html', {
            'students': students,
            'current_filter': filiere_filter,
            'search_query': search_query,
            'total_students': StudentRegistration.objects.count(),
        })


class AddStudentView(LoginRequiredMixin, View):
    """Admin View to add a new candidate directly."""

    login_url = '/login/'

    def get(self, request):
        return render(request, 'generator/add_student.html', {
            'form_data': {'filiere': 'SR', 'niveau': 'N3'}
        })

    def post(self, request):
        full_name = request.POST.get('full_name', '').strip().upper()
        classe = request.POST.get('classe', '').strip() or 'Non spécifiée'
        filiere = request.POST.get('filiere', 'SR').strip().upper()
        niveau = request.POST.get('niveau', 'N3').strip().upper()
        theme = request.POST.get('theme', '').strip()
        academic_supervisor = request.POST.get('academic_supervisor', '').strip()
        professional_supervisor = request.POST.get('professional_supervisor', '').strip()
        toge = bool(request.POST.get('toge'))
        echarpe = bool(request.POST.get('echarpe'))
        frais_soutenance = bool(request.POST.get('frais_soutenance'))
        force_save = request.POST.get('force_save') == '1'

        if not full_name:
            return render(request, 'generator/add_student.html', {
                'error_message': 'Le nom complet est obligatoire.',
                'form_data': request.POST
            })

        # Check duplicate
        if not force_save:
            existing = StudentRegistration.objects.filter(full_name__iexact=full_name).first()
            if existing:
                return render(request, 'generator/add_student.html', {
                    'error_message': f'Un étudiant nommé "{existing.full_name}" existe déjà ({existing.classe}).',
                    'warn_duplicate': True,
                    'form_data': request.POST
                })

        StudentRegistration.objects.create(
            full_name=full_name,
            classe=classe,
            filiere=filiere,
            niveau=niveau,
            theme=theme,
            academic_supervisor=academic_supervisor,
            professional_supervisor=professional_supervisor,
            toge=toge,
            echarpe=echarpe,
            frais_soutenance=frais_soutenance,
        )

        return redirect('generator:student_list')


class EditStudentView(LoginRequiredMixin, View):
    """Admin View to modify all fields of an existing student."""

    login_url = '/login/'

    def get(self, request, pk):
        student = get_object_or_404(StudentRegistration, pk=pk)
        return render(request, 'generator/edit_student.html', {'student': student})

    def post(self, request, pk):
        student = get_object_or_404(StudentRegistration, pk=pk)
        student.full_name = request.POST.get('full_name', student.full_name).strip().upper()
        student.classe = request.POST.get('classe', student.classe).strip() or 'Non spécifiée'
        student.filiere = request.POST.get('filiere', student.filiere).strip().upper()
        student.niveau = request.POST.get('niveau', student.niveau).strip().upper()
        student.theme = request.POST.get('theme', '').strip()
        student.academic_supervisor = request.POST.get('academic_supervisor', '').strip()
        student.professional_supervisor = request.POST.get('professional_supervisor', '').strip()
        student.toge = bool(request.POST.get('toge'))
        student.echarpe = bool(request.POST.get('echarpe'))
        student.frais_soutenance = bool(request.POST.get('frais_soutenance'))

        student.save()
        return redirect('generator:student_list')


class DeleteStudentView(LoginRequiredMixin, View):
    """Admin View to delete a student record."""

    login_url = '/login/'

    def post(self, request, pk):
        student = get_object_or_404(StudentRegistration, pk=pk)
        student.delete()
        return redirect(request.META.get('HTTP_REFERER') or 'generator:student_list')


class StudentToggleFieldView(LoginRequiredMixin, View):
    """AJAX endpoint to toggle a student boolean field (toge, echarpe, frais_soutenance)."""

    login_url = '/login/'

    def post(self, request, pk):
        student = get_object_or_404(StudentRegistration, pk=pk)
        field = request.POST.get('field')
        value = request.POST.get('value') == '1'

        if field in ['toge', 'echarpe', 'frais_soutenance']:
            setattr(student, field, value)
            student.save(update_fields=[field])

            all_regs = StudentRegistration.objects.all()
            raw_total = sum(get_student_amount(s) for s in all_regs)
            adjustments = FinancialAdjustment.objects.all()
            adjustments_sum = sum(a.amount for a in adjustments)
            net_total = raw_total + adjustments_sum
            student_amount = get_student_amount(student)

            return JsonResponse({
                'success': True,
                'raw_total': raw_total,
                'adjustments_sum': adjustments_sum,
                'net_total': net_total,
                'student_amount': student_amount,
            })

        return JsonResponse({'success': False, 'error': 'Champ invalide'}, status=400)


class AddAdjustmentView(LoginRequiredMixin, View):
    """Admin View to add financial adjustment."""

    login_url = '/login/'

    def post(self, request):
        try:
            amount = int(request.POST.get('amount', 0))
            reason = request.POST.get('reason', '').strip() or 'Ajustement manuel'
            if amount != 0:
                FinancialAdjustment.objects.create(amount=amount, reason=reason)
        except (ValueError, TypeError):
            pass

        return redirect('generator:dashboard')


class DeleteAdjustmentView(LoginRequiredMixin, View):
    """Admin View to delete financial adjustment."""

    login_url = '/login/'

    def post(self, request, pk):
        adj = get_object_or_404(FinancialAdjustment, pk=pk)
        adj.delete()
        return redirect('generator:dashboard')


class IgnoreDuplicatePairView(LoginRequiredMixin, View):
    """Admin View to hide a duplicate pair warning."""

    login_url = '/login/'

    def post(self, request, pk1, pk2):
        pair = (min(pk1, pk2), max(pk1, pk2))
        IGNORED_DUPLICATE_PAIRS.add(pair)
        return redirect('generator:dashboard')


class DashboardDownloadPdfView(LoginRequiredMixin, View):
    """Admin View to export candidate list as PDF."""

    login_url = '/login/'

    def get(self, request):
        filiere_filter = request.GET.get('filiere', '').strip().upper()
        toge_filter = request.GET.get('toge', '').strip()
        echarpe_filter = request.GET.get('echarpe', '').strip()
        niveau_filter = request.GET.get('niveau', '').strip().upper()
        search_query = request.GET.get('q', '').strip()

        students = StudentRegistration.objects.all()

        if search_query:
            students = students.filter(full_name__icontains=search_query)
        if filiere_filter in ['GL', 'SR', 'SE']:
            students = students.filter(filiere=filiere_filter)
        if toge_filter == '1':
            students = students.filter(toge=True)
        if echarpe_filter == '1':
            students = students.filter(echarpe=True)
        if niveau_filter in ['N2', 'N3']:
            students = students.filter(niveau=niveau_filter)

        students = students.order_by('-created_at')

        # Create simple PDF document
        import io
        from reportlab.lib.pagesizes import letter, landscape
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib import colors

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=landscape(letter), rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
        elements = []
        styles = getSampleStyleSheet()

        title_style = ParagraphStyle(
            'ReportTitle',
            parent=styles['Heading1'],
            fontName='Helvetica-Bold',
            fontSize=18,
            textColor=colors.HexColor('#1e293b'),
            spaceAfter=12
        )

        elements.append(Paragraph("Liste des Candidats - Soutenances IAI Cameroun", title_style))
        elements.append(Spacer(1, 10))

        data = [["N°", "Nom Complet", "Classe", "Filière", "Niveau", "Toge", "Écharpe", "Frais Sout."]]

        for idx, s in enumerate(students, 1):
            data.append([
                str(idx),
                s.full_name,
                s.classe,
                s.filiere,
                s.niveau,
                "Oui" if s.toge else "Non",
                "Oui" if s.echarpe else "Non",
                "Oui" if s.frais_soutenance else "Non",
            ])

        t = Table(data)
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#3b82f6')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
            ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#f8fafc')),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
        ]))

        elements.append(t)
        doc.build(elements)
        buffer.seek(0)

        response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
        response['Content-Disposition'] = 'attachment; filename="candidats_soutenance.pdf"'
        return response


# ── PUBLIC API ENDPOINTS ─────────────────────────────────────────────

class StudentSearchApiView(View):
    """Returns JSON list of registered students matching query 'q'."""

    def get(self, request):
        q = request.GET.get('q', '').strip()
        if not q:
            return JsonResponse({'students': []})

        students = StudentRegistration.objects.filter(
            full_name__icontains=q
        ).order_by('full_name')[:10]

        data = [
            {
                'id': s.pk,
                'full_name': s.full_name,
                'classe': s.classe,
                'filiere': s.filiere,
                'niveau': s.niveau,
                'toge': s.toge,
                'echarpe': s.echarpe,
                'frais_soutenance': s.frais_soutenance,
                'theme': s.theme or '',
                'academic_supervisor': s.academic_supervisor or '',
                'professional_supervisor': s.professional_supervisor or '',
            }
            for s in students
        ]
        return JsonResponse({'students': data})


class StudentDuplicateCheckApiView(View):
    """Checks if a given student name matches or is similar to an existing registered student."""

    def get(self, request):
        name = request.GET.get('name', '').strip()
        exclude_id = request.GET.get('exclude_id')

        if not name or len(name) < 3:
            return JsonResponse({'is_duplicate': False, 'exact_match': False, 'matches': []})

        norm_name = normalize_name(name)
        tokens = [t for t in norm_name.split() if len(t) > 2]

        qs = StudentRegistration.objects.all()
        if exclude_id:
            try:
                qs = qs.exclude(pk=int(exclude_id))
            except (ValueError, TypeError):
                pass

        if tokens:
            from django.db.models import Q
            query_filter = Q()
            for tok in tokens:
                prefix = tok[:3] if len(tok) >= 3 else tok
                query_filter |= Q(full_name__icontains=prefix)
            qs = qs.filter(query_filter)
        else:
            qs = qs.filter(full_name__icontains=norm_name)

        matches = []
        is_exact = False

        for s in qs[:100]:
            ratio, exact = compute_name_similarity(name, s.full_name)
            if exact:
                is_exact = True

            if ratio >= 0.75:
                matches.append({
                    'id': s.pk,
                    'full_name': s.full_name,
                    'classe': s.classe,
                    'filiere': s.filiere,
                    'niveau': s.niveau,
                    'toge': s.toge,
                    'echarpe': s.echarpe,
                    'theme': s.theme or '',
                    'academic_supervisor': s.academic_supervisor or '',
                    'professional_supervisor': s.professional_supervisor or '',
                    'similarity': round(ratio, 2),
                    'is_exact': exact
                })

        matches.sort(key=lambda x: x['similarity'], reverse=True)
        matches = matches[:5]

        is_duplicate = len(matches) > 0

        return JsonResponse({
            'is_duplicate': is_duplicate,
            'exact_match': is_exact or any(m['is_exact'] for m in matches),
            'matches': matches
        })
