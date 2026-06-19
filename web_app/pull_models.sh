#!/usr/bin/env bash
# 서버(Docker)에서 Ollama LLM 모델 내려받기.
# docker-compose의 ollama 서비스가 떠 있어야 합니다. (docker compose up -d)
# 모델은 ollama_models 볼륨에 영속 저장됩니다.
set -e
C="${1:-inviz-ollama}"   # ollama 컨테이너 이름
echo "== Ollama 모델 다운로드 (컨테이너: $C) =="
docker exec "$C" ollama pull bge-m3:latest      # 임베딩(RAG, 다국어)
docker exec "$C" ollama pull llama3.1:latest    # 메인 LLM
# 필요 시 추가:
# docker exec "$C" ollama pull llama3.2:latest
echo "== 설치된 모델 =="
docker exec "$C" ollama list
