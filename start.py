"""One-command setup and launch on Windows, macOS and Linux (Python 3.11+)."""
import hashlib
import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def run(args, cwd=ROOT):
    subprocess.run([str(arg) for arg in args], cwd=cwd, check=True)


def digest(paths):
    result = hashlib.sha256()
    for path in sorted(paths):
        result.update(str(path.relative_to(ROOT)).encode())
        result.update(path.read_bytes())
    return result.hexdigest()


def current(stamp, expected):
    return stamp.exists() and stamp.read_text().strip() == expected


def main():
    if sys.version_info < (3, 11):
        raise SystemExit("需要 Python 3.11 或更新版本。")
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    node = shutil.which("node")
    if not npm or not node:
        raise SystemExit("请先安装 Node.js 22 LTS（包含 npm），然后重新运行。")
    version = subprocess.check_output([node, "--version"], text=True).strip()
    if int(version.lstrip("v").split(".")[0]) < 22:
        raise SystemExit(f"当前 Node.js {version}，请安装 Node.js 22 或更新版本。")
    env_dir = ROOT / ".venv"
    python = env_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not python.exists():
        print("首次启动：创建独立 Python 环境…", flush=True)
        venv.create(env_dir, with_pip=True)
    requirements = ROOT / "requirements.txt"
    signature = digest([requirements])
    stamp = env_dir / ".requirements-hash"
    if not current(stamp, signature):
        print("安装后端依赖…", flush=True)
        run([python, "-m", "pip", "install", "-r", requirements])
        stamp.write_text(signature)
    frontend = ROOT / "frontend"
    lock = frontend / "package-lock.json"
    signature = digest([lock, frontend / "package.json"])
    stamp = frontend / "node_modules/.dependencies-hash"
    if not current(stamp, signature):
        print("安装前端依赖…", flush=True)
        run([npm, "ci"], frontend)
        stamp.write_text(signature)
    inputs = [p for p in (frontend / "src").rglob("*") if p.is_file()]
    inputs += [frontend / name for name in ("package.json", "package-lock.json", "index.html", "tsconfig.json", "vite.config.ts")]
    signature = digest(inputs)
    stamp = frontend / "dist/.build-hash"
    if not current(stamp, signature) or not (frontend / "dist/index.html").exists():
        print("构建界面…", flush=True)
        run([npm, "run", "build"], frontend)
        stamp.write_text(signature)
    run([python, ROOT / "run.py"])


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n学习助手已关闭。")
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"步骤执行失败（退出码 {exc.returncode}）。请检查上方错误后重新运行；已有资料不会被删除。")
