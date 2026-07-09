import hashlib
from pathlib import Path


CURRENT = Path(
    "/Users/niko/Library/Application Support/net.metaquotes.wine.metatrader5/drive_c/users/user/AppData/Roaming/MetaQuotes/Terminal/Common/Files/phantom_signals.jsonl"
)
CURRENT_REPO = Path("/Users/niko/Documents/projects/niko-ai/signals/phantom_signals.jsonl")
HIST = Path("/Users/niko/Documents/projects/niko-ai/saved_runs/2026-06-16_6y/cash/phantom_signals_cash.jsonl")


def sha256(path: Path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def first_byte_difference(a: bytes, b: bytes):
    for index, (left, right) in enumerate(zip(a, b), start=1):
        if left != right:
            return index, left, right
    if len(a) != len(b):
        return min(len(a), len(b)) + 1, None if len(a) < len(b) else a[len(b)], None if len(b) < len(a) else b[len(a)]
    return None


def main():
    current_bytes = CURRENT.read_bytes()
    repo_bytes = CURRENT_REPO.read_bytes()
    hist_bytes = HIST.read_bytes()

    print("CURRENT_COMMON")
    print(f"path={CURRENT}")
    print(f"sha256={sha256(CURRENT)}")
    print(f"bytes={len(current_bytes)}")
    print(f"lines={len(CURRENT.read_text(encoding='utf-8', errors='ignore').splitlines())}")
    print()

    print("CURRENT_REPO")
    print(f"path={CURRENT_REPO}")
    print(f"sha256={sha256(CURRENT_REPO)}")
    print(f"identical_to_common={current_bytes == repo_bytes}")
    print()

    print("HIST_CASH")
    print(f"path={HIST}")
    print(f"sha256={sha256(HIST)}")
    print(f"bytes={len(hist_bytes)}")
    print(f"lines={len(HIST.read_text(encoding='utf-8', errors='ignore').splitlines())}")
    print()

    diff = first_byte_difference(current_bytes, hist_bytes)
    print("CUR_VS_HIST")
    print(f"identical={current_bytes == hist_bytes}")
    if diff is None:
        print("first_byte_diff=None")
    else:
        index, left, right = diff
        print(f"first_byte_diff=index:{index};current:{left};hist:{right}")

    current_lines = CURRENT.read_text(encoding="utf-8", errors="ignore").splitlines()
    hist_lines = HIST.read_text(encoding="utf-8", errors="ignore").splitlines()
    for line_no, (left, right) in enumerate(zip(current_lines, hist_lines), start=1):
        if left != right:
            print(f"first_diff_line={line_no}")
            print(f"current_line={left}")
            print(f"hist_line={right}")
            break
    else:
        if len(current_lines) != len(hist_lines):
            print(f"shared_line_prefix={min(len(current_lines), len(hist_lines))}")
            print(f"current_line_count={len(current_lines)}")
            print(f"hist_line_count={len(hist_lines)}")
        else:
            print("first_diff_line=None")


if __name__ == "__main__":
    main()