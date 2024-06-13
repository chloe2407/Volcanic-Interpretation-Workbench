#!/usr/bin/python3
"""
Volcano InSAR Interpretation Workbench

SPDX-License-Identifier: MIT

Copyright (C) 2021-2023 Government of Canada

Authors:
  - Drew Rotheram <drew.rotheram-clarke@nrcan-rncan.gc.ca>
"""
import argparse
import boto3

from ..app.data_utils import get_config_params


def main():
    '''Main function, create SQS job for pair of
    SLC images for a given a site and beam'''
    args = parse_args()
    config = get_config_params()

    # Create SQS client
    sqs = boto3.client('sqs', region_name='ca-central-1')

    queue_url = config['AWS_INSAR_PROCESS_QUEUE']
    message_attributes = {
            'referenceDate': {
                'DataType': 'String',
                'StringValue': f'{args.startDate}'
            },
            'pairDate': {
                'DataType': 'String',
                'StringValue': f'{args.endDate}'
            },
            'site': {
                'DataType': 'String',
                'StringValue': f'{args.site}'
            },
            'beam': {
                'DataType': 'String',
                'StringValue': f'{args.beam}'
            }
        }
    # Send message to SQS queue
    response = sqs.send_message(
        QueueUrl=queue_url,
        DelaySeconds=10,
        MessageAttributes=message_attributes,
        MessageBody=(
            'This is a message indicating which InSAR pairs \
            should be generated by a call to to the duap InSAR Processor'
        )
    )

    return response


def parse_args():
    """
    Parse command line arguments
    """
    parser = argparse.ArgumentParser(description=("Average Coherence across cc"
                                                  "image and output to list"))
    parser.add_argument("--site",
                        type=str,
                        help='Volcanic Site Name',
                        required=True)
    parser.add_argument("--beam",
                        type=str,
                        help="RCM Beam Mode",
                        required=True)
    parser.add_argument("--startDate",
                        type=str,
                        help="First RCM Image Date for pair",
                        required=True)
    parser.add_argument("--endDate",
                        type=str,
                        help="First RCM Image Date for pair",
                        required=True)
    args = parser.parse_args()

    return args


if __name__ == '__main__':
    main()
