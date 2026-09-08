FROM python:3.11-slim-bookworm

# Image provenance is supplied by the build (CI passes the commit SHA and UTC
# build time; local builds may omit them and get an honest "unknown").
ARG SOURCE_REVISION=unknown
ARG BUILD_CREATED=unknown
ARG SOURCE_URL=https://github.com/thomsyne/trade-recommender
ARG IMAGE_VERSION=unknown
LABEL org.opencontainers.image.revision="${SOURCE_REVISION}" \
      org.opencontainers.image.created="${BUILD_CREATED}" \
      org.opencontainers.image.source="${SOURCE_URL}" \
      org.opencontainers.image.version="${IMAGE_VERSION}" \
      org.opencontainers.image.title="trade-recommender"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_SOURCE_REVISION="${SOURCE_REVISION}" \
    APP_BUILD_CREATED="${BUILD_CREATED}"

WORKDIR /app
RUN addgroup --system app && adduser --system --ingroup app app
# util-linux is explicit, not assumed: deploy/scripts/backup.sh requires an
# flock(1) that reports contention with a dedicated exit status (-E), and
# fails closed without one.
RUN apt-get update && apt-get install -y --no-install-recommends curl postgresql-client unzip util-linux \
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
RUN printf 'revision=%s\ncreated=%s\nversion=%s\n' "${SOURCE_REVISION}" "${BUILD_CREATED}" "${IMAGE_VERSION}" > /app/build-info \
    && chown -R app:app /app
USER app

CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2"]
