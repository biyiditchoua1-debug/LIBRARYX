# Production deployment (Railway)

The Django application lives in `libraryx/`. The root Procfile starts it through `libraryx/start.sh`; the script seeds a persistent SQLite volume from the bundled database only when the mounted database is missing or empty, then runs migrations and collects static files.

## Railway setup

1. Connect the `LIBRARYX` GitHub repository and deploy the `main` branch. Use the repository root as the service root; the root Procfile and requirements file support this layout.
2. Add a Railway Volume to the web service and mount it at `/data`.
3. Set these service variables:
   - `SQLITE_PATH=/data/db.sqlite3`
   - `DJANGO_DEBUG=0`
   - `DJANGO_SECRET_KEY` to a newly generated, private, stable value
   - `DJANGO_ALLOWED_HOSTS` to the Railway public hostname (or let Railway provide `RAILWAY_PUBLIC_DOMAIN`)
   - `DIGIPAY_API_KEY` to the private provider key if payments are enabled
4. Enable a public domain and deploy. Keep the service to one replica because the application uses SQLite on a single persistent volume.

On the first deployment, the startup script copies the checked-in SQLite database to `/data/db.sqlite3`. Later deployments keep using the volume database, preserving its accounts and student records. The script never replaces a non-empty database.

## Public database notice

The repository is public and includes `libraryx/db.sqlite3` because this deployment is intended to publish that file. Its student records and password hashes are therefore publicly readable from GitHub. Never add `.env` or provider credentials to the repository; use Railway service variables for secrets.
