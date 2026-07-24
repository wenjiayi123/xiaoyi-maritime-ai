from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.security import issue_access_token  # noqa: E402
from app.settings import Settings  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="签发小懿AI生产Bearer访问令牌")
    parser.add_argument("--actor", required=True, help="稳定的操作员或服务账号标识")
    parser.add_argument("--role", choices=["viewer", "analyst", "operator", "admin"], required=True)
    parser.add_argument("--minutes", type=int, default=60, help="有效分钟数")
    args = parser.parse_args()
    configuration = Settings.from_env()
    print(issue_access_token(
        actor_id=args.actor,
        role=args.role,
        settings=configuration,
        expires_minutes=args.minutes,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
