#!/usr/bin/env python3.9

import argparse
import json
import oci
import boto3
import sys
import os
import gzip
from datetime import datetime
from datetime import date
from datetime import timedelta
import calendar
import pandas
import tempfile
import anycostoci

parser = argparse.ArgumentParser()

# AnyCost side configuration, for writing to s3
parser.add_argument("-aki", "--access-key-id")
parser.add_argument("-sak", "--secret-access-key")
parser.add_argument("-b", "--anycost-s3-bucket")

# OCI side configuration, where is my config file
# Config should contain user OCID, tenancy OCID, and keyfile location
parser.add_argument("-o", "--oci-config-file")

# Temp dir stores the OCI cost files, output is the actual drop.
parser.add_argument("-t", "--temp-dir", default="/tmp/")
parser.add_argument("-d", "--output-dir", default="/tmp/anycost_drop")

# Months of history to evaluate and store in AnyCost drop
parser.add_argument("-m", "--lookback-months", default=1, type=int)

args = parser.parse_args()

print(f"Args given: {args}")

# temp_dir = tempfile.TemporaryDirectory(dir=args.temp_dir)
temp_dir = '/tmp/'

# Filesystem sanity check
try:
  oci_write_dir = os.path.join(temp_dir, "oci_cost_files")
  os.makedirs(oci_write_dir, exist_ok=True)
  anycost_drop_dir = args.output_dir
  os.makedirs(anycost_drop_dir)
except FileExistsError as fee:
  print(f"Path exists: {anycost_drop_dir}")
  exit(1)

oci_file = ""
if args.oci_config_file == None:
    oci_file = oci.config.DEFAULT_LOCATION
else:
    oci_file = args.oci_config_file

# Hydrate OCI config and download --lookback-months worth of cost files

oci_config = oci.config.from_file(oci_file, oci.config.DEFAULT_PROFILE)
print(f"OCI Config: {oci_config}")

downloaded_reports = anycostoci.download_oci_cost_files(
                        args.lookback_months, 
                        oci_config = oci_config,
                        output_dir = oci_write_dir)

output_paths = anycostoci.build_anycost_drop_from_oci_files(
  args.lookback_months, 
  oci_cost_files_dir = oci_write_dir, 
  output_dir = anycost_drop_dir
)

print("Created drops in:")
print(output_paths)