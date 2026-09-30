from django.urls import path
from . import views

app_name = 'generator'

urlpatterns = [
    # Public Flyer Generator
    path('', views.FlyerFormView.as_view(), name='home'),
    path('preview/', views.FlyerPreviewView.as_view(), name='preview'),
    path('download/', views.FlyerDownloadView.as_view(), name='download'),

    # Admin Authentication
    path('login/', views.AdminLoginView.as_view(), name='login'),
    path('logout/', views.AdminLogoutView.as_view(), name='logout'),

    # Admin Protected Area
    path('dashboard/', views.DashboardView.as_view(), name='dashboard'),
    path('dashboard/export/', views.DashboardDownloadPdfView.as_view(), name='dashboard_download'),
    path('dashboard/adjustments/add/', views.AddAdjustmentView.as_view(), name='add_adjustment'),
    path('dashboard/adjustments/delete/<int:pk>/', views.DeleteAdjustmentView.as_view(), name='delete_adjustment'),
    path('dashboard/ignore-duplicate/<int:pk1>/<int:pk2>/', views.IgnoreDuplicatePairView.as_view(), name='ignore_duplicate_pair'),
    path('dashboard/student/toggle/<int:pk>/', views.StudentToggleFieldView.as_view(), name='student_toggle_field'),

    # Student Management CRUD
    path('students/', views.StudentListView.as_view(), name='student_list'),
    path('students/add/', views.AddStudentView.as_view(), name='add_student'),
    path('students/edit/<int:pk>/', views.EditStudentView.as_view(), name='edit_student'),
    path('students/delete/<int:pk>/', views.DeleteStudentView.as_view(), name='delete_student'),

    # Public APIs
    path('api/students/search/', views.StudentSearchApiView.as_view(), name='student_search'),
    path('api/students/check-duplicate/', views.StudentDuplicateCheckApiView.as_view(), name='student_check_duplicate'),
]
