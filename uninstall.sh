#!/bin/bash
# downloads-fixer 제거 (LibreOffice / Java 같은 공용 도구는 남겨둡니다)
# 설치 때 DF_LABEL / DF_DEST 를 바꿨다면 여기서도 같은 값을 넘겨 주세요.
set -euo pipefail
LABEL="${DF_LABEL:-com.reconlabs.downloads-fixer}"
DEST_DIR="${DF_DEST:-$HOME/.local/downloads-fixer}"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

launchctl unload "$PLIST" 2>/dev/null || true
rm -f "$PLIST"
echo "✓ 자동 실행 에이전트를 제거했습니다."
echo "  스크립트 폴더($DEST_DIR)와 로그는 그대로 둡니다."
echo "  완전히 지우려면:  rm -rf \"$DEST_DIR\""
