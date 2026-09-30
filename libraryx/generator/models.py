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

