import calendar
import json
import re
import oci
import datetime
from datetime import datetime
from datetime import timedelta
from datetime import date
import dateutil
from dateutil import relativedelta
import sys
import os
import gzip
import pandas

tenancy_id_cache = {}

def __create_or_verify_bdid_folder(start_date: datetime, output_dir: str, drop_id: str):
    # Snap to the first of the month that start_date is in
    first_of_the_month = start_date.replace(day=1)
    # Calculate the last date of that month
    last_date_of_the_month = calendar.monthrange(start_date.year, start_date.month)[1]
    # Make a datetime for that last date. 
    last_of_the_month = start_date.replace(day=last_date_of_the_month)
    # Add 1 day to get the first of the next month
    first_of_next_month = last_of_the_month + timedelta(days=1)

    # Build billing data ID - "YYYYMMDD-YYYMMDD" of 1st of data month to 1st of following month
    bdid_segment_1 = first_of_the_month.date().strftime("%Y%m%d")
    bdid_segment_2 = first_of_next_month.strftime("%Y%m%d")

    billing_data_id = bdid_segment_1 + "-" + bdid_segment_2
    bdid_path = os.path.join(output_dir, billing_data_id)
    drop_path = os.path.join(bdid_path, drop_id)

    if not os.path.exists(drop_path):
        print(f"Creating directory {drop_path}")
        os.makedirs(drop_path, exist_ok = True)

    return drop_path


def __months_lookback(lookback_months: int) -> dict:
    """How many previous months to look back and stop. Returns tuple of <date>, <date>"""

    start_date = datetime.utcnow().date() - dateutil.relativedelta.relativedelta(months=lookback_months)
    start_date = start_date.replace(day=1)

    # end_date = datetime.utcnow().date() - dateutil.relativedelta.relativedelta(months=1)
    last_day_of_the_month = calendar.monthrange(start_date.year, start_date.month)[1]
    end_date = start_date.replace(day=last_day_of_the_month)

    print(f"Eval dates: {start_date} to {end_date}")
    return start_date, end_date

def __tenancy_name_lookup(tenancy_id: str, oci_config) -> str:
    """Look up a tenancy name by ID, caching the result"""
    # print(f"Entering tenancy name lookup for ID {tenancy_id}")
    tenancy_name = tenancy_id_cache.get(tenancy_id)
    if tenancy_name != None:
        # print(f"Found tenancy name {tenancy_name}")
        return tenancy_name
    
    try:
        oci.config.validate_config(oci_config)
        iam = oci.identity.IdentityClient(oci_config)
        # print(f"Tenant ID {tenancy_id} was uncached, making API call...")
        get_tenancy_response = iam.get_tenancy(tenancy_id)
        tenancy_name = get_tenancy_response.data.name
        tenancy_id_cache[tenancy_id] = tenancy_name
        # print(f"Tenant ID {tenancy_id} lookup success, name was {tenancy_name}")
    except oci.exceptions.ServiceError:
        # print(f"Tenant ID {tenancy_id} lookup failed, setting empty")
        tenancy_name = ""
        tenancy_id_cache[tenancy_id] = tenancy_name

    return tenancy_name

# 0 lookback starts from first of current month to today
# 1 lookback starts from 1st of previous month to last day of previous month
# 2 lookback starts from 1st of next-previous month to last day of that month
def download_oci_cost_files(lookback_months: int, oci_config, output_dir = '/tmp/' ) -> slice:
    """Download OCI cost reports between start_date and end_date. Returns slice of downloaded filenames on success."""
    oci.config.validate_config(oci_config)

    object_storage = oci.object_storage.ObjectStorageClient(oci_config)

    start_date, end_date = __months_lookback(lookback_months)
    # Extend the end date since the last day of the month reports in the
    # following month.
    report_end_date = end_date + timedelta(days=3)

    # TODO: the point of pagination is to make repeated calls. Push this paginating into the fetch/comparison loop function
    report_bucket_objects = oci.pagination.list_call_get_all_results(
                            object_storage.list_objects,
                            'bling',
                            oci_config['tenancy'],
                            fields="name,timeCreated,size",
                            prefix="reports/cost-csv"
                            )

    downloaded_reports = []
    for o in report_bucket_objects.data.objects:
        # print(f"Report Created: {o.time_created.date()} Earliest date: {datetime.strptime('2022-01-01', '%Y-%m-%d').date()}")
        if (o.time_created.date() >= start_date and
            o.time_created.date() <= report_end_date ):
            this_report = object_storage.get_object('bling', oci_config['tenancy'], o.name)
            filename_path = os.path.join(output_dir, o.time_created.strftime("%Y%m%d%H%M%S%Z") + ".csv.gz")
            with open(filename_path, "wb", ) as f:
                for chunk in this_report.data.raw.stream(1024 * 1024, decode_content=False):
                    f.write(chunk)
            downloaded_reports.append(filename_path)
            print(f"File {filename_path} Downloaded - created {o.time_created}")


    return downloaded_reports

def build_anycost_drop_from_oci_files(lookback_months: int,
                                      oci_config,
                                      oci_cost_files_dir = '/tmp/', 
                                      output_dir = '/tmp/anycost_drop/') -> slice:
    """Take a directory of gzipped OCI cost reports and build an AnyCost drop out of them.

    Evaluates the files in oci_cost_files_dir to see their begin/end dates.
    Creates a CBF-drop-formatted directory and file structure in output_dir.
    Creates a CBF manifest.json pointing to the new files.

    Returns a set of paths to created billing data ID folders under output_dir
    """
    oci.config.validate_config(oci_config)
    # CBF drop folder structure is like:
    # output_dir/<billing_data_id>/<drop_id>/<data_file>
    # Ex:
    # output_dir/20220101-20220201/20220128000000Z/data_file[0...N].csv.gz
    # output_dir/20220101-20220201/manifest.json

    start_date, end_date = __months_lookback(lookback_months)

    drop_id = datetime.utcnow().strftime("%Y%m%d%H%M%S%Z")
    drop_paths = set()

    for root, dirs, cost_files in os.walk(oci_cost_files_dir):
        # It would be swell if this yielded the files in order. 
        # The filenames are ordered numbers and we could display progress
        for cost_file in cost_files: 
            if not re.match(".*\.csv\.gz$", cost_file):
                continue

            with gzip.open(os.path.join(root, cost_file), 'rb') as f:
                print(f"Processing file {root}/{cost_file}...")
                try:
                    oci_cost = pandas.read_csv(f)
                except pandas.errors.EmptyDataError:
                    print(f"No rows read from file {root}/{cost_file}")
                    
                # Start building the CBF formatted frame
                cbf_frame = pandas.DataFrame([])


                cbf_frame.insert(0, 'lineitem/id', oci_cost.loc[:, 'lineItem/referenceNo'])
                # AFAICT all cost types in OCI are 'Usage', with the possible
                # exception of 'Adjustment's for rows with isCorrection=True.
                # Depending on how corrections are handled we may not need
                # to show that.
                cbf_frame.insert(1, 'lineitem/type', 'Usage')
                cbf_frame.insert(2, 'lineitem/description', oci_cost.loc[:, 'product/Description'])
                cbf_frame.insert(3, 'time/usage_start', oci_cost.loc[:, 'lineItem/intervalUsageStart'])
                cbf_frame.insert(4, 'time/usage_end', oci_cost.loc[:, 'lineItem/intervalUsageEnd'])
                cbf_frame.insert(5, 'resource/id', oci_cost.loc[:, 'product/resourceId'])
                cbf_frame.insert(6, 'resource/service', oci_cost.loc[:, 'product/service'])
                cbf_frame.insert(7, 'resource/account', oci_cost.loc[:, 'lineItem/tenantId'])
                cbf_frame.insert(8, 'resource/region', oci_cost.loc[:, 'product/region'])
                cbf_frame.insert(9, 'action/account', oci_cost.loc[:, 'lineItem/tenantId'])
                cbf_frame.insert(10, 'usage/amount', oci_cost.loc[:, 'usage/billedQuantity'])
                cbf_frame.insert(11, 'cost/cost', oci_cost.loc[:, 'cost/myCost'])

                # Resource Tags
                for c in oci_cost.columns:
                    match = re.match('^tags\/(?P<tag_key>.*)', c)
                    if match:
                        oci_tag_key = match.group('tag_key')
                        oci_tag_key_cleaned = re.sub("[^a-zA-Z0-9\_\.\:\+\@\=\-\/]+", '', oci_tag_key)

                        if len(oci_tag_key) != len(oci_tag_key_cleaned):
                            print("Warning: Some characters were stripped from OCI tag column.")
                            print(f"Column '{oci_tag_key}' contained invalid characters.")

                        tag_column = "resource/tag:" + oci_tag_key_cleaned
                        cbf_frame.insert(len(cbf_frame.columns), tag_column, oci_cost.loc[:, c])

                # Synthesized tag for account name
                cbf_frame.insert(len(cbf_frame.columns), 'resource/tag:oci_tenancy_name', oci_cost.loc[:, 'lineItem/tenantId'])
                cbf_frame['resource/tag:oci_tenancy_name'] = cbf_frame['resource/tag:oci_tenancy_name'].map(lambda t:__tenancy_name_lookup(t, oci_config))

                # This section prunes the CBF frames to contain only rows with
                # usage_start dates within the BDID boundary.

                # Format the usage timestamps so we can parse them
                cbf_frame['time/usage_start'] = pandas.to_datetime(cbf_frame['time/usage_start'], cache=True)
                cbf_frame['time/usage_end']   = pandas.to_datetime(cbf_frame['time/usage_end'], cache=True)

                # Create new date-only timestamp columns so we can look at those for pruning
                # note the .dt property refers to the datetime object inside the column 
                cbf_frame['time/usage_start_date'] = cbf_frame['time/usage_start'].dt.date
                cbf_frame['time/usage_end_date']   = cbf_frame['time/usage_end'].dt.date

                # CBF treats all usage with start dates within the BDID window
                # as valid for that window. So we look at the start date of
                # every row to see whether it belongs within the window.
                if start_date: # conditional here since @start_date is inside the string
                    cbf_frame.query('`time/usage_start_date` >= @start_date', inplace=True)
                
                if end_date:
                    cbf_frame.query('`time/usage_start_date` <= @end_date', inplace=True)
                
                # Finally, let's drop the _date columns since they don't belong
                # in the output.
                cbf_frame.drop(columns=['time/usage_start_date', 'time/usage_end_date'], inplace=True)

                # Dump to disk, assuming we have any rows left
                if len(cbf_frame) > 0:
                    drop_path = __create_or_verify_bdid_folder(cbf_frame.head(1).iat[0,3], output_dir, drop_id)
                    cbf_file_path = os.path.join(output_dir, drop_path, os.path.basename(cost_file))
                    print(f"Writing CBF file to {cbf_file_path}")
                    cbf_frame.to_csv(cbf_file_path, index=False)
                    drop_paths.add(drop_path)
                else:
                    print(f"No rows remaining after date window prune in file {cost_file}")

    # Emit manifest pointing at our current drop.
    # There should only be 1, despite the for statement. 
    for d in drop_paths:
        manifest = {
            "version": "1.0.0",
            "current_drop_id": drop_id
        }

        with open(os.path.join(os.path.dirname(d), "manifest.json"), 'w') as f:
            json.dump(manifest, f)

    return drop_paths
