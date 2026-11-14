# 두 사람이 함께 쓰는 Git 작업 방식

작성 2026-11-14. 이 저장소에 두 사람이 함께 고칠 때, 서로의 반영이 덮이거나 되돌려지지 않게 하는 규칙입니다. 확인하고 의견이 있으면 이 문서를 고치는 PR이나 댓글로 알려 주세요.

## 1. 한 줄 요약

`main`에는 직접 올리지 않습니다. 일 하나마다 브랜치를 만들고 PR(Pull Request)을 올린 뒤, **다른 사람이 확인하고 승인하면** 병합합니다. 단, `yangbun-GIT`이 올린 PR은 승인을 기다리지 않고 자동으로 병합됩니다(8절).

## 2. 왜 이렇게 하나

두 사람이 같은 `main`에 바로 올리면 다음 일이 생깁니다.
- 충돌을 풀면서 한쪽 내용을 통째로 고름
- 오래된 사본으로 덮어씀(강제 푸시)
- 그러다 다른 사람의 반영이 사라짐

브랜치와 PR로 나누면 다음이 지켜집니다.
- 병합 전에 바뀐 내용을 서로 볼 수 있음
- 충돌은 올리는 사람이 자기 브랜치에서 먼저 풂
- 문제가 생겨도 PR 하나만 되돌리면 됨

## 3. 저장소 설정 (관리자만 할 수 있음)

**Settings → Branches → Add branch ruleset**(또는 Branch protection rule)에서 대상 `main`에 다음을 켭니다.

| 설정 | 하는 일 |
|---|---|
| Require a pull request before merging | `main`에는 PR로만 반영 |
| Required approvals: 1 | 다른 한 사람이 승인해야 병합 |
| Require branches to be up to date before merging | 최신 `main`을 반영한 브랜치만 병합. 오래된 브랜치가 새 변경을 덮는 것을 막음 |
| Block force pushes | 강제 푸시 금지 |
| Restrict deletions | `main` 삭제 금지 |
| Bypass list 비우기 / Do not allow bypassing | **관리자도** 위 규칙을 지킴. 이것을 빼면 관리자는 계속 `main`에 바로 올릴 수 있음 |

`gh-pages`는 배포용이라 지금처럼 둡니다.

2026-11-14 현재 위 설정은 켜져 있지 않습니다(`main` 보호 없음, 규칙 없음). `Required approvals: 1`을 켜면 8절의 자동 병합은 멈춥니다(자동 병합은 승인을 대신하지 않습니다).

## 4. 작업 순서

```powershell
# 1) 최신 main에서 시작
git switch main
git pull --ff-only

# 2) 일 하나에 브랜치 하나
git switch -c fix/<무엇을-고치나>

# 3) 작업하고 커밋 (작게, 자주)
git add <파일>
git commit -m "무엇을 왜 바꿨는지"

# 4) 올리기 전에 최신 main을 내 브랜치로 가져와 충돌을 내 쪽에서 먼저 풂
git fetch origin
git merge origin/main        # 충돌이 나면 양쪽 내용을 다 보고 합침

# 5) 브랜치를 올리고 GitHub에서 PR 열기
git push -u origin fix/<무엇을-고치나>
```

1. PR 설명에는 무엇을 왜 바꿨는지, 시험을 돌렸는지, 숫자가 바뀌는지를 적습니다.
2. 다른 사람이 확인하고 승인합니다. 고칠 점은 PR 댓글로 남깁니다.
3. 병합은 **Squash and merge**로 합니다. PR 하나가 `main`의 커밋 하나가 되어 되돌리기 쉽습니다.
4. 병합 뒤 그 브랜치는 지웁니다(GitHub의 Delete branch 버튼).

## 5. 브랜치 이름

| 앞말 | 쓰임 | 예 |
|---|---|---|
| `fix/` | 오류 수정 | `fix/ladder-offsite-pv` |
| `feature/` | 새 기능·큰 작업 묶음 | `feature/interview-feedback` |
| `docs/` | 문서만 | `docs/manual-terms` |

## 6. 하지 않는 것

- `main`에 직접 커밋·푸시
- `git push --force`(꼭 필요하면 자기 브랜치에서만 `--force-with-lease`로, 함께 쓰는 브랜치는 금지)
- 충돌을 "내 것 모두"나 "상대 것 모두"로 한 번에 풀기
- 다른 사람의 브랜치에 말없이 커밋
- `data/`, `.env`, 키, DB 덤프 올리기(기존 규칙 그대로. `AGENTS.md`)

## 7. 충돌을 줄이는 약속

- 시작할 때 누가 어떤 파일을 맡을지 짧게 나눕니다. 이 저장소에서 둘이 같이 고치기 쉬운 곳은 화면(`frontend/src/pages`), `backend/cases/simulation_cases.json`, `docs/USER_MANUAL.md`입니다.
- PR은 작게 만들고, 오래 열어 두지 않습니다. 하루 이틀 안에 병합하는 것이 목표입니다.
- 계수·상수를 바꾸는 PR은 기준 문서(`docs/DATA_STANDARD.md`)와 코드를 같은 PR에서 바꿉니다(기존 규칙).

## 8. 자동 병합 (yangbun-GIT이 올린 PR)

저장소 관리자(shy0401)의 결정으로, 2026-11-14부터 `yangbun-GIT`이 이 저장소의 브랜치에서 `main`으로 여는 PR은 **승인을 기다리지 않고 자동으로 병합**됩니다. `.github/workflows/auto-merge-collaborator.yml`이 PR이 열리거나 커밋이 더해질 때마다 돌아, 보통 1분 안에 Squash and merge 하고 그 브랜치를 지운 뒤 PR에 댓글을 남깁니다. 그래서 1절·4절의 "다른 사람이 승인" 단계는 `yangbun-GIT`의 PR에는 적용되지 않습니다.

자동으로 병합하지 않고 남겨 두는 경우(이유를 PR 댓글로 남깁니다):

| 경우 | 다음에 할 일 |
|---|---|
| `main`과 충돌이 있음 | 4절 4)대로 `git merge origin/main`으로 풀고 같은 브랜치에 푸시하면 다시 시도 |
| 초안(Draft) PR | Ready for review로 바꾸면 병합. 병합을 미루고 싶은 변경은 초안으로 엽니다 |
| `.github/` 아래를 바꿈(이 규칙 자체 포함) | 관리자가 직접 확인하고 병합 |
| 올리지 않기로 한 경로가 들어 있음(`.env`, `.secrets/`, `data/raw`·`data/backups`·`data/cache` 등, 키·덤프 파일) | 그 파일을 PR에서 빼고 다시 푸시 |
| 한 PR이 파일을 20개 넘게 지우거나 3,000줄 넘게 지움 | 관리자가 내용을 보고 직접 병합(잘못 푼 충돌로 다른 사람의 반영이 사라지는 것을 막기 위함) |
| 다른 저장소(fork)에서 온 PR | 이 저장소의 브랜치로 올림 |

알아 둘 것:
- GitHub에서는 시험이 돌지 않습니다. 병합 전에 확인해 주는 단계가 없으므로, 올리는 사람이 로컬에서 시험을 돌리고 결과를 PR 설명에 적습니다.
- 병합 전에 꼭 같이 봐야 하는 변경(계수·상수, 발표 숫자가 바뀌는 변경)은 초안으로 열고 댓글로 알려 주세요.
- 대상 사용자와 기준 값은 워크플로 파일 위쪽의 `ALLOWED_AUTHORS`, `MAX_REMOVED_FILES`, `MAX_DELETED_LINES`에 있습니다.
- 멈추려면 GitHub의 Actions → "협업자 PR 자동 병합" → Disable workflow.

## 9. 지금 진행 중인 브랜치

| 브랜치 | 내용 | 상태 |
|---|---|---|
| `feature/interview-feedback` | 연결 확인 + 이 문서 | PR #1로 병합, 브랜치 삭제 |
| `fix/feedback-audit` | 점검 결과 문서(`FEEDBACK_AUDIT_2026-11-13.md`)와 감축 사다리의 남는 양·상쇄 표시 수정 | PR 검토 대기 |
