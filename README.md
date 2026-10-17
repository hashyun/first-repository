# 주식 투자심사 승인서 생성기

은행 **여신심사 승인서** 형식을 주식 투자 의사결정에 적용한 도구입니다.
종목 하나를 "여신 신청"처럼 심사하여, 공시(OpenDART)·거시지표(한국은행 ECOS, FRED)·정량 평점·LLM 심사의견을 근거로
**승인 / 조건부승인 / 보류 / 거절** 판정, **투자한도**, **승인조건(약정)** 이 담긴 승인서를 Markdown/HTML 로 만듭니다.

> **면책**: 이 도구의 결과물은 공개 데이터와 자동 분석에 기반한 **투자 참고용 자료이며, 투자 권유·투자 자문이 아닙니다.**
> 데이터 오류·누락·모델 한계가 있을 수 있으며, 투자 판단과 그 결과에 대한 책임은 투자자 본인에게 있습니다.

## 빠른 체험 (API 키 불필요)

```bash
pip install -r requirements.txt
python -m invest_memo --demo
```

번들된 **가상 데이터**로 승인서를 만들어 `reports/000000_YYYYMMDD.md`, `.html` 로 저장합니다.

## 설치

Python 3.13 기준입니다.

```bash
pip install -r requirements.txt
cp .env.example .env     # 발급받은 키를 .env 에 입력
```

`anthropic`(LLM 심사의견)과 `finance-datareader`(주가·밸류에이션)는 **선택 설치**입니다.
설치돼 있지 않거나 키가 없으면 해당 부분만 규칙 기반 문장 / `N/A` 로 처리하고 나머지는 정상 동작합니다.

## API 키 발급

| 환경변수 | 용도 | 발급처 |
|---|---|---|
| `DART_API_KEY` | 기업개요·재무제표·공시 | https://opendart.fss.or.kr (회원가입 후 인증키 신청) |
| `ECOS_API_KEY` | 국내 거시지표(기준금리, 환율, CPI, 국고채) | https://ecos.bok.or.kr/api (인증키 신청) |
| `FRED_API_KEY` | 미국/글로벌 거시지표(연방기금금리, VIX 등) | https://fred.stlouisfed.org/docs/api/api_key.html |
| `ANTHROPIC_API_KEY` | (선택) Claude 심사의견 | https://console.anthropic.com |
| `LLM_MODEL` | (선택) 모델 변경, 기본 `claude-sonnet-5-5` | |

키는 `.env` 파일에만 두세요. `.env` 는 `.gitignore` 에 포함돼 있어 커밋되지 않습니다.

## 사용법

```bash
python -m invest_memo --stock 005930 --amount 10000000 --portfolio 100000000 \
    [--year 2025] [--no-llm] [--format md,html] [--out reports/]
```

| 옵션 | 설명 | 기본값 |
|---|---|---|
| `--stock` | 종목코드 6자리 | (필수, `--demo` 제외) |
| `--amount` | 신청금액(원) | 10,000,000 |
| `--portfolio` | 포트폴리오 규모(원) | 100,000,000 |
| `--year` | 기준 사업연도 | 작년 |
| `--no-llm` | LLM 미사용, 규칙 기반 심사의견 | 꺼짐 |
| `--format` | `md`, `html` (쉼표 구분) | `md,html` |
| `--out` | 출력 디렉터리 | `reports/` |
| `--reviewer` | 심사자 표기 | 자동심사 |
| `--demo` | 가상 데이터로 실행(외부 호출 없음) | 꺼짐 |

출력: `reports/{종목코드}_{YYYYMMDD}.md`, `.html` (HTML 은 A4 인쇄용 스타일 포함)

API 응답은 `.cache/` 에 1일간 캐시됩니다.

## 승인서 구성

1. 신청개요 2. 기업개요 3. 재무분석 4. 거시환경 5. 최근 주요 공시 6. 리스크 요인
7. 평점표 및 내부등급 8. 심사의견 9. 승인 판정·투자한도·승인조건 10. 결재란

## 심사 로직 요약

- **평점(100점)**: 재무안정성 25 / 수익성 20 / 성장성 15 / 현금흐름 15 / 밸류에이션 10 / 거시환경 15.
  구간표는 `invest_memo/analysis/scoring.py` 상단 상수에서 조정합니다.
  데이터가 없는 항목은 "N/A" 로 표시하고 배점을 나머지 항목에 비례 재배분합니다.
- **판정/한도**: 80점 이상 승인(10%), 70–79 승인(7%), 60–69 조건부승인(5%, 분할매수), 50–59 보류, 50 미만 거절.
  신청금액이 한도(포트폴리오 대비 %)를 넘으면 한도로 감액 승인합니다.
- **녹아웃**: 자본잠식, 비적정 감사의견·횡령·배임·거래정지 등 공시 키워드는 거절,
  2년 연속 영업적자·이자보상배율 2년 연속 1 미만은 보류로 하향합니다.
- **심사의견**: Claude 가 구조화된 분석 결과만으로 작성합니다(없는 수치 생성 금지 지시).
  LLM 호출 실패 시 규칙 기반 문장으로 대체하고 승인서 비고에 기록합니다.
  다른 LLM 은 `invest_memo/llm/base.py` 의 `LLMProvider` 를 구현한 클래스를 추가하면 연결할 수 있습니다.

## 테스트

```bash
python -m pytest -q
```

네트워크 없이 fixture 와 monkeypatch 로만 동작합니다.

## 한계

- 재무 계정 매칭은 IFRS `account_id` 우선, 실패 시 계정명 키워드이므로 일부 업종(금융업 등)은 항목이 비어 `N/A` 일 수 있습니다.
- PER/PBR 은 FinanceDataReader 로 시가총액을 조회할 수 있을 때만 계산합니다.
- ECOS 통계표/항목 코드는 `invest_memo/sources/ecos.py` 의 `SERIES` 에서 조정할 수 있습니다.
