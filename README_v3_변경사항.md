# Diabetes Pharma Lab v3 (2026-10-30)

## 핵심 사항
- v2 사용자의 공개 GitHub Pages 사이트를 업데이트하는 코드 변경 묶음.
- 기존 `data/pharma_lab.sqlite3` 및 `site/` 경로를 유지해야 과거 수집 기록을 보존할 수 있음.
- `DATA_GO_KR_API_KEY`가 없으면 국내 자료원은 **NOT_CONFIGURED**로 기록되며 실행하지 않음.
- 국내 시범 수집 범위는 식약처 허가 제품 목록 일부 및 심평원 성분 분류 일부. **DUR/안전성서한/회수/급여기준 개정의 감시가 아님.**
- `OPENAI_API_KEY`가 없으면 AI 분석을 제공하지 않음. 키가 있을 경우 PubMed 초록 일부를 **메모리에서만** 불러와 제한된 검토 초안을 작성. 전문을 읽었다고 주장하지 않음.
- UI의 '우선 확인'은 기술적 자료 변화/최근 수집에 따른 정렬로 의료적 긴급도 평가가 아님.

## 검증
- 로컬 단위 테스트: `python -m unittest discover -s tests -v`
- Python 문법 검사: `python -m py_compile ...`
- 외부 API와 GitHub Pages 자동 갱신은 계정 배포 이후 검증 필요. 모의 API 응답 테스트만 수행됨.

## 국내 참고 사이트
- [식약처 의약품 품목허가 API](https://www.data.go.kr/data/15095677/openapi.do)
- [심평원 주성분 정보 API](https://www.data.go.kr/data/15021027/openapi.do)
- [의약품안전나라](https://nedrug.mfds.go.kr/)
- [심평원](https://www.hira.or.kr/)
