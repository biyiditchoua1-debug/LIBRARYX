from django.urls import path
from . import views

app_name = 'generator'

urlpatterns = [
    path('', views.FlyerFormView.as_view(), name='home'),
    path('preview/', views.FlyerPreviewView.as_view(), name='preview'),
    path('download/', views.FlyerDownloadView.as_view(), name='download'),
    path('students/', views.StudentListView.as_view(), name='student_list'),
    path('students/edit/<int:pk>/', views.EditStudentView.as_view(), name='edit_student'),
    path('api/students/search/', views.StudentSearchApiView.as_view(), name='student_search'),
    path('api/students/check-duplicate/', views.StudentDuplicateCheckApiView.as_view(), name='student_check_duplicate'),
]



