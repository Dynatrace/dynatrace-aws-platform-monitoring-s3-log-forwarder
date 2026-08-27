# Copyright 2026 Dynatrace LLC

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#      https://www.apache.org/licenses/LICENSE-2.0

#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.

import importlib.util
import os
import sys
import unittest

# scripts/ is not on sys.path (discovery runs from src/), so the module under test
# is loaded by absolute path. Its own directory is prepended to sys.path first so
# that its `import update_layer_arns` sibling import resolves, exactly as it does
# when the script is run directly.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
SCRIPTS_DIR = os.path.join(REPO_ROOT, "scripts")
SCRIPT_PATH = os.path.join(SCRIPTS_DIR, "render_layer_arns_table.py")
REAL_TEMPLATE_PATH = os.path.join(REPO_ROOT, "template.yaml")

if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

_spec = importlib.util.spec_from_file_location("render_layer_arns_table", SCRIPT_PATH)
render_layer_arns_table = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(render_layer_arns_table)

GENERATED_NOTES = (
    "## What's Changed\n"
    "\n"
    "* Some change by @someone in #123\n"
    "\n"
    "**Full Changelog**: https://github.com/Dynatrace/repo/compare/v1.0.0...v1.1.0\n"
)


class TestRenderLayerArnsTable(unittest.TestCase):

    def setUp(self):
        self.regions = render_layer_arns_table.read_regions(REAL_TEMPLATE_PATH)
        self.section = render_layer_arns_table.render_section(self.regions)

    def test_table_covers_every_region_in_the_template(self):
        '''Every region in the mapping must appear as a row, with both arches.'''
        self.assertGreater(len(self.regions), 0)
        for region, arns in self.regions.items():
            self.assertIn(f"| `{region}` |", self.section)
            for arn in arns.values():
                self.assertIn(f"`{arn}`", self.section)

        row_count = self.section.count("\n| `")
        self.assertEqual(row_count, len(self.regions))

    def test_missing_architecture_is_marked_not_published(self):
        '''A region published for only one arch must not render a blank cell.'''
        section = render_layer_arns_table.render_section({
            "eu-west-1": {"x86": "arn:aws:lambda:eu-west-1:1:layer:l:1"}
        })
        self.assertIn(render_layer_arns_table.NOT_PUBLISHED, section)

    def test_empty_mapping_is_refused(self):
        '''An empty mapping must abort rather than publish an empty table.'''
        with self.assertRaises(SystemExit):
            render_layer_arns_table.render_section({})

    def test_upsert_appends_and_preserves_existing_notes(self):
        '''GitHub's generated notes must survive the first insertion.'''
        result = render_layer_arns_table.upsert(GENERATED_NOTES, self.section)
        self.assertIn("**Full Changelog**", result)
        self.assertIn("## What's Changed", result)
        self.assertIn(render_layer_arns_table.START_MARKER, result)
        self.assertIn(render_layer_arns_table.END_MARKER, result)

    def test_upsert_is_idempotent(self):
        '''
        A workflow re-run must replace the table, not append a second copy.
        '''
        once = render_layer_arns_table.upsert(GENERATED_NOTES, self.section)
        twice = render_layer_arns_table.upsert(once, self.section)
        self.assertEqual(once, twice)
        self.assertEqual(twice.count(render_layer_arns_table.START_MARKER), 1)
        self.assertEqual(twice.count(render_layer_arns_table.END_MARKER), 1)

    def test_upsert_replaces_a_stale_table(self):
        '''A previous release's ARNs must be replaced, not accumulated.'''
        stale = render_layer_arns_table.render_section({
            "us-east-1": {
                "x86": "arn:aws:lambda:us-east-1:335651422829:layer:old:1",
                "arm64": "arn:aws:lambda:us-east-1:335651422829:layer:old-arm64:1",
            }
        })
        notes = render_layer_arns_table.upsert(GENERATED_NOTES, stale)
        self.assertIn("layer:old:1", notes)

        refreshed = render_layer_arns_table.upsert(notes, self.section)
        self.assertNotIn("layer:old:1", refreshed)
        self.assertIn("**Full Changelog**", refreshed)
        self.assertEqual(refreshed.count(render_layer_arns_table.START_MARKER), 1)

    def test_upsert_into_empty_notes(self):
        '''A release with no notes yet must still get a clean table.'''
        result = render_layer_arns_table.upsert("", self.section)
        self.assertTrue(result.startswith(render_layer_arns_table.START_MARKER))
        self.assertTrue(result.endswith("\n"))


if __name__ == '__main__':
    unittest.main()
