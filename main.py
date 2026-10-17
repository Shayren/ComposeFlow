"""ComposeFlow entrypoint."""

import argparse
import json
import sys
from pathlib import Path

from composeflow.compose_cli import ComposeValidationError, validate_response_report
from composeflow.display_placement import place_app_on_laptop_display
from composeflow.ui.app import ComposeFlowApp


def main(argv=None):
    parser = argparse.ArgumentParser(description="Open ComposeFlow")
    parser.add_argument("--run-id")
    parser.add_argument("--output-path", type=Path)
    parser.add_argument("--report-workflow", type=Path)
    parser.add_argument("--response-json", type=Path)
    args = parser.parse_args(argv)
    if bool(args.run_id) != bool(args.output_path):
        parser.error("--run-id and --output-path must be supplied together")
    if bool(args.report_workflow) != bool(args.response_json):
        parser.error("--report-workflow and --response-json must be supplied together")
    if args.report_workflow and args.run_id:
        parser.error("Launch and Report mode cannot be opened together")
    try:
        document = (validate_response_report(args.report_workflow, args.response_json)
                    if args.report_workflow else None)
    except ComposeValidationError as exc:
        print(f"ComposeFlow report failed: {exc}", file=sys.stderr)
        return 2
    app = ComposeFlowApp(run_id=args.run_id, output_path=args.output_path)
    place_app_on_laptop_display(app)
    app.update_idletasks()
    if document is not None:
        try:
            app.show_report(document)
        except ComposeValidationError as exc:
            app.destroy()
            print(f"ComposeFlow report failed: {exc}", file=sys.stderr)
            return 2
    app.mainloop()
    if app.launched_path is not None:
        print("COMPOSE_LAUNCHED " + json.dumps(
            {"runId": app.run_id, "workflowPath": str(app.launched_path)}),
            flush=True)
        return 0
    if args.run_id:
        print("COMPOSE_CANCELLED " + json.dumps({"runId": args.run_id}), flush=True)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
