"""Start native HTTP MCP on 127.0.0.1; the connection token stays in its named environment variable."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--host", choices=["127.0.0.1"], default="127.0.0.1")
    parser.add_argument("--port", type=int, default=17665)
    parser.add_argument("--token-env", default="AGENT_GUI_MCP_TOKEN",
                        help="Name of an environment variable containing a separately generated secrets.token_urlsafe(32) connection token")
    parser.add_argument("--model-directory", type=Path)
    parser.add_argument("--recognition-source", choices=["local", "agent_current", "agent_delegate", "external_api"], default="local")
    parser.add_argument("--delegate-profile")
    parser.add_argument("--api-profile", type=Path)
    parser.add_argument("--decision-profile", type=Path)
    parser.add_argument("--allow-local-input", action="store_true",
                        help="Operator explicitly enables existing non-learning direct input, automatic risk interception OFF")
    args = parser.parse_args(argv)
    from app.instant_mcp_http import create_instant_http_app, load_token_digest, validate_bind
    try:
        validate_bind(args.host, args.port)
        load_token_digest(args.token_env)
    except ValueError as error:
        parser.error(str(error))
    if args.recognition_source == "external_api":
        if args.api_profile is None or not args.api_profile.is_absolute() or not args.api_profile.is_file():
            parser.error("external_api requires an existing absolute --api-profile JSON path")
        from app.vision.external_grounding_api import ApiGroundingError, load_api_grounding_profile
        try:
            load_api_grounding_profile(args.api_profile)
        except ApiGroundingError:
            parser.error("--api-profile has an invalid schema")
    elif args.api_profile is not None:
        parser.error("--api-profile is only valid for external_api")
    from app.instant_mcp import InstantSession
    session = InstantSession(ROOT, args.data_dir, args.model_directory,
                             allow_local_input=args.allow_local_input,
                             recognition_source=args.recognition_source,
                             delegate_profile=args.delegate_profile,
                             api_profile=args.api_profile, decision_profile=args.decision_profile)
    app = None
    try:
        import uvicorn
        app = create_instant_http_app(session, token_env=args.token_env)
        config = uvicorn.Config(app, host=args.host, port=args.port, workers=1,
                                access_log=False, log_level="warning", use_colors=False,
                                proxy_headers=False, forwarded_allow_ips="", lifespan="on",
                                timeout_graceful_shutdown=None)
        uvicorn.Server(config).run()
    finally:
        if app is None:
            session.close()
        else:
            app.close()


if __name__ == "__main__":
    from app.runtime_lifecycle import InstallationLease
    with InstallationLease(ROOT):
        from app.runtime_update_schedule import schedule_check
        schedule_check(ROOT)
        main()
