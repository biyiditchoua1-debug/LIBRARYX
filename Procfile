web: cd libraryx && python manage.py collectstatic --noinput && gunicorn libraryx.wsgi:application --bind 0.0.0.0:$PORT
