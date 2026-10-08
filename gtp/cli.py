"""Command line: run the server and manage customers.

    gtp serve [--host 0.0.0.0] [--port 8000]
    gtp customer create --name "Asha" --email asha@example.com --plan pro
    gtp customer list
    gtp customer set-plan 3 algo
    gtp customer disable 3
    gtp customer rotate-key 3
    gtp check            # test your GDF keys against each API
"""

from __future__ import annotations

import argparse
import json
import sys

from .config import Settings


def _store(s: Settings):
    from .platform.store import Store
    return Store(s.db_path)


def cmd_serve(args: argparse.Namespace) -> None:
    import uvicorn

    from .api.app import DEMO_KEYS, create_app

    s = Settings.from_env()
    app = create_app(s)
    print(f"Global Trader Platform running in {'DEMO' if s.demo else 'LIVE'} mode on http://{args.host}:{args.port}")
    if s.demo:
        print("Demo API keys: " + ", ".join(f"{p}={k}" for p, k in DEMO_KEYS.items()))
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


def cmd_customer(args: argparse.Namespace) -> None:
    store = _store(Settings.from_env())
    if args.action == "create":
        c, key = store.create_customer(args.name, args.email, args.plan)
        print(json.dumps({"customer": c.to_dict(), "api_key": key}, indent=2))
        print("Give the customer this key now. Only its hash is stored.", file=sys.stderr)
    elif args.action == "list":
        for c in store.list_customers():
            print(f"{c.id:>4}  {c.plan.id:<5} {'active' if c.active else 'disabled':<8} {c.key_prefix}…  {c.name} <{c.email}>")
    elif args.action == "set-plan":
        print(store.update_customer(args.id, plan=args.plan).to_dict())
    elif args.action == "disable":
        print(store.update_customer(args.id, active=False).to_dict())
    elif args.action == "enable":
        print(store.update_customer(args.id, active=True).to_dict())
    elif args.action == "rotate-key":
        print(store.rotate_key(args.id))
    elif args.action == "usage":
        for row in store.usage(args.id):
            print(f"{row['day']}  {row['count']:>7}  {row['endpoint']}")


def cmd_check(_: argparse.Namespace) -> None:
    """Make one cheap call to each configured GDF API and report the result."""
    from .gdf import FundamentalsClient, MutualFundClient, NewsClient, PriceClient

    s = Settings.from_env()
    checks = [
        ("price", lambda: PriceClient(s.price_base_url, s.price_access_key).call("GetServerInfo")),
        ("fundamentals", lambda: FundamentalsClient(s.fundamental_base_url, s.fundamental_access_key).call("GetLimitation")),
        ("mutual funds", lambda: MutualFundClient(s.mf_base_url, s.mf_access_key).call("GetSchemeTypeMaster")),
        ("news", lambda: NewsClient(s.news_base_url, s.news_api_key).general_news(limit=1)),
    ]
    ok = True
    for name, fn in checks:
        try:
            res = fn()
            print(f"[ OK ] {name}: {str(res)[:120]}")
        except Exception as e:  # noqa: BLE001
            ok = False
            print(f"[FAIL] {name}: {e}")
    sys.exit(0 if ok else 1)


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="gtp", description="Global Trader Platform")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("serve", help="Run the API server and dashboard")
    sp.add_argument("--host", default="127.0.0.1")
    sp.add_argument("--port", type=int, default=8000)
    sp.set_defaults(fn=cmd_serve)

    cp = sub.add_parser("customer", help="Manage customers and API keys")
    csub = cp.add_subparsers(dest="action", required=True)
    c = csub.add_parser("create")
    c.add_argument("--name", required=True)
    c.add_argument("--email", required=True)
    c.add_argument("--plan", default="free")
    csub.add_parser("list")
    c = csub.add_parser("set-plan")
    c.add_argument("id", type=int)
    c.add_argument("plan")
    for action in ("disable", "enable", "rotate-key", "usage"):
        csub.add_parser(action).add_argument("id", type=int)
    cp.set_defaults(fn=cmd_customer)

    sub.add_parser("check", help="Test your Global Datafeeds keys").set_defaults(fn=cmd_check)

    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
