---
name: generating-test-reports
description: Generates beautiful HTML test reports from Xcode .xcresult bundles. Parses test results, exports all attachments (screenshots, videos). Images are embedded as base64; videos are saved as external files alongside the HTML for reliable playback. Use when the user mentions test report, test results, xcresult, review test output, visualize test artifacts, test summary, or wants an HTML report after running xcodebuild tests.
compatibility: Requires macOS with Xcode command-line tools (xcrun xcresulttool). Python 3.9+.
metadata:
  author: antran
  version: "1.1"
---

# Generating Test Reports

Parses `.xcresult` bundles via `xcrun xcresulttool` and produces an HTML file with images embedded as base64 and videos saved as external files in a `videos/` directory alongside the report.

## Quick start

```bash
python3 scripts/generate_report.py <path-to.xcresult> -o report.html -t "My Report"
```

Then: `open report.html`

## Workflow

Copy this checklist and track progress:

```
Report Generation:
- [ ] Step 1: Locate the .xcresult bundle
- [ ] Step 2: Generate the HTML report
- [ ] Step 3: Verify the output
- [ ] Step 4: Open in browser
```

### Step 1: Locate the xcresult bundle

**Have the path already?** Skip to Step 2.

**Need to find it?** Check Derived Data:

```bash
find ~/Library/Developer/Xcode/DerivedData -name "*.xcresult" -maxdepth 5 -type d | head -5
```

**Running tests now?** Use `-resultBundlePath` for a known location:

```bash
xcodebuild test -resultBundlePath ./TestResults.xcresult ...
```

### Step 2: Generate the report

```bash
python3 scripts/generate_report.py ./TestResults.xcresult \
    --output ./test-report.html \
    --title "Build #42 Test Report"
```

| Argument | Required | Description |
|----------|----------|-------------|
| `xcresult` | Yes | Path to the `.xcresult` bundle |
| `--output` / `-o` | No | Output HTML path (default: `<bundle-name>_report.html`) |
| `--title` / `-t` | No | Report title (default: derived from bundle name) |

### Step 3: Verify the output

The script prints a summary after generation. Example output:

```
Parsing test results from: ./TestResults.xcresult
  Fetching test summary... OK (42 tests, 2 devices)
  Fetching test list... OK
  Exporting attachments... OK
  Found 65 attachments across 3 tests (48 images, 17 videos)
  Generating HTML report...

Report generated: ./test-report.html (16.2 MB)
```

If the attachment count is 0 but tests produced screenshots, the bundle may lack attachments. Verify with:

```bash
xcrun xcresulttool export attachments --path ./TestResults.xcresult --output-path /tmp/att-check
ls /tmp/att-check/
```

### Step 4: Open in browser

```bash
open ./test-report.html
```

## Report contents

| Tab | Content |
|-----|---------|
| **Tests** | Filterable table with pass/fail/skip badges, duration, attachment counts |
| **Screenshots** | Gallery of all image attachments with click-to-zoom lightbox |
| **Videos** | Gallery of all video attachments with inline playback controls |
| **Devices** | Cards showing device name, model, OS version, architecture |

The header displays total/passed/failed/skipped counts, pass rate progress bar, total duration, and timestamps.

## Output format

The report is an **HTML file + `videos/` directory**. Images are embedded as base64 inline for portability. Videos are saved as external files in a `videos/` folder next to the HTML for reliable browser playback.

To share: zip the HTML file and `videos/` folder together, or share the containing directory.
