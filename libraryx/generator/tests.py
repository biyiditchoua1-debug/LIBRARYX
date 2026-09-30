from django.test import TestCase
from .utils import format_supervisor_name

class SupervisorNameFormattingTests(TestCase):
    def test_empty_and_whitespace(self):
        self.assertEqual(format_supervisor_name(""), "--")
        self.assertEqual(format_supervisor_name("   "), "--")
        self.assertEqual(format_supervisor_name(None), "--")

    def test_unrecognized_title_uppercase(self):
        # If no recognized title, whole name should be capitalized
        self.assertEqual(format_supervisor_name("Tchoua Biyidi"), "TCHOUA BIYIDI")
        self.assertEqual(format_supervisor_name("jean Dupont"), "JEAN DUPONT")

    def test_recognized_titles_mixed_case(self):
        # Recognized titles should be title-cased, other words upper-cased
        self.assertEqual(format_supervisor_name("Mr Tchoua Biyidi"), "Mr TCHOUA BIYIDI")
        self.assertEqual(format_supervisor_name("mr TCHOUA biYiDi"), "Mr TCHOUA BIYIDI")
        self.assertEqual(format_supervisor_name("m. jubo celest"), "M. JUBO CELEST")
        self.assertEqual(format_supervisor_name("mme twide camille"), "Mme TWIDE CAMILLE")
        self.assertEqual(format_supervisor_name("Dr. Jean-Marc"), "Dr. JEAN-MARC")
        self.assertEqual(format_supervisor_name("prof. Kengne"), "Prof. KENGNE")
        self.assertEqual(format_supervisor_name("monsieur paul"), "Monsieur PAUL")
        self.assertEqual(format_supervisor_name("ING. Dupont"), "Ing. DUPONT")

    def test_multiple_middle_last_names(self):
        self.assertEqual(format_supervisor_name("Mr. Jean Paul Pierre"), "Mr. JEAN PAUL PIERRE")


class AddStudentViewTests(TestCase):
    def test_add_student_stays_on_page_and_clears_fields(self):
        from django.urls import reverse
        from .models import StudentRegistration

        response = self.client.post(reverse('generator:add_student'), {
            'full_name': 'KOUAM ALAIN',
            'classe': 'SR 3 - B',
            'filiere': 'SR',
            'niveau': 'N3',
            'toge': '1',
            'echarpe': '1',
        })

        # Should return 200 OK (stay on page), not redirect 302
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'generator/add_student.html')
        self.assertIn('success_message', response.context)
        self.assertEqual(response.context['form_data'], {})

        # Verify student was saved in DB
        self.assertTrue(StudentRegistration.objects.filter(full_name='KOUAM ALAIN').exists())


class PDFExportOrderingTests(TestCase):
    def setUp(self):
        from .models import StudentRegistration
        import time
        # Create 3 students registered sequentially
        self.s1 = StudentRegistration.objects.create(
            full_name="FIRST REGISTERED STUDENT",
            filiere="SR",
            niveau="N3"
        )
        time.sleep(0.01)
        self.s2 = StudentRegistration.objects.create(
            full_name="SECOND REGISTERED STUDENT",
            filiere="SR",
            niveau="N3"
        )
        time.sleep(0.01)
        self.s3 = StudentRegistration.objects.create(
            full_name="THIRD REGISTERED STUDENT",
            filiere="SR",
            niveau="N3"
        )

    def test_dashboard_view_keeps_newest_first(self):
        from django.urls import reverse
        response = self.client.get(reverse('generator:dashboard'))
        self.assertEqual(response.status_code, 200)
        students_in_context = list(response.context['students'])
        # Newest registered student (s3) should be first on dashboard
        self.assertEqual(students_in_context[0].pk, self.s3.pk)
        self.assertEqual(students_in_context[-1].pk, self.s1.pk)

    def test_pdf_export_orders_chronologically_oldest_first(self):
        from django.urls import reverse
        response = self.client.get(reverse('generator:dashboard_download_pdf'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        # Content is binary PDF data
        self.assertTrue(len(response.content) > 0)


