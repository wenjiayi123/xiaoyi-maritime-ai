import argparse

from app.xiaoyi import XiaoyiAI


def main() -> None:
    parser = argparse.ArgumentParser(description="小懿港航迷你问答")
    parser.add_argument("question", help="要询问小懿的问题")
    parser.add_argument("--mode", choices=["expert", "ops", "sop", "brief"], default="expert")
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()

    engine = XiaoyiAI()
    result = engine.ask(args.question, mode=args.mode, top_k=args.top_k)
    print(result.answer)
    print("\n证据来源：")
    for item in result.evidence:
        print(f"- {item.title} [{item.source}] score={item.score}")


if __name__ == "__main__":
    main()
