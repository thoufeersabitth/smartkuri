FROM python:3.11

# Prevent .pyc files & buffer issues
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

WORKDIR /app

COPY . .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Collect static files (IMPORTANT for CSS/JS)
RUN python manage.py collectstatic --noinput

# Run server
CMD ["gunicorn", "smartkuri.wsgi:application", "--bind", "0.0.0.0:8000"]