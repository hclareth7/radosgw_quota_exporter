
import time
import requests
import json
import argparse
import logging
import os
import shlex
import subprocess
from awsauth import S3Auth
from prometheus_client import start_http_server
from prometheus_client.core import GaugeMetricFamily, CounterMetricFamily, REGISTRY

logging.basicConfig(level=logging.DEBUG)
DEBUG = int(os.environ.get('DEBUG', '0'))


class RADOSGWQUOTACollector(object):

    def __init__(self, access_key, secret_key, host, port=6780):
        super(RADOSGWQUOTACollector, self).__init__()
        self.access_key = access_key
        self.secret_key = secret_key
        self.host = host
        self.port = port
        self.rgwadmin = None

    def collect(self):
        self._set_up_metrics()
        projects = self._get_users_ids()
        self._get_metrics(projects)

        for metric in self._prometheus_metrics.values():
            yield metric

    def _request_data(self, query, args=None):
        url = "{0}/{1}/?format=json&{2}".format(
            self.host, query, args)
        try:
            response = requests.get(url, auth=S3Auth(self.access_key,
                                                     self.secret_key,
                                                     "{0}".format(self.host)))
            if response.status_code == requests.codes.ok:
                if DEBUG:
                    print(response)

                return response.json()
            else:
                # Usage caps absent or wrong admin entry
                print("Request error [{0}]: {1}".format(
                    response.status_code, response.content.decode('utf-8')))
                return
        # DNS, connection errors, etc
        except requests.exceptions.RequestException as e:
            print("Request error: {0}".format(e))
            return

    def _set_up_metrics(self):
        self._prometheus_metrics = {
            'percent_quota_utilized':
            GaugeMetricFamily('radosgw_percent_quota_utilized',
                              'Percent of radosgw quota utilized',
                              labels=["project_name", "project_id", "project_quota"])
        }

    def _get_metrics(self, projects_list):
        for project in projects_list:
            project_quota = self._get_quota_by_project(project)
            if project_quota > 0:
                user = self._get_user_info(project)
                if user is not None:
                    project_name = user['display_name']
                    project_id = user['user_id']
                    used_size = user['stats']['size_actual']
                    used_size_porcent = (used_size*100)/project_quota
                    self._prometheus_metrics['percent_quota_utilized'].add_metric([str(project_name),
                                                                                   str(project_id),
                                                                                   str(project_quota)],
                                                                                  used_size_porcent)

    def _get_users_ids(self):
        query = 'admin/metadata/user'
        users = self._request_data(query=query)
        return users

    def _get_quota_by_project(self, project):
        query = 'admin/user'
        args = '&quota&uid={0}&quota-type=user'.format(project)
        quota = self._request_data(query=query, args=args)
        return quota['max_size']

    def _get_user_info(self, project):
        query = 'admin/user'
        args = 'stats=True&uid={0}'.format(project)
        user = self._request_data(query=query, args=args)
        return user

def parse_args():
    parser = argparse.ArgumentParser(
        description='RADOSGW address and local binding port as well as \
        S3 access_key and secret_key'
    )
    parser.add_argument(
        '-H', '--host',
        required=True,
        help='Server IP for the RADOSGW api (example: 10.161.70.13 )',
        default=os.environ.get('RADOSGW_SERVER', '10.161.70.13')
    )

    parser.add_argument(
        '-a', '--access_key',
        required=True,
        help='S3 access key',
        default=os.environ.get('ACCESS_KEY', 'NA')
    )
    parser.add_argument(
        '-s', '--secret_key',
        required=True,
        help='S3 secrest key',
        default=os.environ.get('SECRET_KEY', 'NA')
    )
    parser.add_argument(
        '-p', '--port',
        required=False,
        type=int,
        help='Port to listen',
        default=int(os.environ.get('VIRTUAL_PORT', 9247))
    )
    return parser.parse_args()

def main():
    try:
        args = parse_args()
        REGISTRY.register(RADOSGWQUOTACollector(host=args.host,
                                                access_key=args.access_key,
                                                secret_key=args.secret_key)
                          )
        start_http_server(args.port)
        print("Polling {0}. Serving at port: {1}".format('0.0.0.0', args.port))
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nInterrupted")
        exit(0)

if __name__ == "__main__":
    main()

