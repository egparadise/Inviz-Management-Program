# 인비즈 경영관리 — 배포용 컨테이너 이미지
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Seoul \
    INVIZ_PORT=8000

WORKDIR /app

# 시간대(한국) + 한글 폰트(급여명세서 PDF 렌더링용 NanumGothic)
RUN apt-get update && apt-get install -y --no-install-recommends tzdata fonts-nanum \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone \
    && fc-cache -f \
    && rm -rf /var/lib/apt/lists/*

# 의존성 먼저 설치(레이어 캐시)
COPY requirements-deploy.txt .
RUN pip install --upgrade pip && pip install -r requirements-deploy.txt

# 앱 소스 복사 (.dockerignore 로 데이터·비밀 제외)
COPY . /app

EXPOSE 8000

# 리버스 프록시(Caddy/nginx) 뒤에서 실제 클라이언트 IP 인식 (--proxy-headers)
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
