#!/usr/bin/env python3
"""
Generate a beautiful HTML test report from an Xcode .xcresult bundle.

Usage:
    python3 generate_report.py <path-to.xcresult> [--output report.html] [--title "My Report"]

Features:
- Parses test results via xcresulttool
- Exports all attachments (screenshots, videos, etc.)
- Embeds images as base64 data URIs
- Embeds videos as base64 data URIs
- Generates a single self-contained HTML file
"""

import argparse
import base64
import json
import mimetypes
import os
import re
import subprocess
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def check_xcresulttool():
    """Verify xcresulttool is available. Exit with helpful message if not."""
    try:
        result = subprocess.run(
            ["xcrun", "xcresulttool", "version"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            print(
                "Error: xcresulttool is not available.\n"
                "Install Xcode command-line tools: xcode-select --install",
                file=sys.stderr,
            )
            sys.exit(1)
    except FileNotFoundError:
        print(
            "Error: 'xcrun' not found. Xcode command-line tools are required.\n"
            "Install them with: xcode-select --install",
            file=sys.stderr,
        )
        sys.exit(1)
    except subprocess.TimeoutExpired:
        print("Error: xcresulttool timed out. Is Xcode installed correctly?", file=sys.stderr)
        sys.exit(1)


def run_xcresulttool(*args):
    """Run xcresulttool and return parsed JSON output."""
    cmd = ["xcrun", "xcresulttool"] + list(args)
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            # xcresulttool typically completes within 30 seconds even for large bundles.
            # 120s timeout accounts for slow disks or very large result bundles.
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        print(f"Warning: xcresulttool timed out running: {' '.join(args)}", file=sys.stderr)
        return None
    if result.returncode != 0:
        print(f"Warning: xcresulttool failed for '{args[0]} {args[1] if len(args) > 1 else ''}':\n  {result.stderr.strip()}", file=sys.stderr)
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return result.stdout


def get_test_summary(xcresult_path):
    """Get test results summary."""
    return run_xcresulttool("get", "test-results", "summary", "--path", xcresult_path, "--compact")


def get_test_list(xcresult_path):
    """Get full test tree."""
    return run_xcresulttool("get", "test-results", "tests", "--path", xcresult_path, "--compact")


def export_attachments(xcresult_path, output_dir):
    """Export all attachments and return manifest data.

    Returns an empty list (not an error) when the bundle has no attachments,
    which is normal for unit-test-only runs without screenshots.
    """
    cmd = [
        "xcrun", "xcresulttool", "export", "attachments",
        "--path", xcresult_path,
        "--output-path", output_dir,
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            # Attachment export can be slow for bundles with many large videos.
            # 300s (5 min) allows for bundles up to ~1 GB of attachments.
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        print("Warning: attachment export timed out (bundle may have very large videos)", file=sys.stderr)
        return []
    if result.returncode != 0:
        # Non-zero exit is expected when the bundle simply has no attachments
        if "no attachments" in result.stderr.lower():
            return []
        print(f"Warning: attachment export failed:\n  {result.stderr.strip()}", file=sys.stderr)
        return []

    manifest_path = os.path.join(output_dir, "manifest.json")
    if not os.path.exists(manifest_path):
        # No manifest means no attachments were exported
        return []

    with open(manifest_path) as f:
        return json.load(f)


def file_to_data_uri(filepath):
    """Convert a file to a base64 data URI."""
    mime, _ = mimetypes.guess_type(filepath)
    if mime is None:
        ext = os.path.splitext(filepath)[1].lower()
        mime_map = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".heic": "image/heic",
            ".mp4": "video/mp4",
            ".mov": "video/quicktime",
            ".m4v": "video/mp4",
            ".webm": "video/webm",
            ".txt": "text/plain",
            ".log": "text/plain",
            ".json": "application/json",
            ".xml": "application/xml",
            ".plist": "application/xml",
        }
        mime = mime_map.get(ext, "application/octet-stream")

    with open(filepath, "rb") as f:
        data = base64.b64encode(f.read()).decode("ascii")
    return f"data:{mime};base64,{data}"


def copy_video_to_output(filepath, videos_dir, index):
    """Copy a video file to the videos output directory and return a relative path."""
    os.makedirs(videos_dir, exist_ok=True)
    ext = os.path.splitext(filepath)[1] or ".mp4"
    dest_name = f"video_{index}{ext}"
    shutil.copy2(filepath, os.path.join(videos_dir, dest_name))
    return f"videos/{dest_name}"


def is_image(filename):
    return any(filename.lower().endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".gif", ".heic", ".tiff"))


def is_video(filename):
    return any(filename.lower().endswith(ext) for ext in (".mp4", ".mov", ".m4v", ".webm"))


def flatten_tests(nodes, depth=0):
    """Recursively flatten test nodes into a list with depth info."""
    results = []
    for node in nodes:
        results.append({
            "name": node.get("name", "Unknown"),
            "nodeType": node.get("nodeType", ""),
            "result": node.get("result", ""),
            "duration": node.get("duration", ""),
            "durationInSeconds": node.get("durationInSeconds", 0),
            "nodeIdentifier": node.get("nodeIdentifier", ""),
            "details": node.get("details", ""),
            "depth": depth,
        })
        if "children" in node:
            results.extend(flatten_tests(node["children"], depth + 1))
    return results


def count_results(nodes):
    """Count test results recursively."""
    counts = {"Passed": 0, "Failed": 0, "Skipped": 0, "Expected Failure": 0, "unknown": 0, "total": 0}
    for node in nodes:
        if node.get("nodeType") in ("Test Case", "Test Case Run"):
            result = node.get("result", "unknown")
            counts[result] = counts.get(result, 0) + 1
            counts["total"] += 1
        if "children" in node:
            child_counts = count_results(node["children"])
            for k, v in child_counts.items():
                counts[k] = counts.get(k, 0) + v
    return counts


def build_attachment_map(manifest, attachments_dir):
    """Build a map of test_identifier -> list of attachment info."""
    att_map = {}
    for entry in manifest:
        test_id = entry.get("testIdentifier", "unknown")
        attachments = entry.get("attachments", [])
        if not isinstance(attachments, list):
            attachments = [attachments]
        for att in attachments:
            filename = att.get("exportedFileName", "")
            human_name = att.get("suggestedHumanReadableName", filename)
            is_failure = att.get("isAssociatedWithFailure", False)
            filepath = os.path.join(attachments_dir, filename)
            if not os.path.exists(filepath):
                continue
            if test_id not in att_map:
                att_map[test_id] = []
            att_map[test_id].append({
                "filename": filename,
                "humanName": human_name,
                "filepath": filepath,
                "isFailure": is_failure,
                "timestamp": att.get("timestamp"),
            })
    return att_map


def generate_html(test_data, summary_data, attachment_map, title, xcresult_path, videos_dir=None):
    """Generate the complete HTML report."""
    test_nodes = test_data.get("testNodes", []) if test_data else []
    devices = test_data.get("devices", []) if test_data else []
    configs = test_data.get("testPlanConfigurations", []) if test_data else []

    flat_tests = flatten_tests(test_nodes)
    counts = count_results(test_nodes)

    # Summary info from summary endpoint
    start_time = ""
    end_time = ""
    total_duration = ""
    if summary_data:
        if not counts["total"]:
            counts["total"] = summary_data.get("totalTestCount", 0)
            counts["Passed"] = summary_data.get("passedTests", 0)
            counts["Failed"] = summary_data.get("failedTests", 0)
            counts["Skipped"] = summary_data.get("skippedTests", 0)
            counts["Expected Failure"] = summary_data.get("expectedFailures", 0)
        start_ts = summary_data.get("startTime")
        end_ts = summary_data.get("endTime")
        # Fallback to finishTime if endTime is not present
        if not end_ts:
            end_ts = summary_data.get("finishTime")
        if start_ts:
            start_time = datetime.fromtimestamp(start_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        if end_ts:
            end_time = datetime.fromtimestamp(end_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        if start_ts and end_ts:
            dur = end_ts - start_ts
            mins, secs = divmod(dur, 60)
            total_duration = f"{int(mins)}m {secs:.1f}s"

    pass_rate = (counts["Passed"] / counts["total"] * 100) if counts["total"] > 0 else 0
    all_passed = counts["Failed"] == 0 and counts["total"] > 0

    # Collect all attachments for the gallery
    all_attachments = []
    for test_id, atts in attachment_map.items():
        for att in atts:
            att["testId"] = test_id
            all_attachments.append(att)

    image_attachments = [a for a in all_attachments if is_image(a["filename"])]
    video_attachments = [a for a in all_attachments if is_video(a["filename"])]
    other_attachments = [a for a in all_attachments if not is_image(a["filename"]) and not is_video(a["filename"])]

    total_attachments = len(all_attachments)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{_esc(title)}</title>
<style>
:root {{
  --background: #0a0a0a;
  --foreground: #fafafa;
  --card: #171717;
  --muted: #262626;
  --muted-foreground: #a1a1a1;
  --accent: #3f3f3f;
  --border: rgba(255,255,255,0.1);
  --input: rgba(255,255,255,0.15);
  --ring: #737373;
  --radius: 0.625rem;
  --success: #22c55e;
  --success-bg: rgba(34,197,94,0.1);
  --destructive: #ef4444;
  --destructive-bg: rgba(239,68,68,0.1);
  --warning: #eab308;
  --warning-bg: rgba(234,179,8,0.1);
  --info: #3b82f6;
  --info-bg: rgba(59,130,246,0.1);
  --purple: #a855f7;
  --purple-bg: rgba(168,85,247,0.1);
  --mono: 'SF Mono', 'Cascadia Code', 'Menlo', monospace;
}}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
  background: var(--background);
  color: var(--foreground);
  line-height: 1.6;
  -webkit-font-smoothing: antialiased;
}}
.container {{ max-width: 1200px; margin: 0 auto; padding: 24px; }}

/* Header */
.header {{
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 32px;
  margin-bottom: 24px;
  position: relative;
  overflow: hidden;
}}
.header::before {{
  content: '';
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 3px;
  background: {'var(--success)' if all_passed else 'var(--destructive)'};
}}
.header h1 {{
  font-size: 24px;
  font-weight: 600;
  margin-bottom: 8px;
  letter-spacing: -0.5px;
}}
.header .meta {{
  color: var(--muted-foreground);
  font-size: 13px;
  display: flex;
  gap: 20px;
  flex-wrap: wrap;
}}
.header .meta span {{ display: flex; align-items: center; gap: 6px; }}

/* Stats Grid */
.stats-grid {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 16px;
  margin-bottom: 24px;
}}
.stat-card {{
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 20px;
  text-align: center;
  transition: transform 0.15s ease;
}}
.stat-card:hover {{ transform: translateY(-2px); }}
.stat-card .value {{
  font-size: 36px;
  font-weight: 700;
  font-family: var(--mono);
  letter-spacing: -1px;
  line-height: 1.2;
}}
.stat-card .label {{
  font-size: 12px;
  color: var(--muted-foreground);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-top: 4px;
}}
.stat-card.passed .value {{ color: var(--success); }}
.stat-card.failed .value {{ color: var(--destructive); }}
.stat-card.skipped .value {{ color: var(--warning); }}
.stat-card.total .value {{ color: var(--info); }}

/* Progress Bar */
.progress-container {{
  margin-bottom: 24px;
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 20px;
}}
.progress-bar {{
  height: 8px;
  border-radius: 4px;
  background: var(--muted);
  overflow: hidden;
  display: flex;
}}
.progress-bar .segment {{
  height: 100%;
  transition: width 0.5s ease;
}}
.progress-bar .pass {{ background: var(--success); }}
.progress-bar .fail {{ background: var(--destructive); }}
.progress-bar .skip {{ background: var(--warning); }}
.progress-legend {{
  display: flex;
  gap: 20px;
  margin-top: 12px;
  font-size: 13px;
  color: var(--muted-foreground);
}}
.progress-legend span {{ display: flex; align-items: center; gap: 6px; }}
.progress-legend .dot {{
  width: 8px; height: 8px;
  border-radius: 50%;
  display: inline-block;
}}

/* Tabs */
.tabs {{
  display: flex;
  gap: 4px;
  margin-bottom: 24px;
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 4px;
}}
.tab {{
  padding: 10px 20px;
  cursor: pointer;
  border-radius: calc(var(--radius) - 2px);
  font-size: 14px;
  font-weight: 500;
  color: var(--muted-foreground);
  border: none;
  background: none;
  transition: all 0.15s ease;
}}
.tab:hover {{ color: var(--foreground); background: var(--muted); }}
.tab.active {{ color: var(--foreground); background: var(--muted); }}
.tab .badge {{
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 20px;
  height: 20px;
  padding: 0 6px;
  border-radius: 10px;
  font-size: 11px;
  font-family: var(--mono);
  margin-left: 6px;
  background: var(--accent);
}}
.tab-content {{ display: none; }}
.tab-content.active {{ display: block; }}

/* Section */
.section {{
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  margin-bottom: 24px;
  overflow: hidden;
}}
.section-header {{
  padding: 16px 20px;
  font-size: 15px;
  font-weight: 600;
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  gap: 10px;
}}

/* Test Table */
.test-table {{
  width: 100%;
  border-collapse: collapse;
}}
.test-table th {{
  text-align: left;
  padding: 12px 16px;
  font-size: 11px;
  font-weight: 600;
  color: var(--muted-foreground);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  background: var(--card);
  border-bottom: 1px solid var(--border);
  position: sticky;
  top: 0;
  z-index: 1;
}}
.test-table td {{
  padding: 10px 16px;
  border-bottom: 1px solid var(--border);
  font-size: 14px;
  vertical-align: middle;
}}
.test-table tr:last-child td {{ border-bottom: none; }}
.test-table tr:hover {{ background: var(--muted); }}
.test-table .name {{ font-weight: 500; }}
.test-table .duration {{
  color: var(--muted-foreground);
  font-family: var(--mono);
  font-size: 13px;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}}

/* Status Badges */
.badge-pass {{
  display: inline-flex; align-items: center; gap: 4px;
  color: var(--success);
  background: var(--success-bg);
  padding: 2px 10px;
  border-radius: 9999px;
  font-size: 12px;
  font-weight: 600;
}}
.badge-fail {{
  display: inline-flex; align-items: center; gap: 4px;
  color: var(--destructive);
  background: var(--destructive-bg);
  padding: 2px 10px;
  border-radius: 9999px;
  font-size: 12px;
  font-weight: 600;
}}
.badge-skip {{
  display: inline-flex; align-items: center; gap: 4px;
  color: var(--warning);
  background: var(--warning-bg);
  padding: 2px 10px;
  border-radius: 9999px;
  font-size: 12px;
  font-weight: 600;
}}
.badge-expected {{
  display: inline-flex; align-items: center; gap: 4px;
  color: var(--purple);
  background: var(--purple-bg);
  padding: 2px 10px;
  border-radius: 9999px;
  font-size: 12px;
  font-weight: 600;
}}

/* Suite grouping */
.suite-row td {{
  background: var(--muted);
  font-weight: 600;
  font-size: 13px;
  color: var(--muted-foreground);
  padding: 8px 16px;
}}
.suite-row td:first-child {{ padding-left: 16px; }}

/* Devices */
.device-cards {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
  gap: 12px;
  padding: 16px;
}}
.device-card {{
  background: var(--muted);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 16px;
}}
.device-card .name {{ font-weight: 600; margin-bottom: 4px; }}
.device-card .detail {{ font-size: 13px; color: var(--muted-foreground); }}

/* Gallery */
.gallery-grid {{
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 16px;
  padding: 16px;
}}
.gallery-item {{
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
  transition: transform 0.15s ease;
}}
.gallery-item:hover {{ transform: translateY(-2px); }}
.gallery-item img {{
  width: 100%;
  height: auto;
  display: block;
  cursor: pointer;
}}
.gallery-item video {{
  width: 100%;
  height: auto;
  display: block;
  background: #000;
}}
.gallery-caption {{
  padding: 10px 12px;
  font-size: 12px;
  color: var(--muted-foreground);
  border-top: 1px solid var(--border);
}}
.gallery-caption .test-name {{
  font-weight: 600;
  color: var(--foreground);
  display: block;
  margin-bottom: 2px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}}
.gallery-caption .att-name {{
  display: block;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}}
.gallery-caption .failure-tag {{
  display: inline-block;
  background: var(--destructive-bg);
  color: var(--destructive);
  font-size: 11px;
  font-weight: 600;
  padding: 1px 6px;
  border-radius: 4px;
  margin-top: 4px;
}}

/* Lightbox */
.lightbox {{
  display: none;
  position: fixed;
  top: 0; left: 0; right: 0; bottom: 0;
  background: rgba(0,0,0,0.92);
  z-index: 1000;
  justify-content: center;
  align-items: center;
  cursor: pointer;
  padding: 40px;
}}
.lightbox.active {{ display: flex; }}
.lightbox img {{
  max-width: 95vw;
  max-height: 90vh;
  border-radius: var(--radius);
}}
.lightbox-close {{
  position: fixed;
  top: 16px; right: 20px;
  font-size: 28px;
  color: #fff;
  cursor: pointer;
  z-index: 1001;
  background: rgba(255,255,255,0.1);
  border: 1px solid rgba(255,255,255,0.1);
  width: 40px; height: 40px;
  border-radius: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
}}

/* Filter */
.filter-bar {{
  display: flex;
  gap: 8px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border);
  flex-wrap: wrap;
}}
.filter-btn {{
  padding: 6px 14px;
  border: 1px solid var(--border);
  border-radius: 9999px;
  background: none;
  color: var(--muted-foreground);
  font-size: 13px;
  cursor: pointer;
  transition: all 0.15s ease;
}}
.filter-btn:hover {{ border-color: var(--info); color: var(--info); }}
.filter-btn.active {{ background: var(--info-bg); border-color: var(--info); color: var(--info); }}

/* Empty state */
.empty-state {{
  padding: 48px;
  text-align: center;
  color: var(--muted-foreground);
}}
.empty-state .icon {{ font-size: 48px; margin-bottom: 12px; opacity: 0.5; }}
.empty-state .message {{ font-size: 16px; }}

/* Scrollable table */
.table-wrapper {{
  max-height: 700px;
  overflow-y: auto;
}}
.table-wrapper::-webkit-scrollbar {{ width: 6px; }}
.table-wrapper::-webkit-scrollbar-track {{ background: var(--card); }}
.table-wrapper::-webkit-scrollbar-thumb {{ background: var(--accent); border-radius: 3px; }}

footer {{
  text-align: center;
  padding: 24px;
  color: var(--muted-foreground);
  font-size: 13px;
}}
</style>
</head>
<body>

<div class="container">

<!-- Header -->
<div class="header">
  <h1>{"&#9989;" if all_passed else "&#10060;"} {_esc(title)}</h1>
  <div class="meta">
    <span>&#128197; {start_time or "N/A"}</span>
    <span>&#9202; {total_duration or "N/A"}</span>
    <span>&#128196; {_esc(os.path.basename(xcresult_path))}</span>
  </div>
</div>

<!-- Stats -->
<div class="stats-grid">
  <div class="stat-card total">
    <div class="value">{counts['total']}</div>
    <div class="label">Total Tests</div>
  </div>
  <div class="stat-card passed">
    <div class="value">{counts['Passed']}</div>
    <div class="label">Passed</div>
  </div>
  <div class="stat-card failed">
    <div class="value">{counts['Failed']}</div>
    <div class="label">Failed</div>
  </div>
  <div class="stat-card skipped">
    <div class="value">{counts['Skipped'] + counts.get('Expected Failure', 0)}</div>
    <div class="label">Skipped</div>
  </div>
</div>

<!-- Progress Bar -->
<div class="progress-container">
  <div style="display:flex; justify-content:space-between; margin-bottom:8px;">
    <span style="font-weight:600;">Pass Rate</span>
    <span style="font-weight:700; color:{'var(--success)' if pass_rate >= 90 else 'var(--destructive)' if pass_rate < 70 else 'var(--warning)'};">{pass_rate:.1f}%</span>
  </div>
  <div class="progress-bar">
    <div class="segment pass" style="width:{pass_rate:.1f}%"></div>
    <div class="segment fail" style="width:{(counts['Failed'] / counts['total'] * 100) if counts['total'] else 0:.1f}%"></div>
    <div class="segment skip" style="width:{((counts['Skipped'] + counts.get('Expected Failure', 0)) / counts['total'] * 100) if counts['total'] else 0:.1f}%"></div>
  </div>
  <div class="progress-legend">
    <span><span class="dot" style="background:var(--success)"></span> Passed ({counts['Passed']})</span>
    <span><span class="dot" style="background:var(--destructive)"></span> Failed ({counts['Failed']})</span>
    <span><span class="dot" style="background:var(--warning)"></span> Skipped ({counts['Skipped'] + counts.get('Expected Failure', 0)})</span>
  </div>
</div>

<!-- Tabs -->
<div class="tabs">
  <button class="tab active" onclick="switchTab('tests')">&#128203; Tests <span class="badge">{counts['total']}</span></button>
  <button class="tab" onclick="switchTab('images')">&#128247; Screenshots <span class="badge">{len(image_attachments)}</span></button>
  <button class="tab" onclick="switchTab('videos')">&#127909; Videos <span class="badge">{len(video_attachments)}</span></button>
  <button class="tab" onclick="switchTab('devices')">&#128241; Devices <span class="badge">{len(devices)}</span></button>
</div>

<!-- Tests Tab -->
<div id="tab-tests" class="tab-content active">
  <div class="section">
    <div class="filter-bar">
      <button class="filter-btn active" onclick="filterTests('all', this)">All</button>
      <button class="filter-btn" onclick="filterTests('Passed', this)">Passed</button>
      <button class="filter-btn" onclick="filterTests('Failed', this)">Failed</button>
      <button class="filter-btn" onclick="filterTests('Skipped', this)">Skipped</button>
    </div>
    <div class="table-wrapper">
      <table class="test-table">
        <thead>
          <tr>
            <th style="width:50%">Test</th>
            <th style="width:15%">Status</th>
            <th style="width:15%">Duration</th>
            <th style="width:20%">Attachments</th>
          </tr>
        </thead>
        <tbody>
"""

    # Build test rows
    for t in flat_tests:
        node_type = t["nodeType"]
        name = t["name"]
        result = t["result"]
        duration = t["duration"]
        node_id = t["nodeIdentifier"]

        # Skip top-level plan nodes
        if node_type in ("Test Plan",):
            continue

        # Suite headers
        if node_type in ("Unit test bundle", "UI test bundle", "Test Suite"):
            badge_html = ""
            if result == "Passed":
                badge_html = '<span class="badge-pass">Passed</span>'
            elif result == "Failed":
                badge_html = '<span class="badge-fail">Failed</span>'
            html += f"""          <tr class="suite-row" data-result="{_esc(result)}">
            <td colspan="4">{_esc(name)} {badge_html}</td>
          </tr>
"""
            continue

        # Test case rows
        if node_type in ("Test Case", "Test Case Run"):
            badge = ""
            if result == "Passed":
                badge = '<span class="badge-pass">&#10003; Passed</span>'
            elif result == "Failed":
                badge = '<span class="badge-fail">&#10007; Failed</span>'
            elif result == "Skipped":
                badge = '<span class="badge-skip">&#8722; Skipped</span>'
            elif result == "Expected Failure":
                badge = '<span class="badge-expected">&#10003; Expected</span>'
            else:
                badge = f'<span class="badge-skip">{_esc(result)}</span>'

            # Count attachments for this test
            att_count = len(attachment_map.get(node_id, []))
            att_html = f'<span style="color:var(--info)">{att_count} file{"s" if att_count != 1 else ""}</span>' if att_count else '<span style="color:var(--muted-foreground)">-</span>'

            indent = max(0, t["depth"] - 2) * 20
            html += f"""          <tr class="test-row" data-result="{_esc(result)}">
            <td class="name" style="padding-left:{16 + indent}px">{_esc(name)}</td>
            <td>{badge}</td>
            <td class="duration">{_esc(duration) if duration else '-'}</td>
            <td>{att_html}</td>
          </tr>
"""

    html += """        </tbody>
      </table>
    </div>
  </div>
</div>

"""

    # Images Tab
    html += """<!-- Images Tab -->
<div id="tab-images" class="tab-content">
  <div class="section">
    <div class="section-header">&#128247; Screenshots &amp; Images</div>
"""
    if image_attachments:
        html += '    <div class="gallery-grid">\n'
        for att in image_attachments:
            data_uri = file_to_data_uri(att["filepath"])
            test_display = att["testId"].split("/")[-1] if "/" in att["testId"] else att["testId"]
            failure_tag = '<span class="failure-tag">Failure</span>' if att["isFailure"] else ""
            html += f"""      <div class="gallery-item">
        <img src="{data_uri}" alt="{_esc(att['humanName'])}" onclick="openLightbox(this.src)" loading="lazy">
        <div class="gallery-caption">
          <span class="test-name">{_esc(test_display)}</span>
          <span class="att-name">{_esc(att['humanName'])}</span>
          {failure_tag}
        </div>
      </div>
"""
        html += '    </div>\n'
    else:
        html += """    <div class="empty-state">
      <div class="icon">&#128247;</div>
      <div class="message">No screenshots or images in this test run</div>
    </div>
"""
    html += """  </div>
</div>

"""

    # Videos Tab
    html += """<!-- Videos Tab -->
<div id="tab-videos" class="tab-content">
  <div class="section">
    <div class="section-header">&#127909; Videos</div>
"""
    if video_attachments:
        html += '    <div class="gallery-grid">\n'
        for i, att in enumerate(video_attachments):
            if videos_dir:
                video_src = copy_video_to_output(att["filepath"], videos_dir, i)
            else:
                video_src = file_to_data_uri(att["filepath"])
            test_display = att["testId"].split("/")[-1] if "/" in att["testId"] else att["testId"]
            failure_tag = '<span class="failure-tag">Failure</span>' if att["isFailure"] else ""
            html += f"""      <div class="gallery-item">
        <video controls preload="metadata" poster="">
          <source src="{video_src}" type="video/mp4">
          Your browser does not support video playback.
        </video>
        <div class="gallery-caption">
          <span class="test-name">{_esc(test_display)}</span>
          <span class="att-name">{_esc(att['humanName'])}</span>
          {failure_tag}
        </div>
      </div>
"""
        html += '    </div>\n'
    else:
        html += """    <div class="empty-state">
      <div class="icon">&#127909;</div>
      <div class="message">No videos in this test run</div>
    </div>
"""
    html += """  </div>
</div>

"""

    # Devices Tab
    html += """<!-- Devices Tab -->
<div id="tab-devices" class="tab-content">
  <div class="section">
    <div class="section-header">&#128241; Test Devices</div>
"""
    if devices:
        html += '    <div class="device-cards">\n'
        for dev in devices:
            html += f"""      <div class="device-card">
        <div class="name">{_esc(dev.get('deviceName', 'Unknown'))}</div>
        <div class="detail">{_esc(dev.get('modelName', ''))}</div>
        <div class="detail">{_esc(dev.get('platform', ''))} {_esc(dev.get('osVersion', ''))}</div>
        <div class="detail">{_esc(dev.get('architecture', ''))}</div>
      </div>
"""
        html += '    </div>\n'
    else:
        html += """    <div class="empty-state">
      <div class="icon">&#128241;</div>
      <div class="message">No device information available</div>
    </div>
"""
    html += """  </div>
</div>

"""

    # Lightbox + Scripts
    html += """<!-- Lightbox -->
<div class="lightbox" id="lightbox" onclick="closeLightbox()">
  <button class="lightbox-close" onclick="closeLightbox()">&times;</button>
  <img id="lightbox-img" src="" alt="Enlarged">
</div>

<footer>
  Generated by test-report-generator &middot; """ + datetime.now().strftime("%Y-%m-%d %H:%M:%S") + """
</footer>

</div>

<script>
function switchTab(name) {
  document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(el => el.classList.remove('active'));
  document.getElementById('tab-' + name).classList.add('active');
  event.target.closest('.tab').classList.add('active');
}

function filterTests(result, btn) {
  document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  document.querySelectorAll('.test-row').forEach(row => {
    if (result === 'all' || row.dataset.result === result) {
      row.style.display = '';
    } else {
      row.style.display = 'none';
    }
  });
  // Always show suite rows
  document.querySelectorAll('.suite-row').forEach(row => {
    row.style.display = '';
  });
}

function openLightbox(src) {
  document.getElementById('lightbox-img').src = src;
  document.getElementById('lightbox').classList.add('active');
  document.body.style.overflow = 'hidden';
}

function closeLightbox() {
  document.getElementById('lightbox').classList.remove('active');
  document.body.style.overflow = '';
}

document.addEventListener('keydown', function(e) {
  if (e.key === 'Escape') closeLightbox();
});
</script>

</body>
</html>"""

    return html


def _esc(text):
    """HTML escape."""
    if not text:
        return ""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def main():
    parser = argparse.ArgumentParser(
        description="Generate a beautiful HTML test report from an Xcode .xcresult bundle",
        epilog="Example: python3 generate_report.py ./Test.xcresult -o report.html -t 'Build 42'",
    )
    parser.add_argument("xcresult", help="Path to .xcresult bundle")
    parser.add_argument("--output", "-o", default=None, help="Output HTML file path (default: <xcresult-name>_report.html)")
    parser.add_argument("--title", "-t", default=None, help="Report title (default: derived from bundle name)")
    args = parser.parse_args()

    xcresult_path = os.path.abspath(args.xcresult)

    # Validate input
    if not os.path.exists(xcresult_path):
        print(
            f"Error: '{xcresult_path}' does not exist.\n"
            f"Hint: Find .xcresult bundles with:\n"
            f"  find ~/Library/Developer/Xcode/DerivedData -name '*.xcresult' -maxdepth 5 | head -5",
            file=sys.stderr,
        )
        sys.exit(1)

    if not xcresult_path.endswith(".xcresult"):
        print(
            f"Warning: '{os.path.basename(xcresult_path)}' does not have .xcresult extension. Proceeding anyway.",
            file=sys.stderr,
        )

    # Check xcresulttool availability
    check_xcresulttool()

    title = args.title or os.path.basename(xcresult_path).replace(".xcresult", "") + " Test Report"

    output_path = args.output
    if not output_path:
        base = os.path.basename(xcresult_path).replace(".xcresult", "")
        output_path = os.path.join(os.getcwd(), f"{base}_report.html")

    print(f"Parsing test results from: {xcresult_path}")

    # Get test data
    summary_data = get_test_summary(xcresult_path)
    test_count = ""
    device_count = ""
    if summary_data:
        total = summary_data.get("totalTestCount", "?")
        test_count = f" ({total} tests)"
    test_data = get_test_list(xcresult_path)
    if test_data:
        device_count = f", {len(test_data.get('devices', []))} device(s)" if test_data.get("devices") else ""
    print(f"  Fetching test summary... OK{test_count}{device_count}")
    print(f"  Fetching test list... OK")

    if not test_data and not summary_data:
        print(
            "Error: Could not read test results from the bundle.\n"
            "The bundle may not contain test data (e.g., it may be a build-only result).\n"
            f"Verify with: xcrun xcresulttool get test-results summary --path '{xcresult_path}'",
            file=sys.stderr,
        )
        sys.exit(1)

    # Export attachments to temp dir
    print("  Exporting attachments...", end=" ", flush=True)
    with tempfile.TemporaryDirectory(prefix="test-report-") as tmp_dir:
        manifest = export_attachments(xcresult_path, tmp_dir)
        attachment_map = build_attachment_map(manifest, tmp_dir)

        all_atts = [a for atts in attachment_map.values() for a in atts]
        img_count = sum(1 for a in all_atts if is_image(a["filename"]))
        vid_count = sum(1 for a in all_atts if is_video(a["filename"]))
        total_att = len(all_atts)
        print("OK")
        print(f"  Found {total_att} attachments across {len(attachment_map)} tests ({img_count} images, {vid_count} videos)")

        # Compute videos directory next to the output file
        videos_dir = os.path.join(os.path.dirname(os.path.abspath(output_path)), "videos")

        # Generate HTML
        print("  Generating HTML report...")
        html = generate_html(test_data, summary_data, attachment_map, title, xcresult_path, videos_dir=videos_dir)

    # Write output
    output_path = os.path.abspath(output_path)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        f.write(html)

    file_size = os.path.getsize(output_path)
    size_str = f"{file_size / 1024 / 1024:.1f} MB" if file_size > 1024 * 1024 else f"{file_size / 1024:.0f} KB"
    print(f"\nReport generated: {output_path} ({size_str})")
    print(f"Open in browser: file://{output_path}")


if __name__ == "__main__":
    main()
