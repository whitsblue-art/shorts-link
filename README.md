# shorts-link · 쇼핑 쇼츠 자동화

쿠팡 상품 검색 → 정확한 상품 제휴 링크 → 해외 실사용 영상 탐색 → 상품 일치 검수 → 서로 다른 3장면 → 대본·음성·자막·완성 화면 검수 → 카탈로그 배포 확인 → 별도 쇼핑 채널에 비공개 업로드 → 처리 완료 확인 → 공개 순서로 실행합니다.

## 최초 연결

저장소 **Settings → Secrets and variables → Actions**에서 설정합니다. 비밀 값은 채팅·코드·로그에 넣지 않습니다.

| 종류 | 이름 | 내용 |
|---|---|---|
| Secret | `COUPANG_ACCESS_KEY` | 이미 발급받은 쿠팡 파트너스 Access Key |
| Secret | `COUPANG_SECRET_KEY` | 쿠팡 파트너스 Secret Key |
| Secret | `GEMINI_API_KEY` | 자료 탐색·대본·멀티모달 검수 |
| Secret | `SHOPPING_YOUTUBE_TOKEN_JSON` | **쇼핑 채널 전용** Google OAuth 사용자 토큰 JSON |
| Variable | `SHOPPING_CHANNEL_URL` | 쇼핑 채널 URL, @핸들 또는 UC로 시작하는 채널 ID |
| Variable | `SHOPPING_AUTOPUBLISH` | 처음에는 미설정. 시범 영상 확인 후 `true`로 한 번 설정하면 정기 실행마다 자동 게시 |

선택 설정 `REVIEW_API_KEY` / `REVIEW_MODEL`은 검수용 Gemini 키·모델을 분리할 때 사용합니다. 현재 기본 검수 모델은 `gemini-2.5-flash`이며, 다른 회사의 AI와 교차 검수하는 구현은 아닙니다. 기술 검사는 Python·Pillow·FFmpeg가 별도로 수행합니다. AI 예외, 불명확한 판정, 누락된 검사 항목은 통과로 바꾸지 않습니다.

쇼핑 채널 토큰은 기존 역사 채널 토큰과 분리합니다. 필요한 경우 로컬에서 `python authorize_youtube.py client_secret.json`으로 한 번 인증합니다. `youtube.upload`, `youtube.readonly`, `youtube.force-ssl` 범위가 필요합니다. 생성되는 `shopping_youtube_token.json`은 Git에서 제외됩니다. 채널 ID가 설정한 대상과 일치해야 업로드할 수 있습니다.

카탈로그는 **Settings → Pages → Build and deployment → Source: GitHub Actions**로 설정합니다. 채널 프로필의 외부 링크에 `https://whitsblue-art.github.io/shorts-link/`를 넣어야 합니다. 실제 배포 JSON의 상품 번호·제휴 링크·세 장의 이미지가 모두 일치해야 유튜브 업로드가 시작됩니다.

## 실행과 일정

- `Shopping connection check`는 API 연결 상태를 확인하고 보고서를 남깁니다. 상품·동영상·카탈로그를 게시하지 않습니다.
- `Zero-Click Shopper Bot`의 수동 실행은 기본적으로 **시범 영상만** 만듭니다. `publish`가 켜져야 카탈로그 배포와 유튜브 게시 단계가 실행됩니다.
- 쇼핑 일정은 매일 한국 시간 오전 9시입니다. `SHOPPING_AUTOPUBLISH=true`를 한 번 설정하면 매번 승인할 필요가 없습니다. 기존 `auto-shorts` 역사 채널의 월·수·금 일정과는 별개입니다.
- 시범 결과는 실행 페이지의 `pipeline-실행번호-시도번호` 아티팩트에서 내려받습니다. `final_shorts.mp4`, `thumbnail.jpg`, `subtitles.srt`, 원본 출처와 검수 보고서가 포함됩니다. 보관 기간은 30일입니다.
- 공개가 완료된 실행에서 **Re-run jobs**를 눌러도 새 영상을 만들지 않습니다. 결과가 불확실한 업로드는 기존 업로드를 고유 태그로 찾고, 찾지 못하면 중복 업로드하지 않고 중단합니다.
- API가 차단되거나 정확한 자료 3개를 확보하지 못하면 해당 상품을 건너뜁니다. 찾지 못한 날에는 게시하지 않습니다. 매일 반드시 게시된다는 보장은 없습니다.

## 자료 및 검수

`shopping_config.json`에서 상품 키워드와 탐색 한도를 설정합니다. 실제 상품 모델·옵션·색상·연결부까지 기준 이미지와 비교합니다. 일반적인 주방/수전 사진은 허용하지 않습니다. 과거 욕실·냄비 Unsplash 사진은 코드에서 차단합니다.

공개 페이지의 동영상 파일을 우선 탐색합니다. 로그인이나 접근 제한이 있는 샤오홍슈 페이지를 우회하지 않으므로 모든 리뷰를 자동 확보할 수는 없습니다. 영상이 부족하면 해당 상품의 판매 이미지로 구성하되, 같은 이미지를 복제해 세 장면으로 채우지 않습니다. AI로 가짜 사용 장면을 생성하지 않습니다.

외부 리뷰의 자동 게시에는 재사용 가능한 출처를 한 번 등록해야 합니다. `product_sources.json` 예시:

```json
[
  {
    "product_id": "실제쿠팡상품ID",
    "media": [
      {"url": "https://허용된호스트/원본.mp4", "type": "video", "source_url": "https://출처/게시물", "publication_allowed": true}
    ]
  }
]
```

공개 검색으로 발견했지만 사용 권한을 확인하지 않은 리뷰는 시범 영상에서만 이용됩니다. 자동 게시 실행에서는 등록된 출처와 상품 판매 자료만 사용합니다. `approved_review_url_prefixes`에도 재사용 가능한 출처를 등록할 수 있습니다. 영상 하나에서 세 구간을 추출할 수 있으나, 각 구간의 시작·중간·끝에서 정확한 상품을 확인하고 장면 유사도 검사도 통과해야 합니다.

대본은 상품명으로 뒷받침되는 내용만 사용합니다. 검증되지 않은 성능·호환·최저가·직접 써 봤다는 표현을 막습니다. TTS 원음과 대본을 대조하고, 실제 단어 타이밍으로 자막을 그립니다. 최종 파일 전체 디코딩, 검은 화면·무음·FPS·길이 검사, 장면별 3시점의 자막 OCR·상품 식별·가독성 검수도 수행합니다.

썸네일 JPG를 생성·검수하고 API 등록을 시도합니다. Shorts에서 등록 기능을 거부하는 명확한 응답은 `thumbnail_status: manual_required`로 기록합니다. **쇼츠 썸네일 자동 등록 성공을 보장하지 않습니다.** 이미지 파일은 아티팩트에 남습니다. 등록 실패 시 공개도 막으려면 `SHORTS_THUMBNAIL_MODE=required`를 실행 환경에 설정합니다.

## 데이터·장애 복구

기존 `products.json`의 번호와 기록은 유지합니다. 첫 새 상품은 기존 최대 번호 다음인 15번부터 시작하며, 필수 `id/title/link/image/verified/scenes` 구조를 유지합니다. 알려진 잘못된 과거 이미지가 있는 항목은 새 상품 등록 시 `verified=false`로 바꾸고 기록은 보존합니다. 카탈로그 화면도 이 항목들을 숨깁니다.

`pipeline_state.json`은 원격 GitHub에 업로드 의도와 결과를 저장합니다. 지우면 중복 방지 기록도 사라지므로 초기화하지 마세요. 검수한 파일의 해시가 바뀌면 게시를 막습니다. 재개할 때 이전 실행의 아티팩트를 복구합니다. 30일이 지나 파일이 만료되거나 업로드 결과가 계속 불확실하면 수동 확인이 필요합니다.

현재 쇼핑 파이프라인은 쇼츠 전용입니다. 롱폼 동시 자동 게시를 활성화하는 기능은 포함하지 않습니다.

## 로컬 검사

```sh
python -m pip install -r requirements.txt
python -m py_compile main.py video_maker.py
python -m unittest discover -s tests -v
```

FFmpeg/ffprobe와 한국어 글꼴이 필요합니다. Ubuntu에서는 `ffmpeg fonts-nanum`, Windows에서는 맑은 고딕 또는 `KOREAN_FONT` 경로를 사용합니다. 테스트에서는 합성 음원과 가짜 API 응답을 쓰며, 실제 상품 생성·게시 성공 여부는 연결 검사 및 실제 시범 실행으로 별도 확인합니다.
