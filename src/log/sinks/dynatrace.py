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


import logging
import os
import sys
import json
import gzip
import time
import requests
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
from aws_lambda_powertools.utilities import parameters
from aws_lambda_powertools import Metrics
from aws_lambda_powertools.metrics import MetricUnit
from utils.helpers import ENCODING
from version import get_version

logger = logging.getLogger()

GENERIC_LOGS_INGEST_API_URL_SUFFIX = '/api/aws/s3/v1/logs'

# Related documentation
# https://www.dynatrace.com/support/help/how-to-use-dynatrace/log-monitoring/log-monitoring-limits

DYNATRACE_LOG_INGEST_CONTENT_MARK_TRIMMED = '[TRUNCATED]'
# CloudTrail messages can be up to 256KB!
# https://docs.aws.amazon.com/awscloudtrail/latest/userguide/WhatIsCloudTrail-Limits.html
try:
    DYNATRACE_LOG_INGEST_CONTENT_MAX_LENGTH = int(os.getenv('DYNATRACE_LOG_INGEST_CONTENT_MAX_LENGTH'))    
except (ValueError, TypeError):
    DYNATRACE_LOG_INGEST_CONTENT_MAX_LENGTH = 65536

DYNATRACE_LOG_INGEST_ATTRIBUTE_MAX_LENGTH = 250
DYNATRACE_LOG_INGEST_PAYLOAD_MAX_SIZE = 5242880  # 5MB
DYNATRACE_LOG_INGEST_MAX_RECORD_AGE = 86340  # 1 day
DYNATRACE_LOG_INGEST_MAX_ENTRIES_COUNT = 5000

DYNATRACE_LOG_MESSAGE_MAX_ATTRIBUTES = 50

COMMA_SEPARATOR_LENGTH = 1
LIST_BRACKETS_LENGTH = 2

DYNATRACE_CONNECT_TIMEOUT = 3
DYNATRACE_READ_TIMEOUT = 12

metrics = Metrics()

default_headers = {
    "User-Agent" : f"dynatrace-aws-platform-monitoring-s3-log-forwarder/{get_version()}"
}

class DynatraceSink():
    def __init__(self, dt_url: str, dt_platform_token_parameter: str, verify_ssl: bool = True,
                 token_source: str = 'secretsmanager'):
        self._environment_url = dt_url.rstrip('/')
        self._platform_token_parameter = dt_platform_token_parameter
        self._token_source = token_source
        self._approx_buffered_messages_size = LIST_BRACKETS_LENGTH
        self._messages = []
        self._batch_num = 1
        self._s3_source = ""

        retry_strategy = Retry(
            total = 3,
            status_forcelist = [429, 500, 503],
            allowed_methods =['POST'],
            raise_on_status = False,
            backoff_factor = .5
        )

        adapter = HTTPAdapter(max_retries=retry_strategy)

        self.session = requests.Session()
        self.session.verify = verify_ssl
        self.session.mount("https://", adapter)

    def get_num_of_buffered_messages(self):
        return len(self._messages)

    def get_size_of_buffered_messages(self):
        return self._approx_buffered_messages_size

    def is_empty(self):
        return self.get_num_of_buffered_messages() <= 0

    def get_environment_url(self):
        return self._environment_url

    def set_s3_source(self, bucket: str, key: str):
        self._s3_source = f"{bucket}/{key}"

    def push(self, message: dict):
        # Validate that the message size doesn't reach DT limits. If so,
        # truncate the "content" field.

        self.check_log_message_size_and_truncate(message)

        # Check if we'd be exceeding limits before appending the message
        new_message_size = sys.getsizeof(json.dumps(message).encode(ENCODING))
        new_num_of_buffered_messages = self.get_num_of_buffered_messages() + 1
        new_approx_size_of_buffered_messages = (
                    self._approx_buffered_messages_size + new_message_size + COMMA_SEPARATOR_LENGTH)

        # If we'd exceed limits, flush before buffering
        if ( new_num_of_buffered_messages > DYNATRACE_LOG_INGEST_MAX_ENTRIES_COUNT or
             new_approx_size_of_buffered_messages > DYNATRACE_LOG_INGEST_PAYLOAD_MAX_SIZE ):
            self.flush()
            self._batch_num += 1

        # buffer log messages
        self._messages.append(message)
        self._approx_buffered_messages_size += new_message_size + COMMA_SEPARATOR_LENGTH

    def flush(self):
        if not self.is_empty():
            self.ingest_logs(self._messages, batch_num=self._batch_num,session=self.session)
        self._messages = []
        self._approx_buffered_messages_size = LIST_BRACKETS_LENGTH

    def empty_sink(self):
        self._messages = []
        self._approx_buffered_messages_size = LIST_BRACKETS_LENGTH
        self._batch_num = 1
        self._s3_source = ""

    def check_log_message_size_and_truncate(self, message: dict):
        '''
        Gets a Dynatrace LogMessageJson object. If message size exceeds Dynatrace limit, returns
        truncated message.
        '''
        if len(message['content']) > DYNATRACE_LOG_INGEST_CONTENT_MAX_LENGTH:
            trimmed_length = DYNATRACE_LOG_INGEST_CONTENT_MAX_LENGTH - \
                len(DYNATRACE_LOG_INGEST_CONTENT_MARK_TRIMMED)
            message['content'] = message['content'][0:trimmed_length] + \
                DYNATRACE_LOG_INGEST_CONTENT_MARK_TRIMMED
            metrics.add_metric(name='LogMessagesTrimmed',
                               unit=MetricUnit.Count, value=1)
        return message

    def post_logs(self, dt_url, dt_platform_token, dt_tenant, data,
                  compress=True, session=None):
        '''
        Does an HTTP POST request to the generic logs ingest API. Compresses data by default.
        '''

        if session is None:
            session = requests.Session()

        headers = {}
        headers.update(default_headers)
        headers.update({
            'Authorization': f'Bearer {dt_platform_token}',
            'Content-Type': 'application/json; charset=utf-8',
            'Dt-Tenant': dt_tenant
        })


        request_data = data

        if compress:
            request_data = gzip.compress(data, compresslevel=6)
            headers['Content-Encoding'] = 'gzip'

        try:
            resp = session.post(dt_url, data=request_data, headers=headers,
                                timeout=(DYNATRACE_CONNECT_TIMEOUT, DYNATRACE_READ_TIMEOUT))
        except Exception:
            logger.exception('Error pushing logs to Dynatrace')
            raise

        return resp

    def ingest_logs(self, logs: list, session=None,
                    batch_num: int = -1):
        '''
        POSTs list of messages to the generic log ingress Dynatrace API.
        Creates batches if messages exceed the ingest API limits.
        Returns a list of failed batch numbers.
        '''

        if self._token_source == 'secretsmanager':
            secret = parameters.get_secret(self._platform_token_parameter, max_age=120, transform='json')
            dt_platform_token = secret['dt.platform_token']
        else:
            dt_platform_token = parameters.get_parameter(
                self._platform_token_parameter, max_age=120, decrypt=True)

        tenant_id = extract_tenant_id_from_url(self._environment_url)

        logger.debug('Preparing log batches to post to Dynatrace: %s', tenant_id)

        # Create a session to re-use connections
        if session is None:
            session = self.session

        data = json.dumps(logs).encode(ENCODING)

        # POST to dynatrace
        start_time = time.time()

        # https://github.com/requests/requests-threads
        resp = self.post_logs(self._environment_url + GENERIC_LOGS_INGEST_API_URL_SUFFIX,
                              dt_platform_token, tenant_id, data, session=session)

        if resp.status_code == 204:
            logger.debug('%s: Successfully posted batch %d. Ingested %.2f KB of log data to Dynatrace',
                         tenant_id, batch_num, (len(data) / 1024))
            metrics.add_metric(name='DynatraceHTTP204Success',
                               unit=MetricUnit.Count, value=1)
        elif resp.status_code == 200:
            logger.warning(
                '%s: Parts of batch %s were not successfully posted: %s. Source file: %s',tenant_id, batch_num, resp.text, self._s3_source)
            metrics.add_metric(
                name='DynatraceHTTP200PartialSuccess', unit=MetricUnit.Count, value=1)
        elif resp.status_code == 400:
            logger.warning(
                '%s: Parts of batch %s were not successfully posted: %s. Source file: %s',tenant_id, batch_num, resp.text, self._s3_source)
            metrics.add_metric(
                name='DynatraceHTTP400InvalidLogEntries', unit=MetricUnit.Count, value=1)
        elif resp.status_code == 413:
            logger.error(
                "%s: Batch %d rejected by Dynatrace (payload too large): %s. Source file: %s",
                tenant_id, batch_num, resp.text, self._s3_source)
            metrics.add_metric(name='DynatraceHTTP413PayloadTooLarge', unit=MetricUnit.Count, value=1)
            metrics.add_metric(name='DynatraceHTTPErrors', unit=MetricUnit.Count, value=1)
            raise DynatraceIngestionException
        elif resp.status_code == 429:
            logger.error("%s: Throttled by Dynatrace. Exhausted retry attempts... Source file: %s", tenant_id, self._s3_source)
            metrics.add_metric(name='DynatraceHTTP429Throttled',unit=MetricUnit.Count, value=1)
            metrics.add_metric(name='DynatraceHTTPErrors', unit=MetricUnit.Count, value=1)
            raise DynatraceThrottlingException
        elif resp.status_code == 503:
            logger.error("%s: Usable space limit reached. Exhausted retry attempts... Source file: %s", tenant_id, self._s3_source)
            metrics.add_metric(name='DynatraceHTTP503SpaceLimitReached',unit=MetricUnit.Count, value=1)
            metrics.add_metric(name='DynatraceHTTPErrors', unit=MetricUnit.Count, value=1)
            raise DynatraceThrottlingException
        else:
            logger.error(
                "%s: There was a HTTP %d error posting batch %d to Dynatrace. %s. Source file: %s",
                tenant_id,resp.status_code, batch_num, resp.text, self._s3_source)
            metrics.add_metric(name='DynatraceHTTPErrors',
                               unit=MetricUnit.Count, value=1)
            raise DynatraceIngestionException

        metrics.add_metric(name='UncompressedLogDTPayloadSize',
                           unit=MetricUnit.Bytes, value=sys.getsizeof(data))

        end_time = time.time()
        metrics.add_metric(name='DTIngestionTime',
                           unit=MetricUnit.Seconds, value=(end_time - start_time))


def load_sink() -> 'DynatraceSink':
    '''
    Loads the configured Dynatrace sink. Exactly one of two env vars is set by CloudFormation:
      DYNATRACE_API_KEY_SECRETS_MANAGER — Secrets Manager secret ARN (when DynatraceApiKey or DynatraceApiKeySecretsManagerSecret parameter set)
      DYNATRACE_API_KEY_SSM             — SSM parameter path (when DynatraceApiKeySSMParameter parameter set)
    '''
    verify_ssl = False if os.environ['VERIFY_DT_SSL_CERT'] == "false" else True
    dt_url = os.environ['DYNATRACE_ENV_URL']
    secret_arn = os.environ.get('DYNATRACE_API_KEY_SECRETS_MANAGER')
    if secret_arn:
        return DynatraceSink(dt_url, secret_arn, verify_ssl=verify_ssl, token_source='secretsmanager')
    return DynatraceSink(dt_url, os.environ['DYNATRACE_API_KEY_SSM'], verify_ssl=verify_ssl,
                         token_source='ssm')


def extract_tenant_id_from_url(environment_url: str):
    return environment_url[environment_url.find("//") + 2: environment_url.find(".")]


class DynatraceThrottlingException(Exception):
    pass

class DynatraceIngestionException(Exception):
    pass
