---
description: 안전 동기화 실행 — DB 백업 + 변경 감지 + 무결성 검증 + LLM 분류 + 벡터 갱신
---

인비즈 자가발전 동기화를 실행합니다.

옵션: $1 (--no-rollback 입력 시 critical 변동 발견해도 롤백 안 함, 기본은 자동 롤백)

실행:
```bash
cd "C:\Users\scpar\OneDrive - Inviz\5.Inviz_Corporation\14.경영정보\00.경영관리마스터\web_app"
set PYTHONIOENCODING=utf-8
python self_dev.py
```

또는 백그라운드 + 로그:
```bash
safe_sync.bat manual
```

완료 후 다음 보고:
1. **백업**: 스냅샷 경로 + 크기
2. **동기화**: 처리/오류 파일 수, +/- 행수
3. **무결성**: warning/critical/롤백 건수
4. **LLM 분류**: 자동 처리·검토 대기열
5. **벡터 갱신**: 재인덱싱 청크 수

critical 변동 발견 시:
- 어떤 테이블·지표·변화율
- 자동 롤백 여부
- 권장 후속 조치
