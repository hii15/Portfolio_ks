# BigQuery 데이터 계약(Pre-BQ)

이 문서는 현재 콘솔이 기대하는 **Canonical 스키마**를 BigQuery 테이블로 연결할 때의 최소 계약입니다.

## 1) 대상 테이블

- `fact_installs`
- `fact_events`
- `fact_cost`

---

## 2) 필수 컬럼 계약

### 2.1 `fact_installs`

| 컬럼 | 타입(권장) | 설명 | 필수 |
|---|---|---|---|
| `user_key` | STRING | 유저 식별자 | Y |
| `install_time` | TIMESTAMP | 설치 시각(UTC 권장) | Y |
| `media_source` | STRING | 매체명 | Y |
| `campaign` | STRING | 캠페인명 | Y |
| `adset` | STRING | 광고그룹 | N |
| `creative` | STRING | 소재명 | N |
| `geo` | STRING | 국가코드 | N |
| `platform` | STRING | 플랫폼(iOS/Android) | N |

### 2.2 `fact_events`

| 컬럼 | 타입(권장) | 설명 | 필수 |
|---|---|---|---|
| `user_key` | STRING | 유저 식별자 | Y |
| `event_time` | TIMESTAMP | 이벤트 시각(UTC 권장) | Y |
| `event_name` | STRING | 이벤트명 | Y |
| `revenue` | FLOAT64 | 이벤트 매출(현재 KRW 기준) | Y |

### 2.3 `fact_cost`

| 컬럼 | 타입(권장) | 설명 | 필수 |
|---|---|---|---|
| `date` | DATE | 광고비 집계일 | Y |
| `media_source` | STRING | 매체명 | Y |
| `campaign` | STRING | 캠페인명 | Y |
| `impressions` | INT64 | 노출수 | Y |
| `clicks` | INT64 | 클릭수 | Y |
| `spend` | FLOAT64 | 광고비(현재 KRW 기준) | Y |

---

## 3) 정합성 규칙

1. `fact_events.user_key`는 `fact_installs.user_key`와 조인 가능해야 함.
2. `install_time <= event_time` 조건이 대부분의 레코드에서 성립해야 함.
3. `fact_cost`는 최소 `media_source + campaign + date` 단위 집계가 가능해야 함.
4. `spend`, `revenue`는 음수 금지(환불 데이터는 별도 처리 정책 필요).

---

## 4) 운영 체크리스트

- [ ] UTC 기준 시간 저장 여부 확인
- [ ] 매체/캠페인 문자열 정규화 규칙 확인(대소문자/공백)
- [ ] KRW 기준 값인지 확인 (타 통화는 변환 정책 필요)
- [ ] 일별 적재 누락 여부 모니터링 (install/event/cost)

---

## 5) 장애 시 우선 점검

- 업로드 오류 코드 `E001~E007` 대응 가이드를 우선 확인
- 템플릿 기준 컬럼과 실제 BQ 뷰 컬럼 차이 확인
- 조인키(`user_key`) null/중복 분포 확인
