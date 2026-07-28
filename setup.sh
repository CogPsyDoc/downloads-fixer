#!/bin/bash
# =============================================================================
# downloads-fixer 설치 스크립트 (macOS)
#
#   ~/Downloads 에서
#     1) URL-인코딩된 깨진 한글 파일명을 자동 복원
#     2) 새로 받은 .hwp/.hwpx 를 자동으로 .pdf 로 변환
#
# 사용법:  bash setup.sh
#          (같은 폴더에 downloads_fixer.py 가 있어야 함)
#
# 이 스크립트는 몇 번을 다시 돌려도 안전합니다(idempotent).
# =============================================================================
set -euo pipefail

SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
# 설치 위치와 자동 실행 식별자는 환경변수로 각자 바꿀 수 있습니다.
#   DF_DEST=~/tools/df  DF_LABEL=com.example.df  bash setup.sh
DEST_DIR="${DF_DEST:-$HOME/.local/downloads-fixer}"
LABEL="${DF_LABEL:-com.reconlabs.downloads-fixer}"
PLIST_DST="$HOME/Library/LaunchAgents/$LABEL.plist"
H2O_VER="v0.7.13"
H2O_URL="https://github.com/ebandal/H2Orestart/releases/download/$H2O_VER/H2Orestart.oxt"
SOFFICE="/Applications/LibreOffice.app/Contents/MacOS/soffice"
UNOPKG="/Applications/LibreOffice.app/Contents/MacOS/unopkg"

say() { printf "\n\033[1;34m▶ %s\033[0m\n" "$*"; }
ok()  { printf "  \033[32m✓ %s\033[0m\n" "$*"; }
die() { printf "\n\033[31m✗ %s\033[0m\n" "$*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# 0) 사전 점검
# ---------------------------------------------------------------------------
[ "$(uname)" = "Darwin" ] || die "이 도구는 macOS 전용입니다."
[ -f "$SRC_DIR/downloads_fixer.py" ] || die "downloads_fixer.py 를 같은 폴더에서 찾을 수 없습니다."

if ! command -v brew >/dev/null 2>&1; then
  die "Homebrew 가 필요합니다. https://brew.sh 에서 먼저 설치한 뒤 다시 실행하세요."
fi
BREW_PREFIX="$(brew --prefix)"
PYTHON="$BREW_PREFIX/bin/python3"

# ---------------------------------------------------------------------------
# 1) LibreOffice
# ---------------------------------------------------------------------------
say "1/7  LibreOffice 확인·설치"
if [ -x "$SOFFICE" ]; then
  ok "이미 설치됨"
else
  brew install --cask libreoffice
  ok "설치 완료"
fi

# ---------------------------------------------------------------------------
# 2) Java (H2Orestart HWP 필터에 필요)
# ---------------------------------------------------------------------------
say "2/7  Java(OpenJDK) 확인·설치"
if [ ! -d "$BREW_PREFIX/opt/openjdk/libexec/openjdk.jdk" ]; then
  brew install openjdk
fi
# LibreOffice/Java 프레임워크가 인식하도록 사용자 JVM 디렉터리에 링크
mkdir -p "$HOME/Library/Java/JavaVirtualMachines"
ln -sfn "$BREW_PREFIX/opt/openjdk/libexec/openjdk.jdk" \
        "$HOME/Library/Java/JavaVirtualMachines/openjdk.jdk"
JAVA_HOME="$(/usr/libexec/java_home 2>/dev/null || true)"
[ -n "$JAVA_HOME" ] || die "Java 설치 후에도 인식되지 않습니다. 새 터미널에서 다시 시도하세요."
export JAVA_HOME UNO_JAVA_JFW_ENV_JAVA_HOME=1
ok "JAVA_HOME=$JAVA_HOME"

# ---------------------------------------------------------------------------
# 3) H2Orestart 확장 (LibreOffice 에 HWP/HWPX 읽기 필터 추가)
# ---------------------------------------------------------------------------
say "3/7  H2Orestart 확장 등록"
# 갓 brew 로 설치된 LibreOffice.app 은 격리(quarantine) 속성이 붙어 있어,
# GUI 로 한 번도 열지 않은 상태에서 unopkg 가 내부적으로 soffice.bin 을 띄우면
# macOS Gatekeeper 가 그 프로세스를 SIGKILL(Killed: 9) 한다. 격리 속성을 제거해
# 통과시킨다. (본인 소유 앱이라 sudo 불필요)
xattr -dr com.apple.quarantine /Applications/LibreOffice.app 2>/dev/null || true

# unopkg 는 실행 중인 LibreOffice 와 충돌한다. 인스턴스를 정리하고 남은
# 잠금 파일(.lock)을 지운 뒤에 다뤄야 한다 — 이 잠금이 남으면 이후 모든
# unopkg 호출이 "already running" 으로 실패한다.
clean_office_lock() {
  pkill -9 -f soffice 2>/dev/null || true
  sleep 1
  rm -f "$HOME/Library/Application Support/LibreOffice/4/.lock"
}
# 첫 실행: 헤드리스로 한 번 초기화해 사용자 프로필을 만들어 두면, 이어지는
# unopkg 의 soffice 파이프 연결이 안정적으로 동작한다.
clean_office_lock
"$SOFFICE" --headless --terminate_after_init >/dev/null 2>&1 || true
clean_office_lock
# unopkg 출력을 파이프로 바로 grep 하면 grep -q 가 파이프를 먼저 닫아
# unopkg 가 SIGPIPE(exit 141)로 죽고, pipefail 때문에 "미등록"으로 오판한다.
# → 출력을 변수에 먼저 담은 뒤 grep 한다.
is_h2o_registered() {
  local out
  out="$("$UNOPKG" list 2>/dev/null || true)"
  printf '%s' "$out" | grep -q "H2Orestart"
}
if is_h2o_registered; then
  ok "이미 등록됨"
else
  TMP_OXT="$(mktemp -d)/H2Orestart.oxt"
  curl -fsSL -o "$TMP_OXT" "$H2O_URL" || die "H2Orestart 다운로드 실패"
  clean_office_lock
  "$UNOPKG" add --suppress-license "$TMP_OXT" 2>/dev/null || true
  clean_office_lock
  if is_h2o_registered; then
    ok "등록 완료"
  else
    die "H2Orestart 등록 실패. LibreOffice 를 Finder 에서 한 번 실행(우클릭→열기)해
    Gatekeeper 를 통과시킨 뒤 다시 'bash setup.sh' 를 실행하세요.
    (그래도 안 되면 'xattr -dr com.apple.quarantine /Applications/LibreOffice.app' 후 재시도)"
  fi
fi

# ---------------------------------------------------------------------------
# 4) 스크립트 설치
# ---------------------------------------------------------------------------
say "4/7  스크립트 설치 → $DEST_DIR"
mkdir -p "$DEST_DIR"
cp "$SRC_DIR/downloads_fixer.py" "$DEST_DIR/"
[ -f "$SRC_DIR/uninstall.sh" ] && cp "$SRC_DIR/uninstall.sh" "$DEST_DIR/"
chmod +x "$DEST_DIR/downloads_fixer.py"
ok "복사 완료"

# ---------------------------------------------------------------------------
# 5) 기존 깨진 파일명 1회 복원 (+ 기존 HWP 는 변환 제외로 기록)
# ---------------------------------------------------------------------------
say "5/7  기존 Downloads 파일명 복원"
"$PYTHON" "$DEST_DIR/downloads_fixer.py" --backfill
ok "완료"

# ---------------------------------------------------------------------------
# 6) launchd 에이전트 생성 (현재 계정에 맞춰 경로 자동 생성)
# ---------------------------------------------------------------------------
say "6/7  자동 실행 에이전트 등록"
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST_DST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON</string>
        <string>$DEST_DIR/downloads_fixer.py</string>
    </array>
    <key>WatchPaths</key>
    <array>
        <string>$HOME/Downloads</string>
    </array>
    <key>StartInterval</key>
    <integer>1800</integer>
    <key>ThrottleInterval</key>
    <integer>10</integer>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$HOME/Library/Logs/downloads-fixer.launchd.log</string>
    <key>StandardErrorPath</key>
    <string>$HOME/Library/Logs/downloads-fixer.launchd.log</string>
</dict>
</plist>
PLIST
launchctl unload "$PLIST_DST" 2>/dev/null || true
launchctl load "$PLIST_DST"
ok "등록 완료"

# ---------------------------------------------------------------------------
# 7) macOS 개인정보 보호(TCC) 안내
# ---------------------------------------------------------------------------
say "7/7  완료"
cat <<EOF

  설치가 끝났습니다. ~/Downloads 에 파일을 받으면 자동으로:
    · 깨진 한글 이름이 복원되고
    · .hwp/.hwpx 는 같은 이름의 .pdf 가 함께 생깁니다.

  로그:   ~/Library/Logs/downloads-fixer.log
  제거:   bash $DEST_DIR/uninstall.sh

  ⚠️  macOS 가 "다운로드 폴더 접근" 권한을 물어보는 팝업을 띄우면
      반드시 [허용] 을 눌러 주세요. (안 뜨면 이미 허용된 것)
      혹시 자동 변환이 안 되면 시스템 설정 → 개인정보 보호 및 보안 →
      파일 및 폴더 에서 "$PYTHON" 항목의 다운로드 폴더 접근을 켜세요.

EOF
