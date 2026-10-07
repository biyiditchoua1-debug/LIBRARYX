import uuid

from django.conf import settings
from django.db import models

class StudentRegistration(models.Model):
    full_name = models.CharField(max_length=255, db_index=True)
    classe = models.CharField(max_length=100)
    toge = models.BooleanField(default=False)
    echarpe = models.BooleanField(default=False)
    frais_soutenance = models.BooleanField(default=False)
    filiere = models.CharField(max_length=100, db_index=True)
    niveau = models.CharField(max_length=50, db_index=True)
    # Flyer-specific info (optional — not shown in dashboard table)
    theme = models.TextField(blank=True, default='')
    academic_supervisor = models.CharField(max_length=255, blank=True, default='')
    professional_supervisor = models.CharField(max_length=255, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    def __str__(self):
        return f"{self.full_name} ({self.classe})"


class FinancialAdjustment(models.Model):
    amount = models.IntegerField()
    reason = models.CharField(max_length=255, default='Ajustement manuel')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.amount} FCFA ({self.reason})"


class FlyerPaymentOrder(models.Model):
    STATUS_CREATED = 'created'
    STATUS_INITIATING = 'initiating'
    STATUS_PENDING = 'pending'
    STATUS_PAID = 'paid'
    STATUS_FAILED = 'failed'
    STATUS_EXPIRED = 'expired'
    STATUS_CHOICES = [
        (STATUS_CREATED, 'Created'),
        (STATUS_INITIATING, 'Initiating'),
        (STATUS_PENDING, 'Pending'),
        (STATUS_PAID, 'Paid'),
        (STATUS_FAILED, 'Failed'),
        (STATUS_EXPIRED, 'Expired'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session_key = models.CharField(max_length=40, db_index=True)
    flyer_png = models.BinaryField()
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_CREATED)
    transaction_id = models.CharField(max_length=128, blank=True, db_index=True)
    payment_method = models.CharField(max_length=16, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField(db_index=True)

    def __str__(self):
        return f"Flyer payment {self.id} ({self.status})"


class FlyerAccessCode(models.Model):
    """One-use complimentary flyer code; the plaintext is shown only at creation."""

    code_digest = models.CharField(max_length=64, unique=True)
    code_hint = models.CharField(max_length=4)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='generated_flyer_access_codes',
    )
    redeemed_at = models.DateTimeField(null=True, blank=True)
    redeemed_order = models.OneToOneField(
        FlyerPaymentOrder,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='redeemed_access_code',
    )

    def __str__(self):
        return f"Free flyer code ending {self.code_hint}"
