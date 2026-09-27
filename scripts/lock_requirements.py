"""把目前環境裡「實測過的版本」寫成打包用的鎖定檔 requirements-lock.txt。

requirements*.txt 只寫版本範圍（下限 + 上限），重新安裝時仍可能抓到範圍內較新
的版本；打包要可重現，所以 build.bat 改裝這份鎖定檔。這裡不用 `pip freeze`：
那會把環境裡跟 PinDrift 無關的套件全部凍結進去。做法是從 requirements 檔列出
的套件出發，沿著已安裝套件的 metadata 走遍遞移相依（依目前平台評估環境標記），
只收錄真的會被裝進來的套件。

用法（在測試過、打包過的環境執行）：
    python scripts/lock_requirements.py
"""

import pathlib
import sys
from importlib import metadata

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = pathlib.Path(__file__).resolve().parent.parent
SOURCE_FILES = ("requirements.txt", "requirements-build.txt")
LOCK_FILE = ROOT / "requirements-lock.txt"

HEADER = """\
# 打包用的固定版本（build.bat 安裝這份）。由 scripts/lock_requirements.py 依目前環境
# 已安裝、實測過的版本產生，含所有遞移相依；不要手改，升級套件後重新產生。
# 來源：{sources}
# 產生環境：Python {python}（{platform}）；環境標記依這個平台評估，只適用 Windows 打包。
"""


def read_requirements(path):
    requirements = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line and not line.startswith("-"):
            requirements.append(Requirement(line))
    return requirements


def resolve(requirements):
    """回傳 {正規化名稱: (顯示名稱, 版本)}；已安裝版本不符範圍時丟 SystemExit。"""
    pinned = {}
    expanded = set()  # 已展開過相依的 (套件, extra)；同一套件可能被以不同 extras 要求
    pending = [(req, "") for req in requirements]
    while pending:
        req, parent_extra = pending.pop()
        if req.marker and not req.marker.evaluate({"extra": parent_extra}):
            continue
        key = canonicalize_name(req.name)
        try:
            dist = metadata.distribution(req.name)
        except metadata.PackageNotFoundError:
            raise SystemExit(f"{req.name} 沒有安裝，請先 pip install -r 對應的 requirements 檔")
        version = dist.version
        if req.specifier and not req.specifier.contains(version, prereleases=True):
            raise SystemExit(f"{req.name} 已安裝 {version}，不符合 {req.specifier}")
        pinned[key] = (dist.metadata["Name"], version)
        for extra in {""} | set(req.extras):
            if (key, extra) in expanded:
                continue
            expanded.add((key, extra))
            pending.extend((Requirement(child), extra) for child in dist.requires or [])
    return pinned


def main():
    requirements = []
    for name in SOURCE_FILES:
        requirements.extend(read_requirements(ROOT / name))
    pinned = resolve(requirements)
    lines = [f"{name}=={version}" for _key, (name, version) in sorted(pinned.items())]
    header = HEADER.format(
        sources="、".join(SOURCE_FILES),
        python=".".join(map(str, sys.version_info[:3])),
        platform=sys.platform,
    )
    LOCK_FILE.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")
    print(f"已寫入 {LOCK_FILE.name}：{len(lines)} 個套件")


if __name__ == "__main__":
    main()
