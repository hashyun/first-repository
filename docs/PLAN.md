# 주식 투자심사 승인서 생성기 — 설계 계획

은행 여신심사 승인서 형식을 주식 투자 의사결정에 적용한다.
종목 하나를 "여신 신청"처럼 심사하고, 공시·거시 데이터와 정량 평점, LLM 심사의견을 근거로
**승인 / 조건부승인 / 보류 / 거절**과 **투자한도**, **승인조건(약정)**을 담은 승인서를 만든다.

## 1. 데이터 소스

| 소스 | 환경변수 | 용도 | 주요 엔드포인트/시리즈 |
|---|---|---|---|
| OpenDART | `DART_API_KEY` | 기업개요, 재무제표, 공시 | `corpCode.xml`(종목코드→corp_code), `company.json`, `fnlttSinglAcntAll.json`(연결 우선, 없으면 별도), `list.json`(최근 공시), `hyslrSttus.json`(최대주주) |
| 한국은행 ECOS | `ECOS_API_KEY` | 국내 거시 | 기준금리 `722Y001/0101000`, 원/달러 `731Y001/0000001`, CPI `901Y009/0`, 국고채3년 `817Y002/010200000` |
| FRED | `FRED_API_KEY` | 미국/글로벌 거시 | `DFF`(연방기금금리), `DGS10`, `VIXCLS`, `T10Y2Y`(장단기 금리차), `CPIAUCSL` |
| 주가 | (없음, 선택) | 밸류에이션·변동성 | `FinanceDataReader`가 설치돼 있으면 사용, 없으면 밸류에이션 항목 "N/A" 처리 |
| LLM | `ANTHROPIC_API_KEY` | 심사의견 서술 | `claude-sonnet-5-5` 기본, `LLM_MODEL`로 변경 가능. 키 없으면 규칙 기반 템플릿 문장 |

> "Jev AI"가 특정 서비스를 뜻하는지 불명확하여 LLM 계층은 `LLMProvider` 인터페이스로 분리하고 Claude를 기본 구현으로 둔다. 다른 제공자는 클래스 하나 추가로 연결 가능.

모든 API 클라이언트는 `requests` + 타임아웃 + 단순 재시도, 응답은 `.cache/`에 JSON 파일 캐시(TTL 1일)로 저장해 반복 호출을 줄인다.

## 2. 패키지 구조

```
invest_memo/
  __init__.py
  __main__.py          # python -m invest_memo
  cli.py               # argparse CLI
  config.py            # .env 로드, 설정 dataclass
  cache.py             # 파일 캐시
  sources/
    dart.py            # DartClient
    ecos.py            # EcosClient
    fred.py            # FredClient
    price.py           # 선택적 주가 조회
  analysis/
    financials.py      # 재무비율 계산 (3개년)
    macro.py           # 거시 지표 요약/국면 판단
    scoring.py         # 항목별 평점 → 내부등급
    decision.py        # 승인 판정, 투자한도, 승인조건
  llm/
    base.py            # LLMProvider 프로토콜 + RuleBasedProvider
    claude.py          # ClaudeProvider (anthropic SDK)
  report/
    builder.py         # MemoData 조립
    templates/memo.md.j2
    templates/memo.html.j2
    render.py          # Markdown/HTML 출력
tests/                 # pytest, 네트워크 없이 fixture로 검증
  fixtures/*.json
.env.example
requirements.txt
README.md (한국어 사용법)
```

## 3. 분석 로직

### 3.1 재무비율 (최근 3개 사업연도)
- 안정성: 부채비율, 유동비율, 차입금의존도, 이자보상배율(영업이익/이자비용)
- 수익성: 영업이익률, 순이익률, ROE, ROA
- 성장성: 매출 성장률, 영업이익 성장률
- 현금흐름: 영업현금흐름/순이익, FCF(영업CF − CAPEX)
- 밸류에이션(주가 있을 때): PER, PBR, 1년 변동성, 52주 고점 대비 낙폭

DART 계정은 `account_id`(IFRS 표준코드) 우선 매칭, 실패 시 `account_nm` 키워드 매칭.

### 3.2 평점표 (100점 만점)
| 항목 | 배점 |
|---|---|
| 재무안정성 | 25 |
| 수익성 | 20 |
| 성장성 | 15 |
| 현금흐름 | 15 |
| 밸류에이션 | 10 (데이터 없으면 배점을 다른 항목에 비례 재배분) |
| 거시환경 | 15 |

각 지표는 구간표(threshold table)로 0~1 점수화 → 항목 가중합. 구간표는 `scoring.py` 상단 상수로 두어 조정 쉽게.

거시환경 점수: 기준금리/연방기금금리 방향(최근 6개월 변화), VIX 수준, 장단기 금리차 역전 여부, 원/달러 급변 여부.

### 3.3 내부등급 및 판정
| 점수 | 등급 | 판정 | 기본 투자한도(포트폴리오 대비) |
|---|---|---|---|
| ≥ 80 | A+ / A | 승인 | 10% |
| 70–79 | B+ | 승인 | 7% |
| 60–69 | B | 조건부승인 | 5% |
| 50–59 | C | 보류 | 0% (재심사) |
| < 50 | D | 거절 | 0% |

**녹아웃(Knock-out) 규칙** — 점수와 무관하게 등급 하향/거절:
- 자본잠식, 2년 연속 영업적자, 이자보상배율 < 1 2년 연속
- 최근 90일 내 감사의견 비적정·횡령/배임·거래정지 관련 공시 키워드

신청금액이 한도를 넘으면 한도로 감액 승인.

### 3.4 승인조건 (Covenants)
- 손절선: 진입가 대비 −(변동성 기반, 8~15%)
- 재심사 트리거: 분기 실적 발표 시, 부채비율 기준 초과 시, 기준금리 변경 시
- 분할매수 권고(조건부승인일 때)

## 4. 승인서 양식

1. 신청개요 (종목, 신청금액, 신청일, 심사자)
2. 기업개요 (DART 기업정보, 최대주주)
3. 재무분석 (3개년 표 + 해설)
4. 거시환경 (국내/미국 지표 표)
5. 최근 주요 공시 (90일)
6. 리스크 요인 (녹아웃·경고 항목)
7. 평점표 및 내부등급
8. 심사의견 (LLM 또는 규칙 기반)
9. 승인 판정 · 투자한도 · 승인조건
10. 결재란 (담당 / 심사역 / 승인권자 칸)
- 하단 고지: 투자 참고용이며 투자 권유가 아님

출력: `reports/{종목코드}_{YYYYMMDD}.md`, `.html`

## 5. CLI

```bash
python -m invest_memo --stock 005930 --amount 10000000 --portfolio 100000000 \
    [--year 2025] [--no-llm] [--format md,html] [--out reports/]
```

## 6. 테스트
- 각 클라이언트: fixture JSON으로 파싱 검증 (`requests` monkeypatch)
- 재무비율·평점·판정: 경계값 단위 테스트, 녹아웃 테스트
- 엔드투엔드: 모든 소스를 fixture로 대체하고 `--no-llm`으로 승인서 생성, 필수 섹션 존재 확인

## 7. 실행 분담
- 계획: Opus (이 문서)
- 구현: Sonnet 서브에이전트
