# 당뇨병 치료제 정보분석실 v2 — 클라우드 자동 갱신판

**기준: 2026-10-30 / 데이터 출처는 PubMed·ClinicalTrials.gov·openFDA 3곳**

GitHub Actions가 매일 아침 공식 공개 API를 확인하고, 변경 정보를 GitHub 저장소에 누적한 뒤, GitHub Pages에 스마트폰에서도 열리는 웹페이지를 배포하는 개인 연구용 프로젝트입니다. **이 ZIP을 받아 HTML만 열면 자동 수집이 진행되는 것은 아닙니다.** GitHub에 한 번 배포해야 합니다.

## 현재 무엇이 되는가

| 기능 | 상태 |
|---|---|
| PubMed 논문 제목·서지 자동 수집 | 코드 구현, 모의 API 테스트 성공 / 실서버 연결 미검증 |
| ClinicalTrials.gov 임상시험 등록정보 수집 | 코드 구현, 모의 API 테스트 성공 / 실서버 연결 미검증 |
| openFDA 미국 의약품 라벨 버전 추적 | 코드 구현, 모의 API 테스트 성공 / 실서버 연결 미검증 |
| 재수집 중복 방지, 동일 자료 ID 변경 감지 | 오프라인 자동 테스트 성공 |
| 07:17 KST GitHub Actions 예약 실행 | workflow 파일 제공, GitHub 계정에 실제 활성화 필요 |
| GitHub Pages 한국어 모바일 웹사이트 | HTML 생성 완료, 실제 웹주소 배포 전 |
| 검색, 자료원 필터, 공식 문서 링크 | 구현 완료 |
| AI 우선 검토 초안 (OpenAI API) | 선택 기능, 별도 API 키·요금 필요 / 실 API 호출 미검증 |
| 식약처·심평원 국내 허가/급여 자동 감시 | **미구현** — 사이트에 명시적으로 표시 |
| 긴급 안전성 이메일/문자 알림 | 미구현 |

## 가장 쉬운 배포 방법 (Windows 사용자 기준)

### 1) GitHub 계정과 저장소 준비

1. [github.com](https://github.com/)에 로그인하거나 무료 계정을 만듭니다.
2. 컴퓨터에 [GitHub Desktop](https://desktop.github.com/)을 설치해 로그인합니다.
3. 받은 ZIP을 압축 해제합니다. `diabetes_ai_cloud_v2` 폴더 안에는 `.github/workflows/update.yml`, `pharma_lab.py`, `update_site.py`, `site/` 등이 있습니다. Windows에서는 `.github` 폴더가 숨김파일/폴더처럼 보일 수 있습니다.
4. GitHub Desktop에서 **File → Add Local Repository**로 압축 해제한 폴더를 선택합니다. Git 저장소가 아니라는 안내가 나오면 **Create a repository here**를 선택합니다. (앱 버전에 따라 메뉴 문구가 다를 수 있습니다.)
5. 변경된 파일을 commit하고 **Publish repository**를 누릅니다. 저장소 이름 예시: `diabetes-pharma-lab`. **Keep this code private** 체크를 해제해 **Public** 저장소로 게시하면 GitHub Free에서 Pages를 사용할 수 있습니다. 이 프로젝트는 공개 의약품 정보만 취급해야 합니다.

### 2) 웹사이트 공개 설정 (한 번만)

GitHub 웹사이트에서 방금 만든 저장소를 엽니다.

- `Settings → Pages → Build and deployment → Source`를 **GitHub Actions**로 선택합니다.
- `Settings → Actions → General → Workflow permissions`에서 **Read and write permissions**을 허용합니다. `contents: write` 권한이 조직 정책에 의해 제한되어 있다면 관리자에게 설정을 요청해야 합니다.
- `Actions` 탭에서 **Daily diabetes drug research update**를 선택하고 `Run workflow`를 눌러 처음 한 번 실행합니다. 초기 Push에서 이미 실행된 경우 Pages 설정 전에 실패했을 수 있으므로, Pages 설정 뒤 다시 수동 실행하세요.
- 실행이 성공하면 `Settings → Pages → Visit site`로 실제 웹사이트에 들어갑니다. 주소 형태는 `https://<GitHub아이디>.github.io/<저장소명>/`이며, 실제 주소는 GitHub가 표시하는 것을 사용하세요.

### 3) 예약 갱신

워크플로에 `17 22 * * *`이 설정되어 있습니다. **UTC 22:17 = 한국시간 다음 날 오전 7:17**입니다. 컴퓨터를 켜두지 않아도 GitHub 서버에서 실행합니다. GitHub 측 사정으로 시작이 지연될 수 있으며, 매일 정확히 같은 초에 실행되는 것은 아닙니다.

수집한 정보는 `data/pharma_lab.sqlite3`에 누적 기록되어 저장소에 반영됩니다. 생성된 `site/index.html`, `site/feed.json`, `site/latest_report.md`도 갱신합니다. 웹 화면은 열어둔 상태에서도 30분에 한 번 자동 새로고침하도록 구현돼 있습니다.

**주의:** GitHub는 공개 저장소에 사용자 활동이 60일간 없으면 예약 실행을 비활성화할 수 있습니다. `Actions`에서 주기적으로 정상 실행 여부를 확인하세요. GitHub Pages는 공개 웹사이트입니다.

### 4) 무료 기본 사용과 AI 선택 기능

기본 수집/보고는 API 키 없이 실행을 시도합니다. 이때 화면에 표시되는 내용은 논문·임상시험·라벨 메타데이터를 바탕으로 자동 생성된 **규칙 기반 요약**이며, 임상적 결론을 생성하는 AI 분석은 아닙니다.

AI가 최근 자료를 선별하고 추가 확인해야 할 질문을 생성하게 하려면:

1. `Settings → Secrets and variables → Actions → Secrets → New repository secret`
2. 이름을 정확히 `OPENAI_API_KEY`로 하여 본인의 OpenAI API 키 저장. **API 키는 GitHub 파일, 채팅, 공개 웹페이지에 직접 붙여 넣지 마세요.**
3. 선택적으로 `Variables`에서 `OPENAI_MODEL`을 설정합니다. 설정하지 않으면 `gpt-4.1-mini`를 시도합니다. 계정/서비스에서 해당 모델을 쓸 수 없다면 사용 가능한 모델로 변경해야 합니다.
4. 다시 `Actions → Run workflow`를 실행합니다.

AI 기능에는 **ChatGPT 월 구독과 별개로 API 사용요금**이 발생할 수 있습니다. 이 기능은 논문 제목 및 공개 메타데이터만으로 ‘검토 질문’을 작성하므로 임상적 유효성·안전성을 단정하지 않으며, 전문 원문 검증 없이 사용하지 마세요. API 오류가 나면 AI 보고서는 숨기고 기존 대시보드만 게시합니다.

NCBI 권장 연락처를 지정하려면 `Settings → Secrets and variables → Actions → Variables`에 `PHARMA_CONTACT_EMAIL`을 추가하세요. PubMed API 사용량은 기본 제한(키 없이 초당 3회)을 고려해 제한되어 있습니다. NCBI 공식 API 이용 정책을 따라야 합니다.

### 5) 혼동하기 쉬운 점

- **'오늘 처음 수집'은 '오늘 새롭게 발표된 연구'와 다릅니다.** 사이트에서 발표일과 최초 수집일을 별도 표시합니다.
- **FDA 라벨은 미국 정보**이며 국내 허가나 급여 적용을 증명하지 않습니다.
- PubMed 자동 수집은 **논문 제목·서지정보만** 수집합니다. 실제 연구결과/부작용의 방향을 AI가 판단하게 하지 않습니다.
- 임상시험 **등록정보는 임상 효능 입증이 아닙니다**.
- 새로 추가한 등록·라벨·논문은 다양한 이유로 누락될 수 있습니다. UI에 자료원별 성공/실패를 보여주지만 3개 자료원 모두 성공했다고 전체 관련 정보의 완전성을 보증하지 않습니다.
- **식약처 안전성서한·허가변경, 심평원 급여기준 자동 추적 기능은 아직 없습니다.** 다음 버전에서 공식 데이터 소스별 구현 및 원문 검증이 필요합니다.
- 개인정보·환자별 처방·환자 이름·약국 영업비밀을 이 공개 저장소나 AI 분석 입력에 포함하지 마세요.

## 로컬에서 테스트 및 실행하는 법

Python 3.12 이상이 있으면 프로젝트 폴더에서:

```bash
python -m unittest discover -s tests -v
python update_site.py
python update_site.py --live
```

외부 API 연결이 없는 환경에서는 `--live` 수집이 실패하고 그 상태가 사이트에 표시됩니다. 실패한 데이터를 성공한 것으로 위장하지 않습니다. 생성된 화면은 `site/index.html`입니다. 기본 화면은 배포 후 첫 수집 전까지 빈 화면입니다.

## 주요 파일

- `update_site.py`: 3개 공식 API 수집, 기존 자료와 비교, 사이트 보고서 생성
- `pharma_lab.py`: API 파서·SQLite 변경 추적·데이터 정합성 로직
- `ai_brief.py`: 선택적 OpenAI API 연구자료 검토 질문 생성
- `config.json`: 감시 약물 22개, 논문 검색식, 주요 임상시험·라벨 감시 성분
- `.github/workflows/update.yml`: 매일 07:17 KST 자동 실행·GitHub Pages 배포
- `data/pharma_lab.sqlite3`: 수집 이력(초기에는 비어 있음)
- `site/index.html`: 웹페이지, `site/feed.json`: 사이트 데이터
- `tests/test_cloud.py`: 서버 접속 없이 실행 가능한 모의 API 테스트

## 비용·제한

GitHub Free의 **공개 저장소**로 GitHub Pages와 Actions를 시작할 수 있습니다(정책·이용량 제한에 따름). 비공개 저장소나 추가 API 사용은 요금이 달라질 수 있습니다. 웹페이지는 공개됩니다. 매일 자동으로 돌아가는 코드/웹 화면을 만들었지만, 실제 본인 계정에서의 배포와 예약 실행 권한 부여는 사용자가 승인해야만 가능합니다.

공식 문서:

- [GitHub Pages 설정](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site)
- [GitHub scheduled workflows](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows)
- [NCBI E-utilities 이용 정책](https://support.nlm.nih.gov/kbArticle/?pn=KA-05510)
- [ClinicalTrials.gov API](https://clinicaltrials.gov/data-api/api)
- [openFDA Drug Label API](https://open.fda.gov/apis/drug/label/how-to-use-the-endpoint/)
