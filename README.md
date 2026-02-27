# Game UA Decision Engine

MMP Raw 데이터를 기반으로 UA 집행 분석, Cohort LTV 계산, LiveOps 영향 분석까지 수행하는 게임 인하우스용 의사결정 콘솔입니다.

## 1. Project Goal

이 프로젝트의 목적은 다음을 구현하는 것입니다.

- MMP Raw 데이터 구조를 이해한 분석 시스템
- Cohort 기반 LTV 및 ROAS 계산
- 매체별 Scale Up / Down 판단 로직 구현
- LiveOps 기간 신규 유저 가치 상승 효과 분석
- MMP 포맷 차이를 내부 표준 스키마로 정규화

핵심은 단순 리포팅이 아니라, **의사결정 프레임워크를 제공하는 콘솔** 구현입니다.

---

## 2. System Architecture

```text
MMP Raw Export
   ↓
Adapter (정규화)
   ↓
Canonical Schema
   ↓
Metrics Engine
   ↓
Decision Engine
   ↓
Streamlit UI
```

### 2.1 Core Data Model

#### `fact_installs`
- `user_key`: 유저 고유 식별자
- `install_time`: 설치 시간
- `media_source`: 매체
- `campaign`: 캠페인
- `adset`: 광고그룹
- `creative`: 소재
- `geo`: 국가
- `platform`: iOS / Android

#### `fact_events`
- `user_key`: 유저 식별자
- `event_time`: 이벤트 시간
- `event_name`: 이벤트명
- `revenue`: 매출

#### `fact_cost`
- `date`: 일자
- `media_source`: 매체
- `campaign`: 캠페인
- `impressions`: 노출
- `clicks`: 클릭
- `spend`: 광고비

관계 구조:

- `fact_installs (1) -> fact_events (N)`
- `fact_cost`: daily level aggregate

---

## 3. MMP Adapter Design

MMP별 Raw 포맷 차이를 흡수하기 위해 Adapter 패턴을 사용합니다.

### 3.1 `BaseMMPAdapter`

- `normalize_installs(df)`
- `normalize_events(df)`
- `normalize_cost(df)`

### 3.2 Supported MMP

- AppsFlyer
- Adjust
- Singular

각 Adapter는 아래를 수행합니다.

- user 식별자 통합
- column 이름 표준화
- timestamp 형식 통일
- revenue 필드 정규화

---

## 4. Metrics Engine

### 4.1 계산 지표

#### Install Metrics
- Installs
- CPI = spend / installs

#### Monetization Metrics
- Purchase Rate
- ARPPU
- ARPU
- D1 LTV
- D7 LTV

#### Efficiency Metrics
- D1 ROAS
- D7 ROAS
- Payback Period

### 4.2 Cohort Calculation Logic

- install_time 기준 Cohort 생성
- event_time - install_time 계산
- D1 / D7 / D30 revenue 집계
- 누적 LTV 계산

### 4.3 ROAS 분해 구조

- `ROAS = LTV / Cost`
- LTV는 Purchase Rate, ARPPU, Retention 요소의 함수
- ROAS 변화 원인을 분해 가능한 구조로 유지

---

## 5. Decision Engine

목표: 매체별 Scale Up / Down 판단 자동화

### 5.1 입력값

- Target ROAS
- 최소 Install 기준 (예: 200)
- 분석 기간 (예: 최근 7일)

### 5.2 판단 로직 예시

```python
if installs < threshold:
    decision = "Hold (Low Sample)"
elif D7_ROAS > target * 1.15:
    decision = "Scale Up"
elif D7_ROAS < target * 0.9:
    decision = "Scale Down"
else:
    decision = "Maintain"
```

---

## 6. LiveOps Impact Module

### 6.1 목적

이벤트/업데이트 기간 신규 유저 가치 상승 효과를 측정합니다.

### 6.2 입력

- 이벤트 시작일
- 이벤트 종료일
- 비교 기준 기간 (자동 설정 가능)

### 6.3 계산 방식

- 이벤트 기간 Cohort 생성
- 이전 기간 Cohort 생성
- D7 LTV 비교
- 차이 계산

`LiveOps Impact = Event Cohort D7 LTV - Pre Cohort D7 LTV`

표본 수를 함께 표시합니다.

---

## 7. Sample Dummy Data Requirements

더미 데이터는 아래 특성을 포함합니다.

- 매체별 CPI 차이
- 매체별 Purchase Rate 차이
- 매체별 ARPPU 차이
- 특정 기간 LTV 상승 (LiveOps 테스트용)

예시 매체:
- Meta
- Google
- Unity
- TikTok

---

## 8. Folder Structure

```text
project_root/
│
├── app.py
├── data_processing/
│   ├── adapters/
│   │   ├── base.py
│   │   ├── appsflyer.py
│   │   ├── adjust.py
│   │   └── singular.py
│   │
│   ├── canonical_schema.py
│   ├── metrics_engine.py
│   ├── decision_engine.py
│   ├── liveops_analysis.py
│
├── dummy_data/
│   └── generate_dummy_data.py
│
└── requirements.txt
```

---

## 9. UI Requirements (Streamlit)

구성 탭:

- Upload Data
  - MMP 선택
  - Install / Event / Cost Raw 업로드
- UA Decision
  - Level 선택(media/campaign/adset/creative)
  - KPI 테이블 + decision reason + efficiency note
  - ROAS gap / install gap 컬럼 제공
  - Scale Up / Down 표시
- Cohort Curve
  - Level 선택 기반 D1~D30 누적 LTV 시각화
  - 세그먼트별 비교
- LiveOps Impact
  - 이벤트 기간 입력
  - Level 선택 기반 uplift 비교
  - Cohort 비교 결과
- Experiment Report
  - MMP 더미 실험 실행
  - Insight Cards (Top/Worst/Low Sample)
  - Summary/Decision/Insight 확인

---

## 10. Expansion Capability

향후 확장 목표:

- BigQuery 데이터 소스 연결
- Creative 레벨 분석
- Geo Mix 분석
- A/B Test 분석
- SKAN 데이터 분리 처리
- Media Mix Simulation

---

## 11. Step-by-step Execution Plan

아래 순서로 대규모 개편을 진행합니다.

1. **Spec 고정**: Canonical schema / KPI 정의 / Decision rule 파라미터 확정
2. **입력 표준화**: MMP Adapter로 Raw 스키마 차이 흡수
3. **코어 계산 엔진 정비**: Cohort LTV / ROAS / Payback 계산 모듈화
4. **의사결정 엔진 분리**: rule 기반 판단 로직 모듈 단독 관리
5. **LiveOps 분석 모듈 구축**: 이벤트 전후 코호트 비교 자동화
6. **UI 재구성**: Upload → Decision → Curve → LiveOps 탭 구조 적용
7. **Dummy Data 자동화**: 시나리오 기반 샘플 데이터 생성기 운영
8. **검증 & 확장 준비**: 테스트, 성능 점검, BigQuery 연결 포인트 사전 설계

---

## 12. Development Goals for Codex

Codex 구현 범위:

- Adapter 구조 생성
- Canonical 정규화 모듈 구현
- Cohort LTV 계산 로직 구현
- ROAS 계산 함수 작성
- Decision Engine 모듈 생성
- LiveOps 비교 모듈 생성
- Streamlit UI 구성
- Dummy data 자동 생성 함수 작성

---

## 13. Key Philosophy

이 프로젝트는 단순 지표 집계 툴이 아닙니다.

목표:

- MMP Raw 구조 이해
- UA 판단 기준 명확화
- LTV 기반 사고 체계 증명
- LiveOps와 UA 연결 분석 가능

즉,

**UA 집행과 게임 비즈니스 구조를 연결하는 의사결정 엔진**을 구현합니다.

---

## 14. Run

```bash
pip install -r requirements.txt
python dummy_data/generate_dummy_data.py
streamlit run app.py
```


---

## 15. Dummy MMP Raw Scenario (for KR game teams)

실데이터 연동 전 단계에서 아래 MMP Raw 더미를 생성해 동일 분석 파이프라인을 검증할 수 있습니다.

- AppsFlyer Raw (`dummy_data/appsflyer/*.csv`)
- Adjust Raw (`dummy_data/adjust/*.csv`)
- Singular Raw (`dummy_data/singular/*.csv`)

실행 순서:

```bash
python dummy_data/generate_dummy_data.py
python dummy_data/run_mmp_experiments.py
```

또는 Streamlit Upload 탭에서 **Load MMP Dummy Raw** 버튼으로 바로 더미 로딩이 가능합니다.

생성 결과:

- `dummy_data/experiments/mmp_experiment_summary.csv`
- `dummy_data/experiments/mmp_decision_table.csv`
- `dummy_data/experiments/mmp_experiment_report.md`

---

## 16. Test

```bash
make test
```


(동일 명령: `PYTHONPATH=. pytest -q`)


## 17. CI

GitHub Actions에서 `make test`를 기본 회귀 테스트 명령으로 실행합니다.
워크플로우 파일: `.github/workflows/ci.yml`


## 18. UI 스모크 테스트 체크리스트

배포 전 최소 시나리오 점검 문서: `UI_E2E_SCENARIOS.md`

## 19. BigQuery 연동 계약 문서

Pre-BQ 컬럼/타입/정합성 기준 문서: `docs/BQ_DATA_CONTRACT.md`


## 20. PR/브랜치 보호 체크리스트

CI 체크가 머지를 막는 경우 운영 문서: `docs/BRANCH_PROTECTION_CHECKLIST.md`
