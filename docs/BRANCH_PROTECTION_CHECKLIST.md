# GitHub 브랜치 보호 설정 체크리스트

PR이 열려 있어도 `0/2`처럼 보이거나 머지가 막히는 경우를 줄이기 위한 운영 체크리스트입니다.

## 1) Required status checks

브랜치 보호 규칙에서 아래 체크를 필수로 지정합니다.

- `CI / test`

> 현재 워크플로우 파일: `.github/workflows/ci.yml`

---

## 2) 권장 브랜치 보호 옵션

- [x] Require a pull request before merging
- [x] Require status checks to pass before merging
- [x] Require branches to be up to date before merging
- [x] Do not allow bypassing the above settings

---

## 3) 체크 실패 시 빠른 점검

1. **Actions 로그 확인**
   - `pytest: not found` / dependency missing / test fail 여부 확인
2. **워크플로우 트리거 확인**
   - `push`, `pull_request` 이벤트에서 실행되는지 확인
3. **워크플로우 이름/잡 이름 일치 확인**
   - 보호 규칙의 required check 이름과 실제 실행 이름이 같은지 확인
4. **최신 커밋으로 재실행**
   - `Re-run all jobs` 또는 새 커밋 push

---

## 4) 기준 명령

- 로컬/CI 공통 회귀 명령: `make test`
- 내부 실행: `PYTHONPATH=. pytest -q`
