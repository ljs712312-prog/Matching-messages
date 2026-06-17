# 법원 경매 문자 주소조회

경매 문자 원본을 붙여 넣으면 사건번호, 물건번호, 전화번호, 물건정보, 비고를 정리하고 법원경매정보에서 주소, 동, 층, 호수를 조회해 엑셀로 내려받는 Streamlit 웹앱입니다.

지번 변환 API는 사용하지 않습니다. 법원경매정보에서 확인되는 주소만 채우고, 도로명주소를 지번주소로 바꾸는 작업은 사용자가 별도로 처리합니다.

## 로컬 실행

```powershell
cd auction_lookup_web
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m playwright install chromium
streamlit run app.py
```

기본 비밀번호는 `1234`입니다. 필요하면 `.env`에 아래처럼 로컬 설정만 넣어 바꿀 수 있습니다.

```env
OFFICE_PASSWORD=원하는비밀번호
DEFAULT_COURT=수원
DEFAULT_YEAR=2026
```

## Streamlit Community Cloud 배포

1. 이 폴더 내용을 GitHub 저장소에 올립니다.
2. Streamlit Community Cloud에서 `Create app`을 누릅니다.
3. Repository, branch, main file path를 선택합니다.
4. main file path는 `app.py`로 지정합니다.
5. Python version은 로컬과 맞춰 `3.12`를 권장합니다.
6. 비밀번호를 바꾸려면 Advanced settings의 Secrets에 `OFFICE_PASSWORD="원하는비밀번호"`를 넣습니다.
7. Deploy를 누릅니다.

배포에 필요한 파일:

- `requirements.txt`: Python 패키지
- `packages.txt`: Streamlit Cloud Linux 환경에서 Chromium 설치
- `app.py`: Streamlit 진입점

## 테스트

```powershell
pytest
```

## 운영 메모

- 카카오, 네이버, 공공데이터 API 키는 필요하지 않습니다.
- `.env`는 `.gitignore`에 포함되어 있으므로 GitHub에 올리지 않습니다.
- 조회 실패 시 프로그램을 멈추지 않고 `확인필요사유`에 이유를 남깁니다.
- 법원경매정보 사이트 구조가 바뀌면 조회 파서 수정이 필요할 수 있습니다.
