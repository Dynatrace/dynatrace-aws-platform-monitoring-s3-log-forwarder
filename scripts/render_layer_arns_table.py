#!/usr/bin/env python3

# Copyright 2026 Dynatrace LLC
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#      https://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Render the per-region Lambda Layer ARN table for the GitHub release notes.

Reads Mappings.LayerArns from an already-rewritten template.yaml and emits a
markdown table giving the layer ARN for every region and architecture.

The table is sourced from template.yaml rather than from publish_layer.sh's
--arns-output files because those cover only the regions a single run published
to, whereas the template holds the merged result for every region and is the
artifact customers actually deploy.

With --notes the table is upserted into existing release notes between marker
comments, so re-running a release neither appends a second copy nor discards the
notes GitHub generated.
"""

import argparse
import sys

# Sibling script in scripts/; reused so the template parser has one definition.
import update_layer_arns

START_MARKER = "<!-- layer-arns:start -->"
END_MARKER = "<!-- layer-arns:end -->"

# (mapping key in template.yaml, column heading)
ARCH_COLUMNS = (("x86", "x86_64"), ("arm64", "arm64"))
NOT_PUBLISHED = "_not published_"


def read_regions(template_path):
    """Parse the LayerArns mapping out of a template file."""
    text = open(template_path).read()
    lines = text.split("\n")
    if text.endswith("\n"):
        lines.pop()
    start, end = update_layer_arns.find_block(lines)
    return update_layer_arns.parse_regions(lines, start, end)


def render_section(regions):
    """Render the marked-off markdown section for the given regions."""
    if not regions:
        sys.exit("error: no regions found in the LayerArns mapping; refusing to "
                 "publish an empty layer ARN table")

    rows = [
        "| Region | " + " | ".join(label for _, label in ARCH_COLUMNS) + " |",
        "|---" * (1 + len(ARCH_COLUMNS)) + "|",
    ]
    for region in sorted(regions):
        arns = regions[region]
        cells = [f"`{arns[key]}`" if key in arns else NOT_PUBLISHED
                 for key, _ in ARCH_COLUMNS]
        rows.append(f"| `{region}` | " + " | ".join(cells) + " |")

    return "\n".join([
        START_MARKER,
        "",
        "## Lambda Layer ARNs",
        "",
        f"<details><summary>Layer ARNs in this release</summary>",
        "",
        *rows,
        "",
        "</details>",
        "",
        END_MARKER,
    ])


def upsert(notes, section):
    """Replace an existing marked section, or append one, preserving the rest."""
    start = notes.find(START_MARKER)
    end = notes.find(END_MARKER)

    if start != -1 and end != -1 and end > start:
        head = notes[:start].rstrip("\n")
        tail = notes[end + len(END_MARKER):].lstrip("\n")
        parts = [p for p in (head, section, tail) if p]
        return "\n\n".join(parts) + "\n"

    body = notes.strip("\n")
    return (f"{body}\n\n{section}\n" if body else f"{section}\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--template", required=True,
                    help="template.yaml to read Mappings.LayerArns from")
    ap.add_argument("--notes",
                    help="existing release notes to upsert the table into")
    ap.add_argument("--output", help="write here instead of stdout")
    args = ap.parse_args()

    section = render_section(read_regions(args.template))

    if args.notes:
        result = upsert(open(args.notes).read(), section)
    else:
        result = section + "\n"

    if args.output:
        with open(args.output, "w") as fh:
            fh.write(result)
    else:
        sys.stdout.write(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
