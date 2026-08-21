FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
RUN addgroup --system app && adduser --system --ingroup app app
RUN apt-get update && apt-get install -y --no-install-recommends curl postgresql-client unzip \
    && case "$(dpkg --print-architecture)" in arm64) architecture=aarch64 ;; amd64) architecture=x86_64 ;; *) exit 1 ;; esac \
    && curl --fail --silent --show-error "https://awscli.amazonaws.com/awscli-exe-linux-${architecture}.zip" -o /tmp/awscliv2.zip \
    && unzip -q /tmp/awscliv2.zip -d /tmp \
    && /tmp/aws/install \
    && rm -rf /var/lib/apt/lists/* /tmp/aws /tmp/awscliv2.zip
COPY requirements.txt ./
RUN pip install --no-cache-dir --requirement requirements.txt
COPY . .
RUN DJANGO_SETTINGS_MODULE=config.settings_production \
    DJANGO_SECRET_KEY=build-only-0000000000000000000000000000000000000000 \
    PUBLIC_URL=https://build.invalid \
    POSTGRES_PASSWORD=build-only-database-password \
    python manage.py collectstatic --noinput
RUN chown -R app:app /app
USER app

CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2"]
