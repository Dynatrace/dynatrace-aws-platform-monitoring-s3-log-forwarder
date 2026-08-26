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
import io
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

# scripts/ is not on sys.path (test discovery runs from src/), so the module under
# test is loaded by absolute path. Importing it is side-effect free: it only
# defines constants, compiles the regexes and guards main() behind __main__.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
SCRIPT_PATH = os.path.join(REPO_ROOT, "scripts", "update_layer_arns.py")
REAL_TEMPLATE_PATH = os.path.join(REPO_ROOT, "template.yaml")

FIXTURE_TEMPLATE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "test_templates",
    "template_fixture.yaml"
)

_spec = importlib.util.spec_from_file_location("update_layer_arns", SCRIPT_PATH)
update_layer_arns = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(update_layer_arns)


def read_lines(path):
    '''Split a template into lines the same way the module under test does.'''
    text = open(path).read()
    lines = text.split("\n")
    if text.endswith("\n"):
        lines.pop()
    return lines


def parse_template(path):
    '''Return the region -> {arch: arn} mapping parsed out of a template file.'''
    lines = read_lines(path)
    start, end = update_layer_arns.find_block(lines)
    return update_layer_arns.parse_regions(lines, start, end)


def run_main(template_path, arch_key, pairs):
    '''Invoke the script's main() against a template with the given input pairs.'''
    argv = ["update_layer_arns.py", "--template", template_path, "--arch-key", arch_key]
    with patch.object(sys, "argv", argv), \
            patch.object(sys, "stdin", io.StringIO(pairs)):
        return update_layer_arns.main()


class TestUpdateLayerArns(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)

    def copy_to_tmp(self, source):
        '''Copy a template into the temp dir so tests never mutate repo files.'''
        destination = os.path.join(self.tmpdir.name, os.path.basename(source))
        shutil.copyfile(source, destination)
        return destination

    def test_patterns_match_indent_constants(self):
        '''
        The compiled patterns must agree with the named indent widths, so the
        regexes and render() cannot drift apart.
        '''
        self.assertTrue(update_layer_arns.MAP_KEY_RE.match(
            " " * update_layer_arns.MAP_KEY_INDENT + "LayerArns:"))
        self.assertTrue(update_layer_arns.REGION_RE.match(
            " " * update_layer_arns.REGION_INDENT + "us-east-1:"))
        self.assertTrue(update_layer_arns.ARCH_RE.match(
            " " * update_layer_arns.ARCH_INDENT + "x86: arn:aws:lambda:x"))

        # Off-by-one indentation must not match.
        self.assertIsNone(update_layer_arns.MAP_KEY_RE.match(
            " " * (update_layer_arns.MAP_KEY_INDENT + 1) + "LayerArns:"))
        self.assertIsNone(update_layer_arns.REGION_RE.match(
            " " * (update_layer_arns.REGION_INDENT + 1) + "us-east-1:"))

    def test_unknown_arch_key_is_rejected(self):
        '''
        A second-level key outside ARCH_KEYS must be a hard error, not silently
        dropped by render() on rewrite.
        '''
        self.assertIsNone(update_layer_arns.ARCH_RE.match(
            " " * update_layer_arns.ARCH_INDENT + "x64: arn:aws:lambda:x"))

        lines = [
            "Mappings:",
            "  LayerArns:",
            "    us-east-1:",
            "      x86: arn:aws:lambda:us-east-1:1:layer:l:1",
            "      x64: arn:aws:lambda:us-east-1:1:layer:l-x64:7",
            "",
            "Conditions:",
        ]
        start, end = update_layer_arns.find_block(lines)
        with self.assertRaises(SystemExit):
            update_layer_arns.parse_regions(lines, start, end)

    def test_round_trip_is_lossless(self):
        '''
        Writing the existing ARNs straight back must leave the real template.yaml
        byte-identical. Exercises parse + render over every region and both
        architectures, and fails if the template is ever reformatted.
        '''
        original = open(REAL_TEMPLATE_PATH, "rb").read()
        regions = parse_template(REAL_TEMPLATE_PATH)
        self.assertGreater(len(regions), 0, "no regions parsed from template.yaml")

        for arch in update_layer_arns.ARCH_KEYS:
            with self.subTest(arch=arch):
                target = self.copy_to_tmp(REAL_TEMPLATE_PATH)
                pairs = "".join(
                    f"{region}={arns[arch]}\n"
                    for region, arns in regions.items() if arch in arns
                )
                run_main(target, arch, pairs)
                self.assertEqual(open(target, "rb").read(), original)

    def test_single_region_update_changes_one_line(self):
        '''Bumping one region's version must rewrite exactly one line.'''
        target = self.copy_to_tmp(FIXTURE_TEMPLATE_PATH)
        before = read_lines(target)

        new_arn = "arn:aws:lambda:us-east-1:335651422829:layer:test-layer:99"
        run_main(target, "x86", f"us-east-1={new_arn}\n")

        after = read_lines(target)
        self.assertEqual(len(before), len(after))
        differing = [i for i, (b, a) in enumerate(zip(before, after)) if b != a]
        self.assertEqual(len(differing), 1)
        self.assertEqual(after[differing[0]],
                         " " * update_layer_arns.ARCH_INDENT + f"x86: {new_arn}")

        # The other regions and the arm64 entry must be untouched.
        regions = parse_template(target)
        self.assertEqual(regions["us-east-1"]["x86"], new_arn)
        self.assertTrue(regions["us-east-1"]["arm64"].endswith("test-layer-arm64:2"))
        self.assertTrue(regions["eu-west-1"]["x86"].endswith("test-layer:3"))

    def test_new_region_is_inserted_in_sorted_position(self):
        '''
        A region absent from the mapping is added in sorted order, carrying only
        the architecture that was published.
        '''
        target = self.copy_to_tmp(FIXTURE_TEMPLATE_PATH)
        new_arn = "arn:aws:lambda:mx-central-1:335651422829:layer:test-layer:1"
        run_main(target, "x86", f"mx-central-1={new_arn}\n")

        regions = parse_template(target)
        self.assertEqual(regions["mx-central-1"], {"x86": new_arn})
        self.assertEqual(sorted(regions), list(regions),
                         "regions must be emitted in sorted order")
        self.assertIn("mx-central-1", regions)

    def test_blank_line_after_block_is_preserved(self):
        '''
        The blank line separating the mapping from the next top-level key must
        survive; an earlier implementation swallowed it.
        '''
        target = self.copy_to_tmp(FIXTURE_TEMPLATE_PATH)
        run_main(target, "x86",
                 "us-east-1=arn:aws:lambda:us-east-1:335651422829:layer:test-layer:99\n")

        lines = read_lines(target)
        conditions_index = lines.index("Conditions:")
        self.assertEqual(lines[conditions_index - 1], "")
        # The comments above the mapping key must survive too.
        self.assertIn("  # Comments above the mapping key must survive a rewrite.",
                      lines)

    def test_invalid_published_arns_are_rejected(self):
        """
        A malformed ARN, or one contradicting its region key, must abort before
        anything is written rather than land in the template verbatim.
        """
        cases = {
            "not an ARN at all": "not-an-arn-at-all",
            "too few fields": "arn:aws:lambda:us-east-1:335651422829:layer:l",
            "wrong region": "arn:aws:lambda:eu-west-1:335651422829:layer:l:5",
            "wrong partition": "arn:notaws:lambda:us-east-1:335651422829:layer:l:5",
            "wrong service": "arn:aws:s3:us-east-1:335651422829:layer:l:5",
            "wrong resource type": "arn:aws:lambda:us-east-1:335651422829:function:l:5",
            "short account id": "arn:aws:lambda:us-east-1:12345:layer:l:5",
            "non-numeric version": "arn:aws:lambda:us-east-1:335651422829:layer:l:latest",
            "zero version": "arn:aws:lambda:us-east-1:335651422829:layer:l:0",
        }
        for label, arn in cases.items():
            with self.subTest(case=label):
                with self.assertRaises(SystemExit):
                    update_layer_arns.validate_published_arns(
                        {"us-east-1": arn}, "x86")

    def test_arch_suffix_mismatch_is_rejected(self):
        """
        Feeding one architecture's ARNs to the other arch key - the plausible
        CI mistake of crossing the two layer-arns files - must abort.
        """
        x86_arn = "arn:aws:lambda:us-east-1:335651422829:layer:test-layer:4"
        arm64_arn = "arn:aws:lambda:us-east-1:335651422829:layer:test-layer-arm64:4"

        with self.assertRaises(SystemExit):
            update_layer_arns.validate_published_arns({"us-east-1": arm64_arn}, "x86")
        with self.assertRaises(SystemExit):
            update_layer_arns.validate_published_arns({"us-east-1": x86_arn}, "arm64")

        # The matching combinations must pass.
        update_layer_arns.validate_published_arns({"us-east-1": x86_arn}, "x86")
        update_layer_arns.validate_published_arns({"us-east-1": arm64_arn}, "arm64")

    def test_invalid_arns_leave_the_template_untouched(self):
        """Validation must run before any write, not part-way through one."""
        target = self.copy_to_tmp(FIXTURE_TEMPLATE_PATH)
        original = open(target, "rb").read()

        with self.assertRaises(SystemExit):
            run_main(target, "x86", "us-east-1=not-an-arn\n")

        self.assertEqual(open(target, "rb").read(), original)

    def test_real_template_arns_pass_validation(self):
        """
        Guard against false positives: every ARN already committed to
        template.yaml must satisfy the validator for its own architecture.
        """
        regions = parse_template(REAL_TEMPLATE_PATH)
        for arch in update_layer_arns.ARCH_KEYS:
            pairs = {r: a[arch] for r, a in regions.items() if arch in a}
            with self.subTest(arch=arch):
                self.assertGreater(len(pairs), 0)
                update_layer_arns.validate_published_arns(pairs, arch)

    def test_non_commercial_partitions_are_accepted(self):
        """GovCloud and China layer ARNs must not be rejected."""
        update_layer_arns.validate_published_arns(
            {"us-gov-west-1":
                "arn:aws-us-gov:lambda:us-gov-west-1:335651422829:layer:l:5"}, "x86")
        update_layer_arns.validate_published_arns(
            {"cn-north-1":
                "arn:aws-cn:lambda:cn-north-1:335651422829:layer:l:5"}, "x86")

    def test_malformed_pair_is_rejected(self):
        '''A stdin line without '=' must abort rather than be skipped.'''
        with self.assertRaises(SystemExit):
            update_layer_arns.parse_pairs(io.StringIO("garbage-no-equals\n"))

        with self.assertRaises(SystemExit):
            update_layer_arns.parse_pairs(io.StringIO("=arn:aws:lambda:x\n"))

    def test_empty_stdin_leaves_file_unchanged(self):
        '''No published ARNs must be a no-op, not an empty mapping.'''
        target = self.copy_to_tmp(FIXTURE_TEMPLATE_PATH)
        original = open(target, "rb").read()
        run_main(target, "x86", "")
        self.assertEqual(open(target, "rb").read(), original)


if __name__ == '__main__':
    unittest.main()
