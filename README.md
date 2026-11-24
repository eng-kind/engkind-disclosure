# 영문공시 대상 조회 사이트 — 30분 자동 확인판 (engkind 계정)

## 바뀐 점

- **GitHub Actions가 30분마다 KIND '오늘의 공시'를 직접 확인**해 누적합니다. 엑셀을 매번 올리지 않아도 됩니다.
- KIND 목록에서 접수번호를 함께 가져오므로 **공시 링크가 바로 붙습니다.** 자동 확인분은 AI 링크 검색을 쓰지 않습니다(API 비용 없음).
- 누적 자료는 앱 코드와 분리된 **`data` 브랜치**에 저장됩니다. 30분마다 저장해도 Streamlit 앱이 재시작되지 않습니다.
- 사이트 상단에 **자동 확인 상태**(마지막 확인 시각, 성공/실패, 실패 원인)가 표시됩니다.
- 엑셀 업로드는 **예비 수단**으로 남겼습니다. 자동 확인이 실패하면 업로드 칸이 자동으로 펼쳐집니다. 자동 확인분과 같은 공시는 중복 추가하지 않습니다.
- 자동 저장 기록의 작성자는 `engkind <engkind@krx.co.kr>`입니다.
- 누적 파일 크기 관리: 최근 14일 공시는 전부, 그보다 오래된 공시는 대상법인 공시만 남깁니다. 기존 대상 결과는 그대로 유지됩니다(10/06 코스피 13건 등 확인).

## ⚠️ 먼저 알아둘 점: KIND 차단

KIND가 크롤링을 막은 방식에 따라 GitHub 서버(해외 클라우드)에서의 접속도 막힐 수 있습니다.
이 프로그램은 차단을 우회하지 않습니다. 대신 자신을 `KRX-engkind-disclosure-monitor`(연락처 engkind@krx.co.kr)로 밝히고 접속합니다.

- 첫 수동 실행(아래 4단계)에서 바로 확인됩니다.
- 막히면 사이트에 "KIND 자동 확인 실패 · KIND가 접속을 거부했습니다 (HTTP 403)"처럼 표시되고, engkind@krx.co.kr로 GitHub 실패 메일이 옵니다.
- 막혔을 때 선택지
  1. KRX IT(KIND 운영 부서)에 위 이름의 접속을 30분 간격으로 허용해달라고 요청합니다. GitHub 서버 IP는 고정되지 않으므로 IP 허용보다는 이 이름(User-Agent) 기준 허용을 요청하는 편이 현실적입니다.
  2. 같은 `kind_collector.py`를 회사 내부망 PC에서 실행하도록 바꿉니다(필요하면 별도 안내).
  3. 그동안은 '예비: 엑셀 직접 업로드'로 운영합니다.

## engkind 계정으로 이전하기

### 1. GitHub 계정 만들기

1. https://github.com/signup 에서 **engkind@krx.co.kr**로 가입합니다. 확인 메일을 받을 수 있어야 합니다.
2. 사용자명(예: `krx-engkind`)을 정합니다. 사이트 주소와 Secrets의 `owner`에 쓰입니다.
3. 회사 메일로 외부 서비스에 가입해도 되는지 사내 정책을 확인하세요.

### 2. 저장소 만들고 파일 올리기

1. 새 계정으로 **New repository** → 이름 예: `engkind-disclosure` → **Private** 선택 → Create.
2. ZIP 압축을 풀고 **Add file → Upload files**에서 다음을 저장소 최상위에 올립니다.
   - `kospi_engdiscl.py`, `engdiscl_rules.py`, `kind_collector.py`
   - `requirements.txt`, `requirements-collector.txt`, `README.md`, `.gitignore`
   - 기준 CSV 4개: `kospi_company.csv`, `kospi_format.csv`, `kosdaq_company.csv`, `kosdaq_format.csv`
   - `initial_disclosures.json` (기존 누적자료. 첫 실행 때 한 번만 시작점으로 사용)
3. **워크플로 파일은 따로 만듭니다.** `.github`처럼 점으로 시작하는 폴더는 업로드 창에서 빠지기 쉽습니다.
   **Add file → Create new file** → 파일 이름 칸에 `.github/workflows/kind_collect.yml` 입력 →
   ZIP 안의 같은 파일 내용을 붙여넣기 → Commit changes.

### 3. Actions 권한 켜기

저장소 **Settings → Actions → General**
- Actions permissions: **Allow all actions and reusable workflows**
- Workflow permissions: **Read and write permissions** → Save

### 4. 첫 실행으로 KIND 접속 확인

1. **Actions** 탭 → (안내가 나오면 워크플로 사용 허용) → 왼쪽 **KIND 공시 30분 확인** → **Run workflow**.
2. 1~2분 뒤 결과:
   - 초록색 ✓: 성공. `data` 브랜치가 새로 생기고 `data/disclosure_state.json`, `data/collector_status.json`이 저장됩니다.
   - 빨간색 ✗: 실행 화면의 오류 문구를 확인합니다. KIND가 보낸 화면은 실행 화면 아래 **Artifacts → kind-debug**에 7일간 보관됩니다.
3. 이후에는 30분마다(매시 5분·35분) 자동 실행됩니다.

### 5. 앱용 토큰 만들기

GitHub 오른쪽 위 프로필 → **Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token**
- Resource owner: engkind 계정, Repository access: **Only select repositories** → `engkind-disclosure`
- Permissions → Repository permissions → **Contents: Read and write**
- 만료일을 정하고, 만료 전에 다시 발급해 Secrets를 바꿔야 합니다(만료되면 사이트가 "현재 세션에만 저장" 경고를 띄웁니다).
- 생성된 토큰(github_pat_…)은 한 번만 보입니다. 바로 다음 단계에 붙여넣으세요.

### 6. Streamlit 앱 새로 배포하기

1. https://share.streamlit.io 에서 **engkind GitHub 계정으로 로그인**합니다.
2. **Create app → Deploy a public app from GitHub**
   - Repository: `engkind-disclosure`, Branch: **main**, Main file path: `kospi_engdiscl.py`
   - App URL을 원하는 이름으로 정합니다.
3. **Advanced settings → Secrets**에 아래를 붙여넣습니다(`secrets.toml.example` 참고).

   ```toml
   [github]
   token = "github_pat_..."      # 5단계 토큰
   owner = "krx-engkind"         # 1단계 사용자명
   repo = "engkind-disclosure"
   branch = "data"               # 반드시 data
   path = "data/disclosure_state.json"

   [openai]
   api_key = "sk-..."            # 기존 앱 Secrets에서 복사 (엑셀 업로드분 링크 검색용, 없어도 됨)
   model = "gpt-4.1-mini"
   ```
4. Deploy → 사이트 상단 "KIND 자동 확인 정상"과 사이드바 "누적 저장: GitHub 연결"이 보이면 완료입니다.

### 7. 기존 사이트 정리

새 사이트가 정상 동작하면 기존 Streamlit 앱을 삭제하거나 중지하고, 사이트를 쓰던 분들께 새 주소를 안내합니다.
기존 저장소의 토큰도 더 쓰지 않으면 폐기하세요.

## 운영 메모

- **실행 지연:** GitHub의 예약 실행은 몇 분, 혼잡하면 수십 분 늦어질 수 있습니다. 90분 넘게 확인이 없으면 사이트에 경고가 뜹니다.
- **무료 사용량:** Private 저장소는 Actions를 월 2,000분까지 무료로 씁니다. 30분마다 실행하면 월 약 1,500분(실행당 1분으로 계산)입니다. 넘으면 그달 남은 기간 동안 자동 확인이 멈춥니다. 저장소를 Public으로 바꾸면 제한이 없지만 누적 자료(공개된 공시 목록)가 누구에게나 보입니다. 토큰·API 키는 Secrets에 있어 공개되지 않습니다.
- **자정 직후** 실행에서는 전날 목록도 한 번 더 확인해 늦은 공시를 놓치지 않습니다.
- **기준 CSV 변경:** main 브랜치의 CSV를 바꾸면 앱과 다음 자동 확인에 모두 반영됩니다.
- **수동 확인:** 언제든 Actions → Run workflow로 즉시 확인할 수 있고, 사이트의 '최신 자료 다시 불러오기'로 화면을 갱신합니다(화면은 최대 1분간 캐시).

## 파일 구성

| 파일 | 역할 |
|---|---|
| `kospi_engdiscl.py` | Streamlit 사이트 |
| `engdiscl_rules.py` | 대상법인·대상서식 판정, 중복 판별 (사이트와 자동 확인이 함께 사용) |
| `kind_collector.py` | KIND 오늘의 공시 조회·누적 |
| `.github/workflows/kind_collect.yml` | 30분마다 자동 실행 |
| `requirements.txt` / `requirements-collector.txt` | 사이트용 / 자동 확인용 패키지 |
| `initial_disclosures.json` | 기존 누적자료(첫 실행 시작점) |

## 검증 범위

- 확인함: KIND 목록과 같은 구조의 시험 화면 해석(시각·회사코드·회사명·전체 제목·제출인·접수번호·시장), 결과 없음 화면, HTTP 403·차단 화면 감지와 상태 기록, 연속 실패 횟수,
  기존 누적자료 1,606건에서 시작해 병합·정리 후 대상 결과 유지(코스피 10/02 15건·10/06 13건·10/07 7건, 코스닥 5·14·4건),
  엑셀 업로드분과 자동 확인분 중복 방지(양쪽 순서 모두), 로컬 git으로 data 브랜치 최초 생성·갱신·푸시 충돌 재시도,
  Streamlit 화면(정상·실패·1MB 초과 파일·과거 날짜 조회).
- **확인하지 못함:** 실제 KIND 접속. 작업 환경에서 KIND 접속이 막혀 있었습니다. KIND의 실제 화면 구조가 다르면 첫 실행에서 "공시 행을 찾지 못했습니다"로 표시되며, Artifacts의 kind-debug 파일을 주시면 맞춰 수정할 수 있습니다.
  실제 GitHub·Streamlit 배포와 OpenAI 검색도 실제 계정으로는 확인하지 않았습니다.
