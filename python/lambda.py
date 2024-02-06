import anycostoci
import sys
import os
import datetime
import boto3
import s3fs
import oci
import tempfile
from datetime import timedelta
from datetime import datetime

# Call with event data to specify lookback:
# curl -d '{"lookback_months": 1 }' for example.

def __load_oci_config(params_path: str) -> dict:
    client = boto3.client('ssm')
    config = {}

    config['user'] = client.get_parameter(
        Name = params_path + "oci-user")['Parameter']['Value']
    config['key_content'] = client.get_parameter(
        Name = params_path + "oci-key-content",
        WithDecryption = True )['Parameter']['Value']
    config['fingerprint'] = client.get_parameter(
        Name = params_path + "oci-key-fingerprint")['Parameter']['Value']
    config['tenancy'] = client.get_parameter(
        Name = params_path + "oci-tenancy" )['Parameter']['Value']
    config['region'] = client.get_parameter(
        Name = params_path + "oci-region" )['Parameter']['Value']
    oci.config.validate_config(config)
    return config

def anycost(event, context):

    # hydrate the OCI configuration for downloading 
    params_path = os.environ.get('SSM_PARAMETER_STORE_FOLDER_PATH')
    oci_config = __load_oci_config(params_path)

    # hydrate the S3 config
    ssm = boto3.client('ssm')
    cbf_s3_bucket = ssm.get_parameter(Name=params_path+'s3-bucket')['Parameter']['Value']
    cbf_s3_prefix = ssm.get_parameter(Name=params_path+'s3-bucket-prefix')['Parameter']['Value']

    # Check event arguments
    lookback_months = 0
    if 'lookback_months' in event:
        lookback_months = event['lookback_months']
    print(f"Looking back {lookback_months} months ago")
    
    # temp dir management for Lambda temp storage
    temp_dir = tempfile.TemporaryDirectory(dir="/tmp/")
    try: 
        oci_write_dir = os.path.join(temp_dir.name, "oci_cost_files")
        os.makedirs(oci_write_dir, exist_ok=True)
        anycost_drop_dir = os.path.join(temp_dir.name, "anycost_drop")
        os.makedirs(anycost_drop_dir, exist_ok=True)

        anycostoci.download_oci_cost_files(
            lookback_months = lookback_months,
            oci_config = oci_config,
            output_dir = oci_write_dir
        )

        output_drops = anycostoci.build_anycost_drop_from_oci_files(
            lookback_months,
            oci_config,
            oci_cost_files_dir = oci_write_dir,
            output_dir = anycost_drop_dir,
        )

        # output_drops:
        # {'/tmp/tmp425_p9ui/anycost_drop/20230101-20230201/20230130225601'}
        print(output_drops)

        # walk the output_drops and plop them all in the target s3 bucket        
        s3 = s3fs.S3FileSystem()
        for drop in output_drops:
            drop_id       = os.path.basename(drop)
            drop_bdid_dir = os.path.dirname(drop)
            drop_bdid     = os.path.basename(drop_bdid_dir)
            
            # should be /bucket/prefix/20230101-20230201/
            s3_drop_path = os.path.join(cbf_s3_bucket, cbf_s3_prefix, drop_bdid, drop_id + "/")

            # when new month used, didn't create drop_id prefix, it just put the files directly in the bdid prefix
            print(f"Putting dir: {drop} to S3 path {s3_drop_path}")
            s3.put(drop, s3_drop_path, recursive=True)

            # manifest.json
            #should be /tmp/tmp425_p9ui/anycost_drop/20230101-20230201/manifest.json
            manifest_tmp_path = os.path.join(drop_bdid_dir, "manifest.json")
            manifest_s3_path = os.path.join(cbf_s3_bucket, cbf_s3_prefix, drop_bdid, 'manifest.json')
            print(f"Putting {manifest_tmp_path} to S3 path {manifest_s3_path}")
            s3.put_file(manifest_tmp_path, manifest_s3_path)


        # cleanup for next invocation
    finally:
        temp_dir.cleanup()