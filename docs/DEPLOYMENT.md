# 무료 온라인 프로토타입 배포

## 선택한 방식

사용자가 PC를 켜 두는 무료 시연 배포를 선택했다. 기존 Docker의 PostgreSQL/PostGIS, Redis, Celery, FastAPI, React, Ollama를 유지하고 Cloudflare Quick Tunnel의 HTTPS 주소로 연결한다. 공개 접속은 Nginx의 비밀번호 인증을 통과해야 한다. 비밀번호를 받은 시연자는 수집·업로드·계산·보고서 작성을 실행할 수 있다.

호스팅·도메인 구입 비용이 없는 방식이며 PC의 전기·네트워크는 사용한다. GitHub Pages는 정적 파일 호스팅이어서 이 프로젝트의 DB와 작업 서버를 실행하지 못한다. Render 무료 PostgreSQL은 30일 만료 및 무료 웹의 영속 디스크 제한이 있다.

## 실행

Docker Desktop이 실행된 Windows에서 프로젝트 루트 기준:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/prototype.ps1 Start
powershell -ExecutionPolicy Bypass -File scripts/prototype.ps1 Status
powershell -ExecutionPolicy Bypass -File scripts/prototype.ps1 Stop
```

`Start`는 컨테이너를 준비하고, 무작위 접속 비밀번호를 생성하고, 로컬 AI 모델을 확인한 뒤 온라인 모드를 켜고 터널을 실행한다. 모델이 없으면 최초 다운로드 약 1GB가 필요하다. `Stop`은 공개 접속용 gateway/tunnel만 멈추며 운영 DB와 로컬 사이트를 보존한다. 기존 API 서비스키를 새 파일로 덮어쓰지 않는다.

- 주소: `data/deployment/public-url.txt`
- 접속 계정·비밀번호: `.secrets/prototype-access.md`
- 로컬 사이트: http://localhost:5173/
- 인증 gateway의 로컬 검증 주소: http://127.0.0.1:5180/

주소는 터널 재생성 또는 재시작 시 변경될 수 있다. `Status`는 마지막 터널 로그의 주소를 보여주므로 현재 실제 접속도 확인한다. PC 종료·절전·네트워크 단절·Docker 중단 시 사이트가 중단된다. Docker가 다시 실행되면 `unless-stopped` 정책으로 컨테이너가 재시작하지만 Windows에서 Docker 자체의 자동 실행은 사용자 설정에 따른다. 절전이나 로그인 설정을 스크립트가 변경하지 않는다.

## 데이터와 보안 경계

기존 named volume과 `data/`를 그대로 사용한다. `docker compose down -v`를 실행하지 않는다. GitHub 저장소만 새로 복제하면 기존 DB·원본·키·AI 모델이 함께 복제되는 것은 아니다. 새로운 PC는 승인된 원본의 이전 또는 재수집이 필요하다.

`.env`, `.secrets`, 백업, 실제 배포 결과는 GitHub에 올리지 않는다. 인증 파일은 무작위 192비트 비밀번호의 SHA-512 crypt 해시이며 실제 비밀번호는 로컬 인계 파일에만 기록한다. 공개 요청의 인증 헤더는 내부 애플리케이션으로 전달하지 않는다. 교차 출처 브라우저 쓰기 요청을 거부한다. 접속 계정은 시연용 공용 계정이며 개인별 권한·감사 시스템은 아니다.

DB/API/Redis/Ollama의 별도 인터넷 포트를 열지 않는다. Cloudflare는 HTTPS를 종료하고 gateway로 요청을 전달한다. 원본 제공기관의 이용 조건과 데이터 공개 범위는 유지해야 한다.

## 동작과 외부 자료의 구분

온라인 모드는 실제 작업 큐를 통한 수집을 허용한다. 유효한 개별 서비스키와 승인 없이 에너지·건축물대장 등 모든 자료가 확보되지는 않는다. 기존 에너지키는 미등록 오류가 확인됐으며 결측을 임의 관측으로 채우지 않는다. DB·지도·면적 시뮬레이션·보고서·로컬 AI와 실제 기상 수집 작업을 공개 주소에서 검사한다.

## 검증

Node와 Playwright가 있는 환경에서:

```powershell
node scripts/verify-gateway.cjs
node scripts/e2e-public.cjs
```

첫 명령은 미인증·오인증 거부, 정상 인증의 DB 연결, 교차 출처 쓰기 거부를 검사한다. 두 번째는 실제 공개 주소로 지도·시나리오·보고서·AI·기상 작업 큐·모바일을 검사하고 `data/deployment/checks.json`에 저장한다. 계정 정보는 출력하지 않는다.

## 무료 서비스 제한과 향후 전환

Quick Tunnel은 개발·시연용이며 가용성 보장이 없고 동시 진행 요청 200개, SSE 미지원 제한이 있다. 현재 앱은 일반 HTTP와 폴링을 사용한다. 고정 주소가 필요하면 Cloudflare 계정·도메인의 관리형 터널로 전환한다. PC 없이 상시 운영하려면 서버 계정과 영속 볼륨을 갖춘 환경으로 이전해야 한다.

공식 근거(2026-09-14 확인):

- [Cloudflare Quick Tunnel](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/)
- [GitHub Pages](https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages)
- [Render 무료 요금제 제한](https://render.com/docs/free)
- [Nginx 비밀번호 인증](https://nginx.org/en/docs/http/ngx_http_auth_basic_module.html)
