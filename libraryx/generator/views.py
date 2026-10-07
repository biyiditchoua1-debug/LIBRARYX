import difflib
import hashlib
import io
import json
import logging
import math
import os
import re
import secrets
import warnings
from collections import defaultdict
from datetime import timedelta

from PIL import Image, UnidentifiedImageError
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.core.validators import validate_email
from django.db import OperationalError, transaction
from django.db.models import Count, Q, Sum
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import salted_hmac
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View

from .models import FlyerAccessCode, FlyerPaymentOrder, FinancialAdjustment, StudentRegistration
from .utils import (
    generate_flyer_image,
    generate_flyer_preview_bytes,
    split_day_month,
    split_time,
)


logger = logging.getLogger(__name__)
MAX_PHOTO_SIZE = 16 * 1024 * 1024
MAX_PHOTO_PIXELS = 30_000_000
FLYER_PRICE_XAF = 100
FLYER_PAYMENT_LIFETIME = timedelta(hours=2)
FLYER_PAYMENT_METHODS = {'orange': 'Orange Money', 'mtn': 'MTN Mobile Money'}
FREE_FLYER_CODE_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
FIXED_TOTAL_DEDUCTION = 450_000
GENERATION_FIELD_LIMITS = {
    'full_name': 255,
    'classe': 100,
    'theme': 1000,
    'academic_supervisor': 255,
    'professional_supervisor': 255,
    'soutenance_date': 5,
    'soutenance_time': 5,
    'filiere': 10,
    'niveau': 10,
    'template_choice': 16,
}


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


def _cached_duplicate_pair_scores(all_candidates):
    """Return scored duplicate ID pairs, caching by the current candidate names."""
    fingerprint = hashlib.sha256()
    for student in all_candidates:
        fingerprint.update(str(student.pk).encode('ascii'))
        fingerprint.update(b'\0')
        fingerprint.update(student.full_name.encode('utf-8'))
        fingerprint.update(b'\0')

    cache_key = f'dashboard:duplicate-pairs:{fingerprint.hexdigest()}'
    cached_scores = cache.get(cache_key)
    if cached_scores is not None:
        return cached_scores

    normalized_names = {student.pk: normalize_name(student.full_name) for student in all_candidates}
    name_tokens = {
        student.pk: frozenset(token for token in normalized_names[student.pk].split() if len(token) > 2)
        for student in all_candidates
    }
    trigram_students = defaultdict(set)
    token_set_students = defaultdict(list)

    for student in all_candidates:
        normalized_name = normalized_names[student.pk]
        if len(normalized_name) >= 3:
            for index in range(len(normalized_name) - 2):
                trigram_students[normalized_name[index:index + 3]].add(student.pk)
        if name_tokens[student.pk]:
            token_set_students[name_tokens[student.pk]].append(student.pk)

    candidate_pair_keys = set()

    def add_pairs_from_groups(groups):
        for student_ids in groups:
            ordered_ids = sorted(student_ids)
            for left_index, left_id in enumerate(ordered_ids):
                for right_id in ordered_ids[left_index + 1:]:
                    candidate_pair_keys.add((left_id, right_id))

    # Equal non-empty token sets count as near-duplicates even when words are
    # reordered, so include those pairs regardless of sequence similarity.
    add_pairs_from_groups(token_set_students.values())

    for student_ids in trigram_students.values():
        ordered_ids = sorted(student_ids)
        for left_index, left_id in enumerate(ordered_ids):
            for right_id in ordered_ids[left_index + 1:]:
                pair_key = (left_id, right_id)
                if pair_key in candidate_pair_keys:
                    continue
                left_tokens = name_tokens[left_id]
                if left_tokens and left_tokens == name_tokens[right_id]:
                    candidate_pair_keys.add(pair_key)
                    continue

                # quick_ratio is an upper bound on SequenceMatcher.ratio.
                # All other successful scorer branches need at least .80.
                matcher = difflib.SequenceMatcher(
                    None, normalized_names[left_id], normalized_names[right_id], autojunk=False
                )
                if matcher.quick_ratio() >= 0.80:
                    candidate_pair_keys.add(pair_key)

    students_by_id = {student.pk: student for student in all_candidates}
    scored_pairs = []
    for left_id, right_id in sorted(candidate_pair_keys):
        sim, exact = compute_name_similarity(
            students_by_id[left_id].full_name,
            students_by_id[right_id].full_name,
        )
        if sim >= 0.75:
            scored_pairs.append((left_id, right_id, int(sim * 100), exact))

    scored_pairs.sort(key=lambda pair: pair[2], reverse=True)
    cache.set(cache_key, scored_pairs, timeout=900)
    return scored_pairs


def get_student_amount(student):
    """Calculates individual total fee for a student."""
    total = 0
    if student.toge:
        total += 13_500
    if student.echarpe:
        total += 3_500
    if student.frais_soutenance:
        total += 2000 if student.niveau == 'N2' else 2500
    return total


def calculate_dashboard_revenue():
    """Calculate fee revenue using the dashboard rates and fixed deduction."""
    counts = StudentRegistration.objects.aggregate(
        toge_count=Count('pk', filter=Q(toge=True)),
        echarpe_count=Count('pk', filter=Q(echarpe=True)),
        n2_count=Count('pk', filter=Q(frais_soutenance=True, niveau__iexact='N2')),
        n3_count=Count('pk', filter=Q(frais_soutenance=True, niveau__iexact='N3')),
    )
    gross_total = (
        (counts['toge_count'] or 0) * 13_500
        + (counts['echarpe_count'] or 0) * 3_500
        + (counts['n2_count'] or 0) * 2_000
        + (counts['n3_count'] or 0) * 2_500
    )
    return gross_total, gross_total - FIXED_TOTAL_DEDUCTION


def _safe_next_url(request):
    candidate = request.POST.get('next') if request.method == 'POST' else request.GET.get('next')
    if candidate and url_has_allowed_host_and_scheme(
        candidate,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return candidate
    return reverse('generator:dashboard')


def _generation_payload(request):
    form_data = {
        'full_name': request.POST.get('full_name', '').strip(),
        'classe': request.POST.get('classe', '').strip(),
        'theme': request.POST.get('theme', '').strip(),
        'academic_supervisor': request.POST.get('academic_supervisor', '').strip(),
        'professional_supervisor': request.POST.get('professional_supervisor', '').strip(),
        'soutenance_date': request.POST.get('soutenance_date', '').strip(),
        'soutenance_time': request.POST.get('soutenance_time', '').strip(),
        'filiere': request.POST.get('filiere', 'SR'),
        'niveau': request.POST.get('niveau', 'N2'),
        'template_choice': request.POST.get('template_choice', ''),
    }

    try:
        raw_photo_crop = request.POST.get('photo_crop', '')
        if len(raw_photo_crop) > 256:
            raise ValueError
        photo_crop = json.loads(raw_photo_crop) if raw_photo_crop else {}
        if not isinstance(photo_crop, dict):
            raise ValueError
        crop_values = {
            'cx': photo_crop.get('cx', 0.5),
            'cy': photo_crop.get('cy', 0.5),
            'zoom': photo_crop.get('zoom', 1),
        }
        if any(
            isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
            for value in crop_values.values()
        ):
            raise ValueError
        if not (0 <= crop_values['cx'] <= 1 and 0 <= crop_values['cy'] <= 1 and 1 <= crop_values['zoom'] <= 3):
            raise ValueError
        form_data['photo_crop'] = crop_values
    except (TypeError, ValueError, json.JSONDecodeError):
        return None, None, JsonResponse({'error': 'Le cadrage de la photo est invalide. Réessayez.'}, status=400)

    for field, limit in GENERATION_FIELD_LIMITS.items():
        if len(form_data[field]) > limit:
            return None, None, JsonResponse(
                {'error': f'Le champ « {field} » dépasse la longueur maximale autorisée.'},
                status=400,
            )

    form_data['filiere'] = form_data['filiere'].strip().upper()
    form_data['niveau'] = form_data['niveau'].strip().upper()
    form_data['template_choice'] = form_data['template_choice'].strip().upper()
    allowed_templates = {
        '', 'AUTO', 'GL', 'SE', 'SR',
        'GL-N2', 'GL-N3', 'SE-N2', 'SE-N3', 'SR-N2', 'SR-N3',
    }
    if form_data['filiere'] not in {'GL', 'SE', 'SR'}:
        return None, None, JsonResponse({'error': 'La filière sélectionnée est invalide.'}, status=400)
    if form_data['niveau'] not in {'N2', 'N3'}:
        return None, None, JsonResponse({'error': 'Le niveau sélectionné est invalide.'}, status=400)
    if form_data['template_choice'] not in allowed_templates:
        return None, None, JsonResponse({'error': 'Le modèle sélectionné est invalide.'}, status=400)

    if form_data['template_choice'] not in {'', 'AUTO', 'GL', 'SE', 'SR'}:
        form_data['filiere'], form_data['niveau'] = form_data['template_choice'].split('-', 1)

    try:
        split_day_month(form_data['soutenance_date'])
        split_time(form_data['soutenance_time'])
    except ValueError as exc:
        return None, None, JsonResponse({'error': str(exc)}, status=400)

    photo_file = request.FILES.get('photo')
    if photo_file:
        if photo_file.size > MAX_PHOTO_SIZE:
            return None, None, JsonResponse(
                {'error': 'La photo doit peser 16 Mo maximum.'}, status=400
            )
        try:
            photo_file.seek(0)
            with warnings.catch_warnings():
                warnings.simplefilter('error', Image.DecompressionBombWarning)
                with Image.open(photo_file) as image:
                    if image.format not in {'JPEG', 'PNG', 'WEBP', 'HEIF'}:
                        raise ValueError('Unsupported image format')
                    if image.width * image.height > MAX_PHOTO_PIXELS:
                        return None, None, JsonResponse(
                            {'error': 'La photo dépasse la limite de 30 mégapixels.'},
                            status=400,
                        )
                    image.verify()
            photo_file.seek(0)
        except (
            UnidentifiedImageError,
            OSError,
            ValueError,
            Image.DecompressionBombError,
            Image.DecompressionBombWarning,
        ):
            return None, None, JsonResponse(
                {'error': 'Choisissez une photo JPEG, PNG, WebP ou HEIC valide (16 Mo maximum).'},
                status=400,
            )

    return form_data, photo_file, None


class AdminLoginView(View):
    """Admin Login view."""

    def get(self, request):
        if request.user.is_authenticated and request.user.is_staff:
            return redirect('generator:dashboard')
        next_url = _safe_next_url(request)
        return render(request, 'generator/login.html', {'next_url': next_url})

    def post(self, request):
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')
        next_url = _safe_next_url(request)

        user_model = get_user_model()
        real_user = user_model.objects.filter(
            username__iexact=username, is_staff=True, is_active=True
        ).first()
        lookup_username = real_user.username if real_user else username

        user = authenticate(request, username=lookup_username, password=password)
        if user is not None and user.is_staff:
            login(request, user)
            return redirect(next_url)

        return render(request, 'generator/login.html', {
            'error_message': 'Identifiant ou mot de passe incorrect.',
            'next_url': next_url
        })


class AdminLogoutView(View):
    """Admin Logout view."""

    def post(self, request):
        logout(request)
        return redirect('generator:home')


# ── PUBLIC FLYER GENERATOR VIEWS ──────────────────────────────────────

class FlyerFormView(View):
    """Renders the main flyer generator page."""

    def get(self, request):
        _expire_old_payment_orders()
        return render(request, 'generator/flyer_form.html')


class FlyerPreviewView(View):
    """Returns a JPEG preview image of the flyer."""

    def post(self, request):
        form_data, photo_file, error_response = _generation_payload(request)
        if error_response:
            return error_response

        try:
            image_bytes = generate_flyer_preview_bytes(
                form_data, photo_file, photo_crop=form_data['photo_crop']
            )
            response = HttpResponse(image_bytes, content_type='image/jpeg')
            response['Cache-Control'] = 'private, no-store, no-cache, max-age=0, must-revalidate'
            response['Pragma'] = 'no-cache'
            response['X-Content-Type-Options'] = 'nosniff'
            return response
        except Exception:
            logger.exception('Flyer preview generation failed')
            return JsonResponse(
                {'error': 'La prévisualisation a échoué. Vérifiez les données et réessayez.'},
                status=500,
            )


class FlyerDownloadView(View):
    """Blocks direct downloads; paid orders are served by FlyerPaymentDownloadView."""

    def post(self, request):
        return JsonResponse(
            {'error': 'Le paiement de 100 FCFA est requis avant le téléchargement.'},
            status=402,
        )


def _expire_old_payment_orders(now=None):
    """Discard expired flyer files while keeping payment history."""
    now = now or timezone.now()
    expired = FlyerPaymentOrder.objects.filter(expires_at__lte=now)
    unfinished_statuses = [
        FlyerPaymentOrder.STATUS_CREATED,
        FlyerPaymentOrder.STATUS_INITIATING,
        FlyerPaymentOrder.STATUS_PENDING,
    ]
    expired.filter(status__in=unfinished_statuses).update(
        status=FlyerPaymentOrder.STATUS_EXPIRED,
        flyer_png=b'',
        session_key='',
        updated_at=now,
    )
    expired.exclude(status__in=unfinished_statuses).update(
        flyer_png=b'',
        session_key='',
        updated_at=now,
    )


def _owned_flyer_order(request, order_id):
    session_key = request.session.session_key
    if not session_key:
        return None
    order = FlyerPaymentOrder.objects.filter(pk=order_id, session_key=session_key).first()
    if order and order.expires_at <= timezone.now():
        _expire_old_payment_orders()
        return None
    return order


def _payment_page(request, order, status=200, **context):
    if order.status == FlyerPaymentOrder.STATUS_FAILED:
        context.setdefault(
            'error_message',
            'Le paiement n’a pas abouti. Vérifiez le numéro et vous pouvez réessayer.',
        )
    return render(
        request,
        'generator/payment_checkout.html',
        {
            'order': order,
            'amount': 0 if order.payment_method == 'free_code' else FLYER_PRICE_XAF,
            'payment_methods': FLYER_PAYMENT_METHODS,
            'can_redeem_free_code': (
                order.status in {FlyerPaymentOrder.STATUS_CREATED, FlyerPaymentOrder.STATUS_FAILED}
                and not order.transaction_id
            ),
            **context,
        },
        status=status,
    )


def _normalize_free_flyer_code(value):
    normalized = re.sub(r'[\s-]+', '', (value or '')).upper()
    if len(normalized) != 12 or any(char not in FREE_FLYER_CODE_ALPHABET for char in normalized):
        return ''
    return normalized


def _free_flyer_code_digest(normalized_code):
    # Keep plaintext vouchers out of the SQLite database and public repository.
    return salted_hmac('generator.free-flyer-code', normalized_code).hexdigest()


class FreeFlyerCodeRedemptionError(Exception):
    pass


def _redeem_free_flyer_code(order, submitted_code):
    normalized_code = _normalize_free_flyer_code(submitted_code)
    if not normalized_code:
        raise FreeFlyerCodeRedemptionError('Le code saisi est invalide ou déjà utilisé.')
    if (
        order.status not in {FlyerPaymentOrder.STATUS_CREATED, FlyerPaymentOrder.STATUS_FAILED}
        or order.transaction_id
    ):
        raise FreeFlyerCodeRedemptionError(
            'Ce code doit être utilisé avant de démarrer un paiement. Revenez au générateur pour créer une nouvelle commande.'
        )

    now = timezone.now()
    digest = _free_flyer_code_digest(normalized_code)
    with transaction.atomic():
        access_code = FlyerAccessCode.objects.filter(
            code_digest=digest,
            redeemed_at__isnull=True,
            redeemed_order__isnull=True,
        ).first()
        if not access_code:
            raise FreeFlyerCodeRedemptionError('Le code saisi est invalide ou déjà utilisé.')

        updated_order = FlyerPaymentOrder.objects.filter(
            pk=order.pk,
            status__in=[FlyerPaymentOrder.STATUS_CREATED, FlyerPaymentOrder.STATUS_FAILED],
            transaction_id='',
        ).update(
            status=FlyerPaymentOrder.STATUS_PAID,
            payment_method='free_code',
            updated_at=now,
        )
        if updated_order != 1:
            raise FreeFlyerCodeRedemptionError(
                'Cette commande a déjà démarré un paiement. Créez une nouvelle commande pour utiliser le code.'
            )

        claimed_code = FlyerAccessCode.objects.filter(
            pk=access_code.pk,
            redeemed_at__isnull=True,
            redeemed_order__isnull=True,
        ).update(redeemed_at=now, redeemed_order=order)
        if claimed_code != 1:
            raise FreeFlyerCodeRedemptionError('Le code saisi est invalide ou déjà utilisé.')


def _generate_free_flyer_code():
    characters = ''.join(secrets.choice(FREE_FLYER_CODE_ALPHABET) for _ in range(12))
    return '-'.join((characters[:4], characters[4:8], characters[8:]))


def _normalize_cameroon_mobile_number(value):
    digits = re.sub(r'\D', '', value or '')
    if digits.startswith('237'):
        digits = digits[3:]
    if digits.startswith('0'):
        digits = digits[1:]
    if len(digits) != 9 or not digits.startswith('6'):
        raise ValueError('Entrez un numéro mobile camerounais valide (9 chiffres).')
    return f'237{digits}'


class FlyerPaymentStartView(View):
    """Generates a private PNG and creates its fixed-price checkout order."""

    def post(self, request):
        form_data, photo_file, error_response = _generation_payload(request)
        if error_response:
            return error_response

        image = None
        try:
            image = generate_flyer_image(
                form_data, photo_file, photo_crop=form_data['photo_crop']
            )
            png_buffer = io.BytesIO()
            image.save(png_buffer, format='PNG')
            flyer_png = png_buffer.getvalue()
        except Exception:
            logger.exception('Paid flyer generation failed')
            return JsonResponse(
                {'error': 'La génération a échoué. Vérifiez les données et réessayez.'},
                status=500,
            )
        finally:
            if image is not None:
                image.close()

        if not request.session.session_key:
            request.session.create()
        now = timezone.now()
        # Purge expired flyer images but keep transaction records for the admin history.
        _expire_old_payment_orders(now)
        order = FlyerPaymentOrder.objects.create(
            session_key=request.session.session_key,
            flyer_png=flyer_png,
            expires_at=now + FLYER_PAYMENT_LIFETIME,
        )
        response = JsonResponse({
            'checkout_url': reverse('generator:payment_checkout', args=[order.pk]),
        }, status=201)
        response['Cache-Control'] = 'no-store'
        return response


class FlyerPaymentCheckoutView(View):
    """Collects the selected wallet and starts a server-side DigiPay payment."""

    def get(self, request, order_id):
        order = _owned_flyer_order(request, order_id)
        if not order:
            return render(request, 'generator/payment_expired.html', status=404)
        return _payment_page(request, order)

    def post(self, request, order_id):
        order = _owned_flyer_order(request, order_id)
        if not order:
            return render(request, 'generator/payment_expired.html', status=404)
        if order.status == FlyerPaymentOrder.STATUS_PAID:
            return redirect('generator:payment_checkout', order_id=order.pk)

        if request.POST.get('action') == 'redeem_free_code':
            try:
                _redeem_free_flyer_code(order, request.POST.get('access_code', ''))
            except FreeFlyerCodeRedemptionError as exc:
                return _payment_page(request, order, error_message=str(exc))
            except OperationalError:
                logger.warning('Concurrent free flyer code redemption for order %s', order.pk)
                return _payment_page(
                    request,
                    order,
                    error_message='Le code vient peut-être d’être utilisé. Rechargez la page et réessayez.',
                )
            return redirect('generator:payment_checkout', order_id=order.pk)

        payment_method = request.POST.get('payment_method', '').strip()
        if payment_method not in FLYER_PAYMENT_METHODS:
            return _payment_page(request, order, error_message='Choisissez Orange Money ou MTN Mobile Money.')
        try:
            customer_phone = _normalize_cameroon_mobile_number(request.POST.get('mobile_number', ''))
        except ValueError as exc:
            return _payment_page(request, order, error_message=str(exc), selected_method=payment_method)

        customer_email = request.POST.get('customer_email', '').strip()
        if customer_email:
            try:
                validate_email(customer_email)
            except ValidationError:
                return _payment_page(
                    request, order,
                    error_message='Entrez une adresse e-mail valide ou laissez le champ vide.',
                    selected_method=payment_method,
                )
            if len(customer_email) > 254:
                return _payment_page(
                    request, order,
                    error_message='L’adresse e-mail est trop longue.',
                    selected_method=payment_method,
                )

        api_key = os.environ.get('DIGIPAY_API_KEY', '').strip()
        if not api_key:
            return _payment_page(
                request, order,
                error_message='Le service de paiement n’est pas configuré. Réessayez plus tard.',
                selected_method=payment_method,
                status=503,
            )
        try:
            from digipay import DigiPay, DigiPayError
        except ImportError:
            return _payment_page(
                request, order,
                error_message='Le service de paiement est momentanément indisponible.',
                selected_method=payment_method,
                status=503,
            )

        # Claim the order before contacting DigiPay so duplicate submissions cannot charge twice.
        claimed = FlyerPaymentOrder.objects.filter(
            pk=order.pk,
            status__in=[FlyerPaymentOrder.STATUS_CREATED, FlyerPaymentOrder.STATUS_FAILED],
        ).update(
            status='initiating',
            payment_method=payment_method,
            transaction_id='',
            updated_at=timezone.now(),
        )
        if claimed != 1:
            return redirect('generator:payment_checkout', order_id=order.pk)

        try:
            client = DigiPay(api_key=api_key, timeout=12)
            payment = client.payments.initiate(
                amount=FLYER_PRICE_XAF,
                customer_phone=customer_phone,
                customer_email=customer_email or None,
                metadata={
                    'order_id': str(order.pk),
                    'payment_method': payment_method,
                },
            )
        except DigiPayError as exc:
            # A provider 4xx is a definitive rejection and permits a corrected retry.
            # Timeouts and 5xx responses are ambiguous, so retain the claim to avoid a duplicate charge.
            if exc.status_code is not None and 400 <= exc.status_code < 500:
                FlyerPaymentOrder.objects.filter(pk=order.pk).update(status=FlyerPaymentOrder.STATUS_FAILED)
                return _payment_page(
                    request, order,
                    error_message='DigiPay a refusé la demande. Vérifiez le numéro et réessayez.',
                    selected_method=payment_method,
                )
            logger.warning('DigiPay payment initiation returned an ambiguous error for order %s', order.pk)
            return redirect('generator:payment_checkout', order_id=order.pk)
        except Exception:
            logger.exception('DigiPay payment initiation failed')
            FlyerPaymentOrder.objects.filter(pk=order.pk).update(status=FlyerPaymentOrder.STATUS_FAILED)
            return _payment_page(
                request, order,
                error_message='Impossible de démarrer le paiement. Réessayez.',
                selected_method=payment_method,
            )

        transaction_id = str(payment.get('transaction_id', '')).strip()
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', transaction_id):
            logger.error('DigiPay returned a payment without a valid transaction ID for order %s', order.pk)
            return redirect('generator:payment_checkout', order_id=order.pk)

        provider_status = str(payment.get('status', 'pending')).lower()
        order.transaction_id = transaction_id
        order.status = (
            FlyerPaymentOrder.STATUS_PAID
            if provider_status == 'success'
            else FlyerPaymentOrder.STATUS_FAILED
            if provider_status in {'failed', 'cancelled', 'canceled', 'expired'}
            else FlyerPaymentOrder.STATUS_PENDING
        )
        order.save(update_fields=['transaction_id', 'status', 'updated_at'])
        return redirect('generator:payment_checkout', order_id=order.pk)


class FlyerPaymentStatusView(View):
    """Refreshes transaction state directly from DigiPay before allowing a download."""

    def get(self, request, order_id):
        order = _owned_flyer_order(request, order_id)
        if not order:
            return JsonResponse({'error': 'Commande introuvable ou expirée.'}, status=404)

        if order.status in {FlyerPaymentOrder.STATUS_CREATED, FlyerPaymentOrder.STATUS_FAILED}:
            return JsonResponse({'status': order.status})
        if order.status == 'initiating' or not order.transaction_id:
            return JsonResponse({'status': 'pending', 'message': 'Vérification du paiement en cours.'})
        if order.status == FlyerPaymentOrder.STATUS_PAID:
            return JsonResponse({
                'status': 'paid',
                'download_url': reverse('generator:payment_download', args=[order.pk]),
            })

        try:
            from digipay import DigiPay
            api_key = os.environ.get('DIGIPAY_API_KEY', '').strip()
            transaction = DigiPay(api_key=api_key, timeout=12).payments.get_status(order.transaction_id)
        except Exception:
            logger.warning('DigiPay status lookup failed for order %s', order.pk)
            return JsonResponse({'status': 'pending', 'message': 'Vérification du paiement en cours.'})

        returned_id = str(transaction.get('transaction_id', '')).strip()
        if returned_id and returned_id != order.transaction_id:
            logger.error('DigiPay returned a mismatched transaction ID for order %s', order.pk)
            return JsonResponse({'status': 'pending', 'message': 'Vérification du paiement en cours.'})

        provider_status = str(transaction.get('status', 'pending')).lower()
        if provider_status == 'success':
            order.status = FlyerPaymentOrder.STATUS_PAID
            order.save(update_fields=['status', 'updated_at'])
        elif provider_status in {'failed', 'cancelled', 'canceled', 'expired'}:
            order.status = FlyerPaymentOrder.STATUS_FAILED
            order.save(update_fields=['status', 'updated_at'])

        if order.status == FlyerPaymentOrder.STATUS_PAID:
            return JsonResponse({
                'status': 'paid',
                'download_url': reverse('generator:payment_download', args=[order.pk]),
            })
        return JsonResponse({'status': order.status})


class FlyerPaymentDownloadView(View):
    """Returns a generated PNG only after the provider confirms the payment."""

    def get(self, request, order_id):
        order = _owned_flyer_order(request, order_id)
        if not order:
            return JsonResponse({'error': 'Commande introuvable ou expirée.'}, status=404)
        if order.status != FlyerPaymentOrder.STATUS_PAID:
            return JsonResponse({'error': 'Le paiement doit être confirmé avant le téléchargement.'}, status=402)

        response = HttpResponse(bytes(order.flyer_png), content_type='image/png')
        response['Content-Disposition'] = 'attachment; filename="soutenance_flyer.png"'
        response['Cache-Control'] = 'private, no-store'
        return response


# ── ADMIN PROTECTED VIEWS ─────────────────────────────────────────────

class AdminRequiredMixin(LoginRequiredMixin):
    """Require an authenticated staff account for the administration area."""

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not request.user.is_staff:
            return HttpResponseForbidden('Accès réservé aux administrateurs.')
        return super().dispatch(request, *args, **kwargs)


class DashboardView(AdminRequiredMixin, View):
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

        # Reuse duplicate analysis until the registered name set changes.
        all_candidates = list(StudentRegistration.objects.all().order_by('pk'))
        students_by_id = {student.pk: student for student in all_candidates}
        duplicate_pairs = []
        duplicate_student_ids = set()
        student_max_similarity = {}
        for left_id, right_id, sim_pct, exact in _cached_duplicate_pair_scores(all_candidates):
            pair_key = (left_id, right_id)
            if pair_key in IGNORED_DUPLICATE_PAIRS:
                continue
            s1 = students_by_id[left_id]
            s2 = students_by_id[right_id]
            duplicate_pairs.append({
                'student1': s1,
                'student2': s2,
                'similarity': sim_pct,
                'is_exact': exact,
                'pair_key': f"{left_id}_{right_id}"
            })
            duplicate_student_ids.add(s1.pk)
            duplicate_student_ids.add(s2.pk)
            student_max_similarity[s1.pk] = max(student_max_similarity.get(s1.pk, 0), sim_pct)
            student_max_similarity[s2.pk] = max(student_max_similarity.get(s2.pk, 0), sim_pct)

        duplicate_pairs.sort(key=lambda x: x['similarity'], reverse=True)

        if duplicates_filter == '1':
            students = students.filter(pk__in=duplicate_student_ids)

        students = students.order_by('-created_at')
        students_page = Paginator(students, 50).get_page(request.GET.get('page'))
        pagination_query = request.GET.copy()
        pagination_query.pop('page', None)

        # Compute financial summary with one SQL aggregate; the fixed
        # 450,000 FCFA deduction is applied exactly once to fee revenue.
        _gross_total, raw_total = calculate_dashboard_revenue()
        adjustments = FinancialAdjustment.objects.all().order_by('-created_at')
        adjustments_sum = FinancialAdjustment.objects.aggregate(total=Sum('amount'))['total'] or 0
        net_total = raw_total + adjustments_sum

        student_amounts = {s.pk: get_student_amount(s) for s in students_page}

        return render(request, 'generator/dashboard.html', {
            'students': students_page,
            'pagination_query': pagination_query.urlencode(),
            'current_filter': filiere_filter,
            'toge_filter': toge_filter,
            'echarpe_filter': echarpe_filter,
            'niveau_filter': niveau_filter,
            'duplicates_filter': duplicates_filter,
            'search_query': search_query,
            'fixed_total_deduction': f"{FIXED_TOTAL_DEDUCTION:,}".replace(',', ' '),
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


class FlyerAccessCodeAdminView(AdminRequiredMixin, View):
    """Generate one-use free flyer codes for administrators to share."""

    login_url = '/login/'

    def _render_page(self, request, *, generated_codes=None, error_message='', status=200):
        response = render(request, 'generator/flyer_access_codes.html', {
            'generated_codes': generated_codes or [],
            'error_message': error_message,
            'access_codes': FlyerAccessCode.objects.select_related(
                'created_by', 'redeemed_order'
            ).order_by('-created_at')[:100],
        }, status=status)
        response['Cache-Control'] = 'private, no-store'
        return response

    def get(self, request):
        return self._render_page(request)

    def post(self, request):
        try:
            count = int(request.POST.get('count', '1'))
        except (TypeError, ValueError):
            return self._render_page(
                request,
                error_message='Entrez un nombre valide entre 1 et 100.',
                status=400,
            )
        if not 1 <= count <= 100:
            return self._render_page(
                request,
                error_message='Vous pouvez générer de 1 à 100 codes à la fois.',
                status=400,
            )

        generated_codes = []
        with transaction.atomic():
            for _ in range(count):
                code = _generate_free_flyer_code()
                digest = _free_flyer_code_digest(code.replace('-', ''))
                while FlyerAccessCode.objects.filter(code_digest=digest).exists():
                    code = _generate_free_flyer_code()
                    digest = _free_flyer_code_digest(code.replace('-', ''))
                FlyerAccessCode.objects.create(
                    code_digest=digest,
                    code_hint=code[-4:],
                    created_by=request.user,
                )
                generated_codes.append(code)

        return self._render_page(request, generated_codes=generated_codes)


class PaymentTransactionsView(AdminRequiredMixin, View):
    """Read-only payment history and revenue summary for staff."""

    login_url = '/login/'

    def get(self, request):
        _expire_old_payment_orders()
        status_filter = request.GET.get('status', '').strip().lower()
        valid_statuses = {value for value, _label in FlyerPaymentOrder.STATUS_CHOICES}

        orders = FlyerPaymentOrder.objects.all().order_by('-created_at')
        if status_filter in valid_statuses:
            orders = orders.filter(status=status_filter)
        else:
            status_filter = ''

        totals = FlyerPaymentOrder.objects.aggregate(
            transaction_count=Count('id'),
            successful_count=Count(
                'id',
                filter=Q(status=FlyerPaymentOrder.STATUS_PAID) & ~Q(payment_method='free_code'),
            ),
            free_code_count=Count(
                'id',
                filter=Q(status=FlyerPaymentOrder.STATUS_PAID, payment_method='free_code'),
            ),
            failed_count=Count('id', filter=Q(status=FlyerPaymentOrder.STATUS_FAILED)),
        )
        pagination_query = request.GET.copy()
        pagination_query.pop('page', None)

        return render(request, 'generator/payment_transactions.html', {
            'orders': Paginator(orders, 30).get_page(request.GET.get('page')),
            'pagination_query': pagination_query.urlencode(),
            'status_filter': status_filter,
            'transaction_count': totals['transaction_count'],
            'successful_count': totals['successful_count'],
            'free_code_count': totals['free_code_count'],
            'failed_count': totals['failed_count'],
            'total_amount': totals['successful_count'] * FLYER_PRICE_XAF,
            'flyer_price': FLYER_PRICE_XAF,
            'status_choices': FlyerPaymentOrder.STATUS_CHOICES,
        })


class StudentListView(AdminRequiredMixin, View):
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
        students_page = Paginator(students, 50).get_page(request.GET.get('page'))
        pagination_query = request.GET.copy()
        pagination_query.pop('page', None)

        return render(request, 'generator/student_list.html', {
            'students': students_page,
            'pagination_query': pagination_query.urlencode(),
            'current_filter': filiere_filter,
            'search_query': search_query,
            'total_students': StudentRegistration.objects.count(),
        })


class AddStudentView(AdminRequiredMixin, View):
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


class EditStudentView(AdminRequiredMixin, View):
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


class DeleteStudentView(AdminRequiredMixin, View):
    """Admin View to delete a student record."""

    login_url = '/login/'

    def post(self, request, pk):
        student = get_object_or_404(StudentRegistration, pk=pk)
        student.delete()
        return redirect(request.META.get('HTTP_REFERER') or 'generator:student_list')


class StudentToggleFieldView(AdminRequiredMixin, View):
    """AJAX endpoint to toggle a student boolean field (toge, echarpe, frais_soutenance)."""

    login_url = '/login/'

    def post(self, request, pk):
        student = get_object_or_404(StudentRegistration, pk=pk)
        field = request.POST.get('field')
        value = request.POST.get('value') == '1'

        if field in ['toge', 'echarpe', 'frais_soutenance']:
            setattr(student, field, value)
            student.save(update_fields=[field])

            _gross_total, raw_total = calculate_dashboard_revenue()
            adjustments_sum = FinancialAdjustment.objects.aggregate(total=Sum('amount'))['total'] or 0
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


class AddAdjustmentView(AdminRequiredMixin, View):
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


class DeleteAdjustmentView(AdminRequiredMixin, View):
    """Admin View to delete financial adjustment."""

    login_url = '/login/'

    def post(self, request, pk):
        adj = get_object_or_404(FinancialAdjustment, pk=pk)
        adj.delete()
        return redirect('generator:dashboard')


class IgnoreDuplicatePairView(AdminRequiredMixin, View):
    """Admin View to hide a duplicate pair warning."""

    login_url = '/login/'

    def post(self, request, pk1, pk2):
        pair = (min(pk1, pk2), max(pk1, pk2))
        IGNORED_DUPLICATE_PAIRS.add(pair)
        return redirect('generator:dashboard')


class DashboardDownloadPdfView(AdminRequiredMixin, View):
    """Admin View to export candidate list as PDF."""

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

        if duplicates_filter == '1':
            all_candidates = list(StudentRegistration.objects.all().order_by('pk'))
            duplicate_student_ids = set()
            for left_id, right_id, _similarity, _exact in _cached_duplicate_pair_scores(all_candidates):
                if (left_id, right_id) not in IGNORED_DUPLICATE_PAIRS:
                    duplicate_student_ids.update((left_id, right_id))
            students = students.filter(pk__in=duplicate_student_ids)

        students = list(students.order_by('-created_at', '-pk'))

        from xml.sax.saxutils import escape

        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER, TA_LEFT
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.pdfbase.pdfmetrics import stringWidth
        from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
        from django.utils.text import slugify

        from .utils import _register_reportlab_fonts

        _register_reportlab_fonts()

        active_filters = []
        title_suffixes = []
        if filiere_filter in ['GL', 'SR', 'SE']:
            active_filters.append(f'Filière : {filiere_filter}')
            title_suffixes.append(filiere_filter)
        else:
            active_filters.append('Filière : Toutes filières')
        if niveau_filter in ['N2', 'N3']:
            active_filters.append(f'Niveau : {niveau_filter}')
            title_suffixes.append(niveau_filter)
        else:
            active_filters.append('Niveau : Tous niveaux')
        if toge_filter == '1':
            active_filters.append('Toge : Oui')
            title_suffixes.append('avec toge')
        if echarpe_filter == '1':
            active_filters.append('Écharpe : Oui')
            title_suffixes.append('avec echarpe')
        if duplicates_filter == '1':
            active_filters.append('Doublons : Oui')
            title_suffixes.append('doublons')
        if search_query:
            active_filters.append(f'Nom : {search_query}')

        title = 'LISTE DES CANDIDATS ENREGISTRÉS'
        if title_suffixes:
            title += ' (' + ' · '.join(title_suffixes).upper() + ')'
        filter_summary = ' | '.join(active_filters)

        page_size = 20
        page_count = max(1, (len(students) + page_size - 1) // page_size)
        page_width, _page_height = A4
        left_margin = right_margin = 9 * mm
        available_width = page_width - left_margin - right_margin

        buffer = io.BytesIO()

        def draw_footer(canvas, doc):
            canvas.saveState()
            canvas.setFont('Poppins-MediumItalic', 7)
            canvas.setFillColor(colors.HexColor('#64748b'))
            canvas.drawCentredString(
                page_width / 2,
                8 * mm,
                f'IAI SYNERGY Database Report – Généré automatiquement le {timezone.localtime():%d/%m/%Y à %H:%M}',
            )
            canvas.restoreState()

        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            rightMargin=right_margin,
            leftMargin=left_margin,
            topMargin=13 * mm,
            bottomMargin=15 * mm,
            title=title,
            author='IAI SYNERGY',
        )

        title_style = ParagraphStyle(
            'CandidateReportTitle', fontName='Poppins-ExtraBold', fontSize=14,
            leading=18, alignment=TA_CENTER, textColor=colors.HexColor('#0f172a'),
            spaceAfter=3 * mm,
        )
        subtitle_style = ParagraphStyle(
            'CandidateReportSubtitle', fontName='Poppins-SemiBold', fontSize=7.5,
            leading=10, alignment=TA_CENTER, textColor=colors.HexColor('#3b82f6'),
            spaceAfter=4 * mm,
        )
        body_style = ParagraphStyle(
            'CandidateReportBody', fontName='Poppins-Medium', fontSize=7.1,
            leading=9, alignment=TA_LEFT, textColor=colors.HexColor('#1e293b'),
        )
        center_style = ParagraphStyle(
            'CandidateReportCenter', parent=body_style, alignment=TA_CENTER,
        )
        yes_style = ParagraphStyle(
            'CandidateReportYes', parent=center_style, fontName='Poppins-Bold',
            textColor=colors.HexColor('#15803d'),
        )
        no_style = ParagraphStyle(
            'CandidateReportNo', parent=center_style, fontName='Poppins-Bold',
            textColor=colors.HexColor('#dc2626'),
        )
        header_style = ParagraphStyle(
            'CandidateReportHeader', fontName='Poppins-Bold', fontSize=7,
            leading=8, alignment=TA_CENTER, textColor=colors.white,
        )
        headers = ['N°', 'Nom Complet', 'Classe', 'Toge', 'Écharpe', 'Frais', 'Filière &amp; Niv.']
        column_widths = [25, 151, 53, 49, 54, 45, available_width - 377]
        elements = []

        def shortened(value, max_width, font_name='Poppins-Medium', font_size=7.1):
            value = str(value or '')
            if stringWidth(value, font_name, font_size) <= max_width:
                return value
            while value and stringWidth(value + '…', font_name, font_size) > max_width:
                value = value[:-1]
            return value.rstrip() + '…'

        for page_index in range(page_count):
            elements.append(Paragraph(escape(title), title_style))
            subtitle = f'{escape(filter_summary)} · Page {page_index + 1} sur {page_count}'
            elements.append(Paragraph(subtitle, subtitle_style))

            rows = [[Paragraph(label, header_style) for label in headers]]
            page_students = students[page_index * page_size:(page_index + 1) * page_size]
            for offset, student in enumerate(page_students, start=page_index * page_size + 1):
                yes_no = lambda value: Paragraph('OUI' if value else 'NON', yes_style if value else no_style)
                name = shortened(student.full_name, column_widths[1] - 8)
                rows.append([
                    Paragraph(str(offset), center_style),
                    Paragraph(escape(name), body_style),
                    Paragraph(escape(shortened(student.classe, column_widths[2] - 8)), center_style),
                    yes_no(student.toge),
                    yes_no(student.echarpe),
                    yes_no(student.frais_soutenance),
                    Paragraph(escape(f'{student.filiere} - {student.niveau}'), center_style),
                ])

            table = Table(
                rows,
                colWidths=column_widths,
                rowHeights=[9 * mm] + [8 * mm] * len(page_students),
                repeatRows=1,
                hAlign='LEFT',
            )
            table_commands = [
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0f172a')),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('ALIGN', (1, 1), (1, -1), 'LEFT'),
                ('LEFTPADDING', (0, 0), (-1, -1), 4),
                ('RIGHTPADDING', (0, 0), (-1, -1), 4),
                ('TOPPADDING', (0, 0), (-1, -1), 2),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
                ('LINEBELOW', (0, 0), (-1, 0), 0.5, colors.HexColor('#334155')),
                ('LINEBELOW', (0, 1), (-1, -1), 0.25, colors.HexColor('#d5deea')),
            ]
            for row_index in range(1, len(rows)):
                if row_index % 2 == 0:
                    table_commands.append((
                        'BACKGROUND', (0, row_index), (-1, row_index), colors.HexColor('#e9eff7')
                    ))
                else:
                    table_commands.append((
                        'BACKGROUND', (0, row_index), (-1, row_index), colors.white
                    ))
            table.setStyle(TableStyle(table_commands))
            elements.append(table)

            if not page_students:
                elements.append(Spacer(1, 8 * mm))
                elements.append(Paragraph('Aucun candidat ne correspond aux filtres sélectionnés.', body_style))
            if page_index + 1 < page_count:
                elements.append(PageBreak())

        doc.build(elements, onFirstPage=draw_footer, onLaterPages=draw_footer)
        filename_parts = ['candidats']
        filename_parts.extend(slugify(part) for part in title_suffixes if slugify(part))
        if search_query:
            filename_parts.append(slugify(search_query)[:40])
        response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{"-".join(filename_parts)}.pdf"'
        return response


# ── PUBLIC API ENDPOINTS ─────────────────────────────────────────────

class StudentSearchApiView(View):
    """Returns JSON list of registered students matching query 'q'."""

    def get(self, request):
        q = request.GET.get('q', '').strip()
        if len(q) > 100:
            return JsonResponse({'error': 'Recherche trop longue.'}, status=400)
        if len(q) < 2:
            return JsonResponse({'students': []})

        students = StudentRegistration.objects.filter(
            full_name__icontains=q
        ).order_by('full_name')[:10]

        data = [
            {
                'full_name': s.full_name,
                'classe': s.classe,
                'filiere': s.filiere,
                'niveau': s.niveau,
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

        if len(name) > 255:
            return JsonResponse({'error': 'Nom trop long.'}, status=400)
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
