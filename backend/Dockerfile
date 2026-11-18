FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn
COPY . .
# Migrations run separately with the database owner role (docker-compose "migrate" service);
# the running app only has the limited app role.
CMD ["sh", "-c", "python manage.py collectstatic --noinput && gunicorn config.wsgi -b 0.0.0.0:8100 -w 4"]
