#!/usr/bin/env python3
"""在临时目录运行 README 演示；不修改真实设计项目。"""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parents[1] / "scripts"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765, help="本地演示端口；0 为自动分配")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="taste-readme-demo-") as project:
        root = Path(project) / ".taste-design"
        subprocess.run([sys.executable, str(SCRIPTS / "gate.py"), "--root", str(root), "init"],
                       cwd=project, check=True, capture_output=True)
        # 仅为展示决策界面设置临时阶段，不代表真实项目已经完成这些闸门。
        state_path = root / "record/state.json"
        state = json.loads(state_path.read_text())
        state.update(stage=3, passed=[0, 1, 2])
        state_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        question = json.loads((HERE / "question.json").read_text())
        decision = root / "record/decisions" / question["id"]
        decision.mkdir(parents=True)
        shutil.copyfile(HERE / "question.json", decision / "question.json")
        samples = root / "work/demo"
        samples.mkdir(parents=True)
        shutil.copyfile(HERE / "directions.html", samples / "directions.html")
        print("README 演示：数据与样张均为虚构示例，关闭后删除临时记录。", flush=True)
        server = subprocess.Popen([sys.executable, "-u", str(SCRIPTS / "decide_server.py"),
                                   "--root", str(root), "serve", "--host", "127.0.0.1", "--port", str(args.port)])
        try:
            server.wait()
        except KeyboardInterrupt:
            pass
        finally:
            if server.poll() is None:
                server.terminate()
            server.wait()


if __name__ == "__main__":
    main()
