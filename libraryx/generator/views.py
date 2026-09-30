from django.views import View
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse, JsonResponse

from .utils import generate_flyer_preview_bytes, generate_flyer_pdf_bytes, generate_flyer_image
from .models import StudentRegistration
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
    Ratio is between 0.0 and 1.0.
    """
    norm1 = normalize_name(name1)
    norm2 = normalize_name(name2)

    if not norm1 or not norm2:
        return 0.0, False

    # Exact match
    if norm1 == norm2:
        return 1.0, True

    # Require minimum length of 3 chars for similarity matching
    if len(norm1) < 3 or len(norm2) < 3:
        return 0.0, False

    seq_ratio = difflib.SequenceMatcher(None, norm1, norm2).ratio()

    # Extract significant tokens (> 2 chars)
    t1 = {t for t in norm1.split() if len(t) > 2}
    t2 = {t for t in norm2.split() if len(t) > 2}

    if t1 and t2:
        # If token sets are identical (order independent: e.g. TCHOUA ALEX vs ALEX TCHOUA)
        if t1 == t2:
            return 0.98, False

        common = t1 & t2
        diff1 = t1 - common
        diff2 = t2 - common

        # If both names contain distinct differing tokens, ensure they are typos of each other
        # e.g. "KOUAM JEAN" vs "KOUAM PAUL" -> diff1={"jean"}, diff2={"paul"} -> NOT a duplicate!
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



class FlyerFormView(View):
    """Renders the main flyer generator page."""

    def get(self, request):
        return render(request, 'generator/flyer_form.html')


class FlyerPreviewView(View):
    """Returns a JPEG preview image of the flyer (for live AJAX preview)."""

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
            
            # Save candidate registration to statistics database (skip if name already registered)
            full_name = form_data['full_name'].strip().upper()   # store in UPPERCASE
            classe = request.POST.get('classe', '').strip()
            toge = 'toge' in request.POST
            echarpe = 'echarpe' in request.POST
            filiere = form_data['filiere']
            niveau = form_data['niveau']

            already_exists = StudentRegistration.objects.filter(
                full_name__iexact=full_name
            ).exists()

            if full_name:
                theme_val = form_data.get('theme', '').strip()
                acad_sup = request.POST.get('academic_supervisor', '').strip()
                prof_sup = request.POST.get('professional_supervisor', '').strip()

                if already_exists:
                    # Update the existing record with new flyer info (theme/supervisors)
                    existing = StudentRegistration.objects.get(full_name__iexact=full_name)
                    if theme_val:   existing.theme = theme_val
                    if acad_sup:    existing.academic_supervisor = acad_sup
                    if prof_sup:    existing.professional_supervisor = prof_sup
                    existing.save()
                else:
                    StudentRegistration.objects.create(
                        full_name=full_name,
                        classe=classe or 'Non spécifiée',
                        toge=toge,
                        echarpe=echarpe,
                        filiere=filiere,
                        niveau=niveau,
                        theme=theme_val,
                        academic_supervisor=acad_sup,
                        professional_supervisor=prof_sup,
                    )

            buf = io.BytesIO()
            img.save(buf, format='PNG')
            buf.seek(0)
            response = HttpResponse(buf.getvalue(), content_type='image/png')
            response['Content-Disposition'] = 'attachment; filename="soutenance_flyer.png"'
            return response
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)


class StudentListView(View):
    """Renders the student management list."""

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


class EditStudentView(View):
    """View to modify an existing student's class, filiere, or theme."""

    def get(self, request, pk):
        student = get_object_or_404(StudentRegistration, pk=pk)
        return render(request, 'generator/edit_student.html', {'student': student})

    def post(self, request, pk):
        student = get_object_or_404(StudentRegistration, pk=pk)
        student.classe = request.POST.get('classe', student.classe).strip() or 'Non spécifiée'
        student.filiere = request.POST.get('filiere', student.filiere).strip().upper()
        student.theme = request.POST.get('theme', '').strip()
        student.save(update_fields=['classe', 'filiere', 'theme'])

        return redirect('generator:student_list')


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

        # Filter candidates at DB level using token prefix matching
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

        # Sort matches by similarity descending
        matches.sort(key=lambda x: x['similarity'], reverse=True)
        matches = matches[:5]

        is_duplicate = len(matches) > 0

        return JsonResponse({
            'is_duplicate': is_duplicate,
            'exact_match': is_exact or any(m['is_exact'] for m in matches),
            'matches': matches
        })




