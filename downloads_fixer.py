#!/usr/bin/env python3
"""Downloads 자동 정리기 (macOS).

~/Downloads 를 감시(launchd WatchPaths)하면서:
  1. URL-인코딩(%XX)된 한글 파일명(예: %EC%A0%9C...hwp)을 사람이 읽을 수 있게 복원
  2. 새로 받은 .hwp/.hwpx 옆에 같은 이름의 .pdf 를 자동 생성 (LibreOffice + H2Orestart)

안전 원칙:
  - 기존 파일을 덮어쓰는 rename 은 절대 하지 않는다 (충돌 시 " (1)" 부여)
  - 다운로드가 끝나지 않은 파일(부분 확장자, 크기 변동 중)은 건너뛴다
  - 변환 실패는 로그에 남기고 다음 파일로 넘어간다

이 스크립트는 계정에 독립적이다(하드코딩된 사용자 경로 없음). 어떤 Mac 계정에서든
그대로 동작한다. 설치는 setup.sh 가 담당한다.

사용:
  downloads_fixer.py            # 1회 스캔 (launchd 가 호출)
  downloads_fixer.py --backfill # 파일명 복원만 전체 실행 (설치 시 1회; PDF 변환은 안 함)
  downloads_fixer.py --dry-run  # 실제 변경 없이 할 일만 출력
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote

DOWNLOADS = Path.home() / "Downloads"
LOG_PATH = Path.home() / "Library/Logs/downloads-fixer.log"
# 상태 파일(잠금·변환 제외 목록)은 이 스크립트가 설치된 폴더 옆에 둔다.
# 덕분에 설치 위치를 바꿔도(DF_DEST) 경로가 어긋나지 않는다.
STATE_DIR = Path(__file__).resolve().parent
LOCK_PATH = STATE_DIR / ".lock"
# 설치(--backfill) 시점에 이미 있던 HWP 목록 — 이 파일들은 PDF 변환 대상에서 제외
IGNORE_LIST = STATE_DIR / "preexisting_hwp.txt"
# 이미 한 번 변환한 원본 기록 — 사용자가 PDF 를 지워도 다시 만들지 않기 위함
# (원본이 새로 바뀌면 크기/수정시각이 달라져 다시 변환된다)
CONVERTED_LEDGER = STATE_DIR / "converted.json"

SOFFICE = "/Applications/LibreOffice.app/Contents/MacOS/soffice"

PERCENT_SEQ = re.compile(r"%[0-9A-Fa-f]{2}")
# 다운로드 중이거나 임시 상태인 이름들
SKIP_SUFFIXES = (".crdownload", ".download", ".part", ".partial", ".tmp")
SKIP_PREFIXES = (".", "~$", "$")
CONVERT_EXTS = {".hwp", ".hwpx"}
SOFFICE_TIMEOUT = 180  # 초


def log(msg: str) -> None:
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    print(line)
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a") as f:
            f.write(line + "\n")
    except OSError:
        pass


def detect_java_home() -> str | None:
    """H2Orestart(Java 컴포넌트)를 쓰려면 JAVA_HOME 이 필요하다. 자동 탐지."""
    try:
        out = subprocess.run(
            ["/usr/libexec/java_home"], capture_output=True, text=True
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except OSError:
        pass
    candidates = [
        Path.home() / "Library/Java/JavaVirtualMachines/openjdk.jdk/Contents/Home",
        Path("/opt/homebrew/opt/openjdk/libexec/openjdk.jdk/Contents/Home"),
        Path("/usr/local/opt/openjdk/libexec/openjdk.jdk/Contents/Home"),
    ]
    for p in candidates:
        if p.exists():
            return str(p)
    return None


def soffice_env() -> dict:
    env = {**os.environ, "UNO_JAVA_JFW_ENV_JAVA_HOME": "1"}
    jh = detect_java_home()
    if jh:
        env["JAVA_HOME"] = jh
    return env


def decode_name(name: str) -> str | None:
    """%XX 시퀀스가 든 파일명을 복원. 바꿀 필요 없으면 None."""
    if not PERCENT_SEQ.search(name):
        return None
    decoded = None
    for enc in ("utf-8", "cp949"):
        try:
            decoded = unquote(name, encoding=enc, errors="strict")
            break
        except UnicodeDecodeError:
            continue
    if decoded is None:
        # 브라우저가 255바이트 제한으로 이름을 중간에 자르면 멀티바이트가
        # 깨진 채 남는다 → 깨진 글자만 U+FFFD 로 치환 후 제거
        decoded = unquote(name, encoding="utf-8", errors="replace")
        decoded = decoded.replace("�", "")
    if decoded == name:
        return None
    decoded = unicodedata.normalize("NFC", decoded)
    # 잘린 인코딩 찌꺼기 정리: "참석희망일%…" -> "참석희망일…"
    decoded = decoded.replace("%…", "…")
    # 파일명에 못 쓰는 문자 방어
    decoded = decoded.replace("/", "／").replace("\0", "")
    decoded = decoded.strip() or None
    return decoded


def unique_path(directory: Path, name: str) -> Path:
    """이름 충돌 시 ' (1)', ' (2)' … 를 붙여 빈 경로를 찾는다."""
    candidate = directory / name
    if not candidate.exists():
        return candidate
    stem, ext = os.path.splitext(name)
    for i in range(1, 100):
        candidate = directory / f"{stem} ({i}){ext}"
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"빈 이름을 찾지 못함: {name}")


def is_settled(path: Path) -> bool:
    """다운로드가 끝나 크기가 안정된 파일인지 확인."""
    try:
        size1 = path.stat().st_size
    except OSError:
        return False
    time.sleep(1.5)
    try:
        return path.stat().st_size == size1
    except OSError:
        return False


def should_skip(path: Path) -> bool:
    name = path.name
    if any(name.startswith(p) for p in SKIP_PREFIXES):
        return True
    if name.lower().endswith(SKIP_SUFFIXES):
        return True
    return False


def fix_names(dry_run: bool = False) -> list[Path]:
    """1단계: 깨진 파일명 복원. 처리 후 존재하는 최종 경로 목록 반환."""
    renamed = []
    for path in sorted(DOWNLOADS.iterdir()):
        if should_skip(path):
            continue
        new_name = decode_name(path.name)
        if new_name is None:
            continue
        if not path.is_dir() and not is_settled(path):
            log(f"SKIP (다운로드 중): {path.name}")
            continue
        target = unique_path(DOWNLOADS, new_name)
        if dry_run:
            log(f"DRY-RUN rename: {path.name!r} -> {target.name!r}")
            continue
        try:
            path.rename(target)
            log(f"RENAME: {path.name!r} -> {target.name!r}")
            renamed.append(target)
        except OSError as e:
            log(f"ERROR rename {path.name!r}: {e}")
    return renamed


def _load_ledger() -> dict:
    """변환 이력 로드. { 파일명: [size, mtime] }."""
    try:
        return json.loads(CONVERTED_LEDGER.read_text())
    except (OSError, ValueError):
        return {}


def _save_ledger(ledger: dict) -> None:
    try:
        CONVERTED_LEDGER.write_text(json.dumps(ledger, ensure_ascii=False))
    except OSError:
        pass


def _identity(path: Path):
    """원본 파일의 지문(크기, 수정시각). PDF 를 지워도 이 값은 안 변한다."""
    st = path.stat()
    return [st.st_size, int(st.st_mtime)]


def convert_hwp_to_pdf(dry_run: bool = False) -> None:
    """2단계: 아직 변환한 적 없는 .hwp/.hwpx 를 LibreOffice 로 변환.

    '이미 변환한 원본'은 사용자가 PDF 를 지워도 다시 만들지 않는다(이력 기록).
    원본 자체가 새로 바뀌면(크기/수정시각 변화) 다시 변환한다.
    """
    if not os.path.exists(SOFFICE):
        log("ERROR: LibreOffice 미설치 — PDF 변환 건너뜀")
        return
    preexisting = set()
    if IGNORE_LIST.exists():
        preexisting = set(IGNORE_LIST.read_text().splitlines())
    ledger = _load_ledger()
    dirty = False
    env = soffice_env()
    if "JAVA_HOME" not in env:
        log("WARN: Java 를 찾지 못함 — HWP 변환이 실패할 수 있음")
    for path in sorted(DOWNLOADS.iterdir()):
        if should_skip(path) or path.is_dir():
            continue
        if path.suffix.lower() not in CONVERT_EXTS:
            continue
        if path.name in preexisting:
            continue
        pdf = path.with_suffix(".pdf")
        try:
            ident = _identity(path)
        except OSError:
            continue
        # 이미 PDF 가 있으면 변환 불필요. 다만 이력에 없거나 달라졌으면 기록해 둔다
        # (이후 PDF 를 지워도 다시 만들지 않도록).
        if pdf.exists():
            if ledger.get(path.name) != ident:
                ledger[path.name] = ident
                dirty = True
            continue
        # PDF 가 없다 — 하지만 같은 원본을 전에 변환한 적이 있으면(지문 동일)
        # 사용자가 일부러 지운 것으로 보고 다시 만들지 않는다.
        if ledger.get(path.name) == ident:
            continue
        if not is_settled(path):
            log(f"SKIP (다운로드 중): {path.name}")
            continue
        # 다운로드가 끝난 뒤 지문을 다시 계산(크기 확정)
        try:
            ident = _identity(path)
        except OSError:
            continue
        if dry_run:
            log(f"DRY-RUN convert: {path.name} -> {pdf.name}")
            continue
        log(f"CONVERT 시작: {path.name}")
        try:
            result = subprocess.run(
                [SOFFICE, "--headless", "--convert-to", "pdf",
                 "--outdir", str(DOWNLOADS), str(path)],
                capture_output=True, text=True, timeout=SOFFICE_TIMEOUT,
                env=env,
            )
            if pdf.exists():
                log(f"CONVERT 완료: {pdf.name}")
                ledger[path.name] = ident
                dirty = True
            else:
                err = (result.stderr or result.stdout or "").strip()[-300:]
                log(f"ERROR convert {path.name}: PDF 미생성 — {err}")
        except subprocess.TimeoutExpired:
            log(f"ERROR convert {path.name}: {SOFFICE_TIMEOUT}초 타임아웃")
        except OSError as e:
            log(f"ERROR convert {path.name}: {e}")
    if dirty:
        _save_ledger(ledger)


def main() -> int:
    dry_run = "--dry-run" in sys.argv
    backfill = "--backfill" in sys.argv

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    lock = LOCK_PATH.open("w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        # 이미 다른 인스턴스가 도는 중 — WatchPaths 중복 트리거는 정상
        return 0

    fix_names(dry_run=dry_run)
    if backfill:
        # 파일명 복원 후 기준으로, 지금 있는 HWP 전부를 변환 제외 목록에 기록
        if not dry_run:
            names = sorted(
                p.name for p in DOWNLOADS.iterdir()
                if p.is_file() and p.suffix.lower() in CONVERT_EXTS
            )
            IGNORE_LIST.write_text("\n".join(names) + "\n")
            log(f"BACKFILL: 기존 HWP {len(names)}개를 변환 제외 목록에 기록")
    else:
        convert_hwp_to_pdf(dry_run=dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
