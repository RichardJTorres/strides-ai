"""Entry point: auth → sync → chat, plus `charts` subcommand."""

import argparse
import math
import os
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

from . import db
from .auth import get_access_token
from .backends.claude import ClaudeBackend
from .backends.ollama import OllamaBackend, DEFAULT_HOST
from .charts_data import get_chart_data
from .coach import chat, build_initial_history, RECALL_MESSAGES
from .db import init_db, get_all_activities, get_activities_for_mode, get_recent_messages
from .profile import get_default_fields, profile_to_text
from .sync import sync_activities


def _build_backend(initial_history: list[dict]):
    provider = os.environ.get("PROVIDER", "claude").lower()

    if provider == "ollama":
        model = os.environ.get("OLLAMA_MODEL")
        if not model:
            print("OLLAMA_MODEL must be set when using PROVIDER=ollama")
            sys.exit(1)
        host = os.environ.get("OLLAMA_HOST", DEFAULT_HOST)
        return OllamaBackend(model, initial_history, host)

    # Default: Claude
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ANTHROPIC_API_KEY must be set when using PROVIDER=claude (the default)")
        sys.exit(1)
    model = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")
    return ClaudeBackend(api_key, initial_history, model)


# ── charts subcommand ─────────────────────────────────────────────────────────


def _run_charts(unit: str, output: str | None) -> None:
    try:
        import matplotlib
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
    except ImportError:
        print("matplotlib is required for charts: pip install matplotlib")
        sys.exit(1)

    init_db()
    activities = get_all_activities()
    if not activities:
        print("No activities found. Run 'strides-ai' to sync your Strava data first.")
        return

    data = get_chart_data(activities, unit)
    ul = "mi" if unit == "miles" else "km"

    fig, axes = plt.subplots(3, 1, figsize=(14, 16))
    fig.patch.set_facecolor("#111827")
    fig.suptitle("Training Dashboard", fontsize=16, fontweight="bold", color="#f3f4f6")

    _plot_weekly_mileage(axes[0], data["weekly_mileage"], ul, fig)
    _plot_atl_ctl(axes[1], data["atl_ctl"], ul, fig)
    _plot_pace_scatter(axes[2], data["pace_scatter"], data["pace_trends"], unit, ul, fig)

    plt.tight_layout(rect=[0, 0, 1, 0.96])

    out_path = Path(output) if output else Path.home() / ".strides_ai" / "charts.png"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out_path, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    print(f"Saved: {out_path}")

    try:
        plt.show()
    except Exception:
        pass  # headless / no display


def _style_ax(ax):
    """Apply dark-theme styling to a matplotlib axes."""
    ax.set_facecolor("#1f2937")
    ax.tick_params(colors="#9ca3af", labelsize=9)
    ax.xaxis.label.set_color("#9ca3af")
    ax.yaxis.label.set_color("#9ca3af")
    ax.title.set_color("#f3f4f6")
    for spine in ax.spines.values():
        spine.set_edgecolor("#374151")
    ax.grid(axis="y", color="#374151", linewidth=0.6, linestyle="--")


def _plot_weekly_mileage(ax, weeks: list[dict], ul: str, fig) -> None:
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from matplotlib.patches import Patch

    if not weeks:
        ax.text(0.5, 0.5, "No data", transform=ax.transAxes, ha="center", color="#6b7280")
        return

    # Show last 52 weeks for readability
    weeks = weeks[-52:]
    dates = [date.fromisoformat(w["week"]) for w in weeks]
    dists = [w["distance"] for w in weeks]
    rollavg = [w["rolling_avg"] for w in weeks]
    colors = ["#4ade80" if w["is_current"] else "#22d3ee" for w in weeks]

    ax.bar(dates, dists, color=colors, width=5, alpha=0.85, label=f"Weekly distance ({ul})")
    ax.plot(
        dates,
        rollavg,
        color="#fb923c",
        linewidth=2,
        linestyle="--",
        marker="o",
        markersize=3,
        label="4-week avg",
    )

    ax.set_title(f"Weekly {ul.upper() if ul == 'km' else 'Mileage'}")
    ax.set_ylabel(f"Distance ({ul})")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b '%y"))
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=35, ha="right")

    handles, labels = ax.get_legend_handles_labels()
    handles.append(Patch(color="#4ade80", alpha=0.85, label="Current week"))
    ax.legend(
        handles=handles, facecolor="#1f2937", edgecolor="#374151", labelcolor="#d1d5db", fontsize=9
    )
    _style_ax(ax)


def _plot_atl_ctl(ax, atl_ctl: list[dict], ul: str, fig) -> None:
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    if not atl_ctl:
        ax.text(0.5, 0.5, "No data", transform=ax.transAxes, ha="center", color="#6b7280")
        return

    # Show last 365 days
    atl_ctl = atl_ctl[-365:]
    dates2 = [date.fromisoformat(d["date"]) for d in atl_ctl]
    atl_vals = [d["atl"] for d in atl_ctl]
    ctl_vals = [d["ctl"] for d in atl_ctl]
    ratio_vals = [d["ratio"] if d["ratio"] is not None else float("nan") for d in atl_ctl]

    ax_ratio = ax.twinx()

    ax.plot(dates2, atl_vals, color="#ef4444", linewidth=1.5, label=f"ATL 7d ({ul}/day)")
    ax.plot(dates2, ctl_vals, color="#60a5fa", linewidth=1.5, label=f"CTL 42d ({ul}/day)")
    ax.set_ylabel(f"Load ({ul}/day)")

    ax_ratio.plot(
        dates2, ratio_vals, color="#a78bfa", linewidth=1.5, linestyle="--", label="ATL/CTL ratio"
    )
    ax_ratio.axhspan(0.8, 1.3, alpha=0.08, color="#22c55e")
    ax_ratio.axhspan(1.3, 2.5, alpha=0.08, color="#ef4444")
    ax_ratio.axhspan(0.0, 0.8, alpha=0.08, color="#6b7280")
    ax_ratio.axhline(0.8, color="#6b7280", linewidth=0.6, linestyle=":")
    ax_ratio.axhline(1.3, color="#ef4444", linewidth=0.6, linestyle=":")
    ax_ratio.set_ylim(0, 2.5)
    ax_ratio.set_ylabel("ATL/CTL ratio", color="#a78bfa")
    ax_ratio.tick_params(colors="#9ca3af", labelsize=9)
    ax_ratio.yaxis.label.set_color("#a78bfa")
    for spine in ax_ratio.spines.values():
        spine.set_edgecolor("#374151")

    ax.set_title("Training Load (ATL / CTL)")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b '%y"))
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=35, ha="right")

    lines1, labels1 = ax.get_legend_handles_labels()
    lines2, labels2 = ax_ratio.get_legend_handles_labels()
    ax.legend(
        lines1 + lines2,
        labels1 + labels2,
        loc="upper left",
        facecolor="#1f2937",
        edgecolor="#374151",
        labelcolor="#d1d5db",
        fontsize=9,
    )
    _style_ax(ax)

    annot = ax_ratio.annotate(
        "",
        xy=(0, 0),
        xytext=(15, 15),
        textcoords="offset points",
        bbox=dict(boxstyle="round,pad=0.4", fc="#1f2937", ec="#374151", alpha=0.95),
        arrowprops=dict(arrowstyle="->", color="#6b7280"),
        color="#f3f4f6",
        fontsize=8,
    )
    annot.set_visible(False)

    def on_hover(event):
        if event.inaxes not in (ax, ax_ratio):
            if annot.get_visible():
                annot.set_visible(False)
                fig.canvas.draw_idle()
            return
        if not dates2:
            return
        try:
            hover_date = mdates.num2date(event.xdata).date()
            idx = min(range(len(dates2)), key=lambda i: abs((dates2[i] - hover_date).days))
            d = atl_ctl[idx]
            r = ratio_vals[idx]
            r_str = f"{r:.2f}" if not math.isnan(r) else "N/A"
            if not math.isnan(r):
                zone = "⚠ Injury risk" if r > 1.3 else "↓ Detraining" if r < 0.8 else "✓ Optimal"
            else:
                zone = ""
            annot.xy = (mdates.date2num(dates2[idx]), r if not math.isnan(r) else 0)
            annot.set_text(
                f"{d['date']}\nATL: {d['atl']:.2f}  CTL: {d['ctl']:.2f}\nRatio: {r_str}  {zone}"
            )
            annot.set_visible(True)
            fig.canvas.draw_idle()
        except Exception:
            pass

    fig.canvas.mpl_connect("motion_notify_event", on_hover)


def _plot_pace_scatter(ax, scatter: dict, trends: dict, unit: str, ul: str, fig) -> None:
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    short_thresh = 3 if unit == "miles" else 5
    med_thresh = 6 if unit == "miles" else 10

    bucket_cfg = [
        ("long", f"Long (≥{med_thresh} {ul})", "#6366f1"),
        ("medium", f"Medium ({short_thresh}–{med_thresh} {ul})", "#10b981"),
        ("short", f"Short (<{short_thresh} {ul})", "#f59e0b"),
    ]

    def fmt_pace(s, _):
        return f"{int(s)//60}:{int(s)%60:02d}"

    any_data = False
    for bucket, label, color in bucket_cfg:
        pts = scatter.get(bucket, [])
        if not pts:
            continue
        any_data = True
        dates_b = [date.fromisoformat(p["date"]) for p in pts]
        paces = [p["pace_s"] for p in pts]
        ax.scatter(dates_b, paces, color=color, alpha=0.65, s=18, label=label)

        tr = trends.get(bucket, [])
        if len(tr) == 2:
            t_dates = [date.fromisoformat(t["date"]) for t in tr]
            t_paces = [t["pace_s"] for t in tr]
            ax.plot(t_dates, t_paces, color=color, linewidth=2.0, alpha=0.85)

    if not any_data:
        ax.text(0.5, 0.5, "No data with pace", transform=ax.transAxes, ha="center", color="#6b7280")
        _style_ax(ax)
        return

    ax.yaxis.set_major_formatter(plt.FuncFormatter(fmt_pace))
    ax.invert_yaxis()  # faster (lower seconds) at top
    ax.set_title(f"Pace Trend by Distance (min/{ul})")
    ax.set_ylabel(f"Pace (min/{ul})")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b '%y"))
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=35, ha="right")
    ax.legend(facecolor="#1f2937", edgecolor="#374151", labelcolor="#d1d5db", fontsize=9)
    _style_ax(ax)


# ── main ──────────────────────────────────────────────────────────────────────


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(prog="strides-ai")
    subparsers = parser.add_subparsers(dest="command")

    # charts subcommand
    charts_p = subparsers.add_parser("charts", help="Generate training charts")
    charts_p.add_argument(
        "--unit",
        choices=["miles", "km"],
        default="miles",
        help="Distance unit (default: miles)",
    )
    charts_p.add_argument(
        "--output",
        metavar="FILE",
        help="Save PNG to FILE (default: ~/.strides_ai/charts.png)",
    )

    # Top-level flags for the default chat mode
    parser.add_argument(
        "--mode",
        choices=["running", "cycling", "hybrid"],
        default="running",
        help="Training mode (default: running)",
    )
    args = parser.parse_args()

    # ── charts ────────────────────────────────────────────────────────────────
    if args.command == "charts":
        _run_charts(args.unit, args.output)
        return

    # ── chat (default) ────────────────────────────────────────────────────────
    init_db()
    mode = args.mode

    client_id = os.environ.get("STRAVA_CLIENT_ID")
    client_secret = os.environ.get("STRAVA_CLIENT_SECRET")
    if not client_id or not client_secret:
        print("Missing STRAVA_CLIENT_ID or STRAVA_CLIENT_SECRET.")
        print("Copy .env.example to .env and fill in your credentials.")
        sys.exit(1)

    print("Authenticating with Strava…")
    access_token = get_access_token(client_id, client_secret)

    print("Syncing activities…")
    new_count = sync_activities(access_token)
    if new_count:
        print(f"  {new_count} new activities synced.")
    else:
        print("  Already up to date.")

    activities = get_activities_for_mode(mode)
    prior_messages = get_recent_messages(RECALL_MESSAGES, mode=mode)
    initial_history = build_initial_history(activities, prior_messages, mode=mode)

    backend = _build_backend(initial_history)
    profile_fields = db.get_profile_fields(mode) or get_default_fields(mode)
    profile = profile_to_text(profile_fields, mode)
    chat(backend, profile, mode=mode)


if __name__ == "__main__":
    main()
