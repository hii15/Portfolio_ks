# LLM Context: Next Work Plan

이 문서는 앞으로 진행할 우선 작업을 정리한 실행 컨텍스트입니다.

## 1) Decision Explainability 고도화 (Phase 2)
- `decision_reason`, `efficiency_note`를 테이블 상단 요약과 함께 표시
- `roas_gap_vs_target_pct`, `install_gap_to_min` 기준 경고 배지 추가
- Hold/Scale Down 세그먼트 우선 정렬 옵션 추가

## 2) LiveOps 분석 고도화
- Level 기반 uplift 결과에 정렬/필터(샘플 수 최소 기준) 추가
- 이벤트 기간 vs 베이스라인 기간의 차이를 매체/캠페인별 카드로 요약
- LiveOps uplift 상/하위 세그먼트 자동 하이라이트

## 3) Experiment Report 고도화
- Insight Cards 확장: Top/Worst MMP 외에 변동성(표본 대비) 지표 추가
- 의사결정 결과(Scale Up/Down/Hold) 분포 요약 차트 추가
- Markdown 리포트에 실험 파라미터(seed/기간/threshold) 포함

## 4) 분석 레벨 확장
- 현재 level(`media_source`, `campaign`, `adset`, `creative`) 동작 점검
- `media_source_campaign` 외 복합 레벨(예: `campaign_adset`) 옵션 검토
- 레벨별 비용 데이터 누락 시 fallback 전략 명시

## 5) 실데이터 연동 준비 (Pre-BQ)
- Canonical 필수 컬럼 validation 에러 메시지 표준화
- MMP별 Raw 템플릿 예시 파일 제공
- BigQuery 연결 시 필요한 테이블/컬럼 계약 문서화

## 6) 품질/테스트
- Decision/LiveOps/Experiment 탭에 대한 최소 UI e2e 시나리오 정리
- Dummy 시나리오 스냅샷 고정(seed별 기대값) 테스트 추가
- 회귀 테스트를 CI에서 일관 실행할 수 있도록 명령 단순화

## 7) 운영성 개선
- Streamlit 탭별 상태 저장(session_state) 정리
- 실패 시 사용자 메시지(원인/해결 가이드) 개선
- 결과 CSV/MD 다운로드 버튼 추가
