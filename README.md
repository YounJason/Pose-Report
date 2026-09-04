# Pose-Report

카메라 앞에서 30초간 자세를 측정해 거북목 · 등/허리 · 어깨 · 골반을 점수화하고, 다리 꼬기는 별도의 기하학적 휴리스틱으로 감지하는 웹 앱입니다. 측정 결과는 Gemini API로 코칭 피드백을 생성한 뒤, 화면에서 바로 A4 용지로 인쇄해 확인할 수 있습니다.

카메라 캡처(OpenCV/Astra Pro)와 자세 분석은 Python(Flask) 백엔드에서 실행되고, 프런트엔드(`index.html`/`script.js`/`style.css`)는 일반 웹 브라우저에서 로컬 서버에 접속해 사용합니다.

## 주요 기능

- 실시간 자세 분석 (MediaPipe Pose 기반 threshold 판정 + RULA 참고 가중 종합점수)
- 다리 꼬기 감지
- Astra Pro (RGB + Depth / 3D skeleton) 지원
- Gemini 기반 AI 코칭 피드백 및 A4 리포트 인쇄
- 측정 중 참가자 화면에 신뢰 채널의 유튜브 쇼츠를 자동 순환 재생

## 파일 구조

```text
Pose-Report/
├── main.py               # Flask 서버 실행 + Astra Pro 캘리브레이션 서브커맨드 포함
├── config.py              # 각도 threshold / 종합 점수 가중치 / 신뢰 채널 목록
├── index.html            # SPA 메인 화면 (screen 0~6)
├── frontend.html         # 개인정보 수집·이용 동의 안내 페이지 (정적 파일로 서빙)
├── script.js
├── style.css
├── requirements.txt
├── README.md
└── AI_CONTEXT.md         # 아키텍처/로직 상세 설명 (LLM·개발자용)
```

## 설치 및 실행

```bash
pip install -r requirements.txt

# 프로젝트 루트에 .env 생성 후 GEMINI_API_KEY, SUPABASE_ANON_KEY, YOUTUBE_API_KEY 등 설정
# config.py의 TRUSTED_YT_CHANNELS에 자동 재생할 유튜브 채널 ID 등록

python main.py
```

## 코드를 수정하는 AI이신가요?

이 프로젝트는 바이브 코딩으로 관리합니다.
아키텍처와 로직에 대한 상세한 설명은 [`AI_CONTEXT.md`](./AI_CONTEXT.md)에 정리되어 있으니, 코드를 수정하기 전에 먼저 읽어보세요.
