# Downloads Fixer (macOS)

웹에서 파일을 받을 때 생기는 두 가지 성가신 일을 백그라운드에서 자동으로 해결하는 macOS 도구입니다.

1. **깨진 한글 파일명 복원** — 브라우저가 한글 파일명을 URL 인코딩된 채로 저장해
   `%EC%A0%9C%EC%95%88%EC%9A%94%EC%B2%AD%EC%84%9C.hwp` 처럼 알아볼 수 없게 받아지는 경우,
   자동으로 `제안요청서.hwp` 로 되돌립니다.
2. **HWP → PDF 자동 변환** — `.hwp` / `.hwpx` 를 받으면 같은 이름의 `.pdf` 를 옆에 자동
   생성합니다. 한글(한컴오피스)이 없는 사람에게 보내거나 빠르게 미리 볼 때 유용합니다.

한 번 설치하면 `~/Downloads` 를 계속 지켜보다가 새 파일이 들어올 때마다 알아서 처리합니다.
사용자가 신경 쓸 일은 없습니다.

---

## 어떻게 동작하나 (구조)

```
새 파일이 ~/Downloads 에 도착
        │
        ▼
launchd (macOS 자동 실행) ──WatchPaths 로 폴더 변화 감지──▶ downloads_fixer.py 실행
        │
        ├─ 1) 파일명에 %XX 인코딩이 있으면  →  UTF-8 → CP949 순으로 디코드해 이름 복원
        │
        └─ 2) .hwp / .hwpx 이고 PDF 가 아직 없으면  →  LibreOffice(headless) 로 PDF 생성
                                                        (H2Orestart 확장 + Java 필요)
```

- **자동 실행:** macOS 의 `launchd` 에이전트가 `~/Downloads` 를 감시합니다(`WatchPaths`).
  놓치는 경우를 대비해 30분마다 한 번 더 훑는 안전망도 있습니다.
- **파일명 복원:** 이름에 `%XX` 시퀀스가 있을 때만 손을 댑니다. UTF-8 로 먼저,
  안 되면 CP949(옛 한글 인코딩)로 디코드합니다. 브라우저가 이름을 255바이트 제한으로
  잘라버린 경우엔 되살릴 수 있는 데까지만 복원합니다.
- **PDF 변환:** LibreOffice 를 창 없이(headless) 돌려 변환합니다. LibreOffice 자체는
  HWP 를 못 읽기 때문에 **H2Orestart** 확장(오픈소스 HWP 필터)을 얹고, 이 확장이
  Java 로 동작하므로 **OpenJDK** 도 함께 씁니다. `setup.sh` 가 이 셋을 전부 자동으로
  설치·연결합니다.

### 안전 설계

- 원본을 덮어쓰지 않습니다. 같은 이름이 이미 있으면 ` (1)`, ` (2)` … 를 붙입니다.
- 다운로드가 끝나지 않은 파일(`.crdownload`, `.part`, 크기 변동 중)은 기다렸다 처리합니다.
- 임시 파일(`~$…`, 숨김 파일)은 건드리지 않습니다.
- 변환 실패는 로그에만 남기고 원본은 그대로 둡니다. **파일을 지우는 동작은 없습니다.**

---

## 설치 (명령어 하나)

> **필요 조건:** macOS + [Homebrew](https://brew.sh)

```bash
git clone https://github.com/CogPsyDoc/downloads-fixer.git
cd downloads-fixer
bash setup.sh
```

`setup.sh` 가 아래를 전부 자동으로 처리합니다.

- LibreOffice 설치 (HWP → PDF 엔진)
- OpenJDK(Java) 설치·연결
- H2Orestart 확장 등록
- **현재 로그인 계정에 맞춰** 자동 실행(`launchd`) 등록
- 지금 Downloads 에 있는 깨진 이름들도 한 번 복원

처음 설치 시 LibreOffice/Java 다운로드로 몇 분 걸릴 수 있습니다. 몇 번을 다시 돌려도
안전합니다(idempotent).

### ⚠️ 설치 직후 딱 하나만 확인

macOS 가 **"다운로드 폴더에 접근하려 합니다"** 팝업을 띄우면 반드시 **[허용]** 을 누르세요.
이걸 눌러야 자동 처리가 동작합니다. (팝업이 안 뜨면 이미 허용된 상태입니다.)

나중에 자동 변환이 안 되면 → 시스템 설정 → 개인정보 보호 및 보안 → **파일 및 폴더**
에서 `python3` 항목의 다운로드 폴더 접근을 켜 주세요.

---

## 설치 위치 / 식별자 바꾸기

경로는 하드코딩돼 있지 않고 **각자 환경에 맞춰 자동 적용**됩니다. 기본값을 바꾸고 싶으면
환경변수로 넘기면 됩니다.

```bash
DF_DEST="$HOME/tools/downloads-fixer" \
DF_LABEL="com.mycompany.downloads-fixer" \
bash setup.sh
```

| 환경변수 | 뜻 | 기본값 |
|---|---|---|
| `DF_DEST`  | 스크립트·상태 파일 설치 폴더 | `~/.local/downloads-fixer` |
| `DF_LABEL` | 자동 실행(launchd) 식별자 | `com.reconlabs.downloads-fixer` |

> 제거할 때 같은 값을 넘겨야 합니다: `DF_LABEL=… DF_DEST=… bash uninstall.sh`

### 무엇이 어디에 설치되나

| 위치 | 내용 | 비고 |
|---|---|---|
| `$DF_DEST/downloads_fixer.py` | 본체 스크립트 | 계정에 독립적 |
| `$DF_DEST/preexisting_hwp.txt` | 변환 제외 목록(설치 시점의 기존 HWP) | |
| `~/Library/LaunchAgents/$DF_LABEL.plist` | 자동 실행 등록 | 계정 경로 자동 생성 |
| `~/Library/Logs/downloads-fixer.log` | 동작 로그 | |
| LibreOffice / OpenJDK / H2Orestart | 공용 도구 | Homebrew·LibreOffice 프로필에 설치 |

---

## 잘 되는지 확인

Downloads 에 아무 `.hwp` 를 하나 넣고 몇 초 뒤 같은 이름의 `.pdf` 가 생기는지 보면 됩니다.

```bash
tail -f ~/Library/Logs/downloads-fixer.log
```

---

## 제거

```bash
bash uninstall.sh
```

자동 실행만 끕니다. LibreOffice·Java 같은 공용 프로그램은 남겨 둡니다.

---

## 자주 묻는 것

**Q. 원래 있던 HWP 도 전부 PDF 로 바뀌나요?**
아니요. 설치 시점에 이미 있던 HWP 는 건드리지 않고, **설치 이후 새로 받는** 파일만
변환합니다. (기존 파일까지 변환하려면 아래 "고급" 참고)

**Q. 변환된 PDF 가 원본과 100% 똑같나요?**
거의 같지만 완벽하진 않습니다. 복잡한 표·서식은 미세하게 다를 수 있어요. 인쇄·제출용
정본이 필요하면 한글(한컴오피스)에서 직접 여는 걸 권장합니다.

**Q. 이미 이름이 잘려서 받아진 파일도 복원되나요?**
브라우저가 이름을 너무 길다고 중간에서 자른 경우, 잘린 글자는 되살릴 수 없어 깨진
마지막 글자만 정리하고 최대한 복원합니다.

**Q. 파일이 덮어써지거나 지워질 걱정은 없나요?**
없습니다. 같은 이름이 있으면 ` (1)` 을 붙이고, 다운로드가 끝나지 않은 파일은 기다렸다
처리합니다. 원본 삭제는 하지 않습니다.

---

## 고급 / 문제 해결

- **동작 상태 보기:** `launchctl list | grep downloads-fixer`
  (두 번째 열이 마지막 종료 코드 — `0` 이면 정상)
- **수동으로 한 번 실행:** `~/.local/downloads-fixer/downloads_fixer.py`
- **미리보기(변경 없이):** `~/.local/downloads-fixer/downloads_fixer.py --dry-run`
- **기존 파일까지 전부 변환:** `~/.local/downloads-fixer/preexisting_hwp.txt` 를 비우거나
  삭제한 뒤 위 수동 실행을 하면 남아 있는 HWP 도 변환합니다.

### 설치가 실패한다면

- **`H2Orestart 등록 실패`** — Java 인식 문제입니다. 새 터미널을 열어 `/usr/libexec/java_home`
  이 경로를 출력하는지 확인한 뒤 `bash setup.sh` 를 다시 실행하세요.
- **PDF 가 안 생김** — 위의 "파일 및 폴더" 권한(TCC)을 확인하세요. 그래도 안 되면
  로그(`~/Library/Logs/downloads-fixer.log`)에서 `ERROR` 줄을 확인하세요.

---

## 구성 파일

| 파일 | 역할 |
|---|---|
| `downloads_fixer.py` | 실제 동작(이름 복원 + PDF 변환). 계정에 독립적. |
| `setup.sh` | 의존성 설치 + 자동 실행 등록까지 한 번에. |
| `uninstall.sh` | 자동 실행 해제. |
| `README.md` | 이 문서. |

---

## 라이선스

MIT License. 자유롭게 쓰고 고치고 배포하세요. 자세한 내용은 [LICENSE](LICENSE) 참고.

HWP 변환은 [H2Orestart](https://github.com/ebandal/H2Orestart)(오픈소스 HWP 필터)와
[LibreOffice](https://www.libreoffice.org/) 를 사용합니다.
