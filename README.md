# Total Darkwoods (`lister`)

`DarkWood2/ForestOfSteel` Unity 프로젝트의 C# 스크립트와 `.asset` 데이터를 Unity 에디터 실행 없이 정적 분석하여 JSON 데이터베이스(`items.json`)로 추출·검증하는 아이템 전산 레포지토리입니다.

## 핵심 구조 (Zero-Hardcoding)

- **동적 스키마 탐색**: `Assets/_Game/01.Scripts/**/*.cs`를 스캔하여 `ItemData` 상속 클래스, 스크립트 GUID, `[SerializeField]` 필드, 기본값, `enum`을 자동 수집합니다.
- **대분류 자동 추론**: `ItemUIFormatter.GetTypeName` 분기문 및 클래스 메타데이터를 파싱해 신규 대분류(`itemType`)나 클래스가 추가되어도 스크립트 수정 없이 자동 반영됩니다.
- **다형성 속성(`attributes`)**: 클래스별 고유 직렬화 필드는 각 아이템의 `attributes` 객체에 동적으로 매핑되며, 메타데이터는 최상위 `categories`, `classSchemas`, `enumSchemas`에 수록됩니다.

## 파일 구성

| 파일명 | 설명 |
|---|---|
| `extract_items.py` | 순수 Python 3 표준 라이브러리 기반 C# 스키마 동적 분석 및 `.asset` 추출/검증 CLI |
| `extract_icons.py` | 원본 텍스처 및 아틀라스(`rect`) 크롭 기반 개별 아이콘 PNG(`icons/*.png`) 추출 CLI |
| `functions/icons/[name].js` | Cloudflare Pages Functions 기반 비공개 R2 버킷(`ICONS_BUCKET`) 아이콘 프록시 |
| `index.html` / `app.js` / `styles.css` | 동적 스키마(`categories`, `classSchemas`) 및 아이콘 렌더링 기반 정적 웹 전산 뷰어 |
| `items.json` | 추출 및 검증 완료된 아이템 데이터 (`.gitignore` 제외 대상, CI/로컬 생성) |
| `items.schema.json` | JSON Schema (Draft 2020-12) 검증 정의 파일 |

## 실행 환경 및 사용법

- **Python 버전**: `Python 3.10.9` (`extract_items.py`: 표준 라이브러리 / `extract_icons.py`: `Pillow`)
- **스키마 버전**: `1.1.0`

```bash
# 1. 아이템 JSON 추출 및 자동 검증
python total-darkwoods/extract_items.py

# 2. 아틀라스 크롭 및 개별 아이콘 PNG 추출 (total-darkwoods/icons/)
python total-darkwoods/extract_icons.py

# 3. 정적 웹 전산(lister) 로컬 실행 (http://localhost:8000)
python -m http.server 8000 --directory total-darkwoods
```

## CI/CD 연동 흐름

1. `DarkWood2` 메인 레포 업데이트 시 CI가 본 레포(`total-darkwoods`)를 함께 체크아웃합니다.
2. `extract_items.py`를 실행해 최신 `items.json`을 생성 및 검증합니다.
3. 변경된 `items.json`을 본 레포에 자동 커밋/푸시하여 정적 웹 전산을 갱신합니다.
