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
| `functions/items.json.js` | Cloudflare Pages Functions 기반 비공개 R2 버킷(`ICONS_BUCKET`) `items.json` 프록시 |
| `functions/icons/[name].js` | Cloudflare Pages Functions 기반 비공개 R2 버킷(`ICONS_BUCKET`) 아이콘 프록시 |
| `index.html` / `app.js` / `styles.css` | 동적 스키마(`categories`, `classSchemas`) 및 아이콘 렌더링 기반 정적 웹 전산 뷰어 |

## 실행 환경 및 사용법

- **Python 버전**: `Python 3.10.9` (`extract_items.py`: 표준 라이브러리 / `extract_icons.py`: `Pillow`)
- **스키마 버전**: `1.1.0`

```bash
# 1. 아이템 JSON 추출 및 자동 검증 (로컬 items.json 생성, Git 추적 제외)
python total-darkwoods/extract_items.py

# 2. 아틀라스 크롭 및 개별 아이콘 PNG 추출 (로컬 total-darkwoods/icons/, Git 추적 제외)
python total-darkwoods/extract_icons.py

# 3. 정적 웹 전산(lister) 로컬 실행 (http://localhost:8000)
python -m http.server 8000 --directory total-darkwoods
```

## CI/CD 연동 흐름

1. `DarkWood2` 메인 레포 업데이트 시 CI가 본 레포(`total-darkwoods`)의 추출 스크립트를 가져옵니다.
2. `extract_items.py`와 `extract_icons.py`를 실행해 최신 `items.json`과 `icons/*.png`를 생성 및 검증합니다.
3. 생성된 `items.json`과 `icons/*.png`를 비공개 Cloudflare R2 버킷에 직접 업로드하며, 웹 전산은 Pages Functions 프록시를 통해 R2에서 데이터를 불러옵니다.
