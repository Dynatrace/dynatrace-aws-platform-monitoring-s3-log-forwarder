# Copyright 2022 Dynatrace LLC

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#      https://www.apache.org/licenses/LICENSE-2.0

#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.

import unittest
from unittest.mock import patch
import os

os.environ['DEPLOYMENT_NAME'] = 'test'

from log.forwarding import log_forwarding_rules
from utils import aws_appconfig_extension_helpers as aws_appconfig_helpers

TEST_FORWARDING_RULES_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "test_rules"
)

class TestLoadLogForwardingRules(unittest.TestCase):

    def test_load_local_test_rules_folder(self):
        '''
        Test we can load a set of forwarding rules files from disk, including handling invalid files and invalid rules.
        (Legacy format)
        '''

        number_of_s3_buckets = 2
        rules_per_bucket = {
            "my_test_bucket1": [ "Send CloudTrail and Elastic Load Balancing logs to Dynatrace",
                                 "Send My App logs",
                                 "Test_logs"],
            "my_test_bucket2": [ "Send Elastic Load Balancing logs to Dynatrace Prod instance",
                                 "Send CloudTrail logs to Security Dynatrace instance"]
            }
        
        os.environ['LOG_FORWARDING_RULES_PATH'] = TEST_FORWARDING_RULES_PATH
        forwarding_rules, _ = log_forwarding_rules.load_forwarding_rules_from_local_folder()
        
        self.assertTrue((len(forwarding_rules)==number_of_s3_buckets))

        for k,v in forwarding_rules.items():
            if k in rules_per_bucket:
                for i in rules_per_bucket[k]:
                    self.assertTrue(i in v.keys())
    
    def test_load_local_test_rules_file(self):
        '''
        Test we can load a set of forwarding rules files from disk, including handling invalid files and invalid rules.
        (single file format)
        '''

        os.environ["LOG_FORWARDING_RULES_FILE"] = TEST_FORWARDING_RULES_PATH + "/log-forwarding-rules.yaml"

        number_of_s3_buckets = 2
        rules_per_bucket = {
            "my_test_bucket1": [ "Send CloudTrail and Elastic Load Balancing logs to Dynatrace",
                                 "Send My App logs",
                                 "Test_logs"],
            "my_test_bucket2": [ "Send Elastic Load Balancing logs to Dynatrace Prod instance",
                                 "Send CloudTrail logs to Security Dynatrace instance"]
            }

        forwarding_rules, _ = log_forwarding_rules.load_forwarding_rules_from_local_file()
        self.assertTrue((len(forwarding_rules)==number_of_s3_buckets))

        for k,v in forwarding_rules.items():
            if k in rules_per_bucket:
                for i in rules_per_bucket[k]:
                    self.assertTrue(i in v.keys())


    @patch("log.forwarding.log_forwarding_rules.load_forwarding_rules_from_local_file")
    @patch("log.forwarding.log_forwarding_rules.load_forwarding_rules_from_aws_appconfig")
    def test_appconfig_error_at_cold_start_falls_back_to_local_defaults(
            self, mock_appconfig, mock_local):
        mock_appconfig.side_effect = aws_appconfig_helpers.ErrorAccessingAppConfig
        mock_local.return_value = ({"default": {}}, 0)

        os.environ["LOG_FORWARDER_CONFIGURATION_LOCATION"] = "aws-appconfig"
        try:
            with self.assertLogs(level="WARNING") as cm:
                rules, version = log_forwarding_rules.load()
        finally:
            del os.environ["LOG_FORWARDER_CONFIGURATION_LOCATION"]

        mock_local.assert_called_once()
        self.assertEqual(rules, {"default": {}})
        self.assertTrue(any("cold start" in msg for msg in cm.output))


if __name__ == '__main__':
    unittest.main()