# CloudZero OCI AnyCost Adaptor

[![Contributor Covenant](https://img.shields.io/badge/Contributor%20Covenant-2.1-4baaaa.svg)](CODE-OF-CONDUCT.md)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
![GitHub release](https://img.shields.io/github/release/cloudzero/template-cloudzero-open-source.svg)

This adaptor imports Oracle Cloud Infrastructure (OCI) [cost and usage data](https://docs.oracle.com/en-us/iaas/Content/Billing/Concepts/usagereportsoverview.htm) into CloudZero via the [AnyCost API](https://docs.cloudzero.com/docs/anycost). Users of OCI may run it to view their cloud costs inside CloudZero.

While somewhat immature, it has been in production use with CloudZero customers for many months, and is still maintained as of December 2023.

Requirements:

* Oracle Cloud account with access to:
  * Cost and Usage Report Object Storage bucket

* AWS account with access to:
  * S3 Bucket
  * Systems Manager
  * Lambda runtime
  * Elastic Container Registry

* Docker container build chain, on your laptop or otherwise

## Table of Contents

TODO: Make sure this is updated based on the sections included:

* [Documentation](#documentation)
* [Setup](#setup)
* [Contributing](#contributing)
* [Support + Feedback](#support--feedback)
* [Vulnerability Reporting](#vulnerability-reporting)
* [What is CloudZero?](#what-is-cloudzero)
* [License](#license)

## Documentation

### Theory of Operation

This is packaged as a Python library that is run via either the CLI or an AWS Lambda container. CLI usage is primarily for testing and proof of concept, the expectation is that scheduled production runs occur in Lambda.

While it may seem odd to run an Oracle cost reporting tool in AWS, the CloudZero [AnyCost interface](https://docs.cloudzero.com/docs/anycost) requires input files in an S3 bucket, so AWS resources are needed to use that interface at all. The Lambda component is a small addition.

### Background Reading

You should be familiar with the CloudZero AnyCost Adaptor integration concepts. Further reading is here:

* [AnyCost](https://docs.cloudzero.com/docs/anycost)
* [Connecting Custom Data from AnyCost Adaptors](https://docs.cloudzero.com/docs/connections-custom)

AWS [S3 buckets](https://docs.aws.amazon.com/s3/), [IAM roles](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles.html), and [Lambda container execution](https://docs.aws.amazon.com/lambda/latest/dg/images-create.html) are also utilized.

## Setup

### CLI Setup

Prerequisites:

* Python 3.9
* 3rd party Python libraries: oci, pandas

It is best to get started locally to prove the concept. The CLI interface is designed to fetch OCI billing data from their object storage, convert it to the AnyCost CBF format, and store the results locally for evaluation.

To that end, you'll need a working `oci` application in your terminal. You can get this from the [oci-cli project](https://github.com/oracle/oci-cli). User permissions to download cost data are also required, see the [OCI CUR Overview](https://docs.oracle.com/en-us/iaas/Content/Billing/Tasks/download-cost-usage-report.htm) page for more. You should set up your credentials locally so that the following command works from your shell:

```bash
oci os object list --namespace-name bling --bucket-name <your-tenancy-ocid>
```

Usually this means configuring the file `~/.oci/config` with your user, fingerprint, key_file, region and tenancy as appropriate for your user. You'll need this file in the next step.

You can use the traditional `pip install -r requirements.txt` to get the pip modules installed. Note that the script requests `python3.9` (and probably pip3.9) specifically since that's what Lambda has available, you may need to symlink the binary on your system if you're not using mac homebrew.

Once your Python environment is sorted, a naive run of the CLI should produce output similar to the following:

```text
$ python3.9 cli.py
Args given: Namespace(oci_config_file=None, temp_dir='/tmp/', output_dir='/tmp/anycost_drop', lookback_months=1)
OCI Config: {'log_requests': False, 'additional_user_agent': '', 'pass_phrase': None, 'user': <your-user-ocid>, 'fingerprint': <your-key-fingerprint>, 'key_file': '/Users/<your_user>/.oci/oci_api_key.pem', 'tenancy': <your-user-tenancy>, 'region': 'us-ashburn-1'}
Eval dates: 2023-12-01 to 2023-12-31
File /tmp/oci_cost_files/20231201022804UTC.csv.gz Downloaded - created 2023-12-01 02:28:04.153000+00:00
...
```

By default, the current month of data is downloaded to `/tmp/oci_cost_files/`, processed, and placed in `/tmp/anycost_drop/`. On completion of the run, the `oci_cost_files` will be deletd, and the `anycost_drop` remains. If you send SIGINT, execution will stop and all files left in place as they were at the time of the signal.

This behavior is especially useful for testing your authentication and access. You may manually inspect the output to confirm that it has the data you expect, however no built in behavior to send to S3 for CloudZero's consumption is present. The output could be manually uploaded to S3 and CloudZero configured to look for it, but this is left as an exercise for the user.

### Lambda Setup

The AWS Lambda configuration for this tool runs in the container style. You should be familiar with deploying these images, see the AWS [Working with Lambda container images](https://docs.aws.amazon.com/lambda/latest/dg/images-create.html) documentation for more.

The Dockerfile for the container is in the `python/` directory. You can build it with a simple `docker build .`, or use your container toolchain as desired. What is important is that the completed image be pushed to an ECR repository that Lambda can pull images from, as detailed [here](https://docs.aws.amazon.com/lambda/latest/dg/images-create.html#gettingstarted-images-permissions). When creating the function, you'll specify an image URI that must be the ECR repository address and a tag.

The function must assume a role that has access to the S3 output bucket you'll use. This means that its role must have suitable bucket object read and write permissions in IAM. Deployments vary here; S3 knowledge is required to grant this, but the script generally just creates and lists objects.

The Lambda container has some configuration data required for fetching the OCI cost files. This is a way to represent the OCI user authentication data in a way that the function can consume.

The following resources are required:

#### Environment variables

* `SSM_PARAMETER_STORE_FOLDER_PATH`: The path prefix where the AWS Systems Manager parameter values will be stored. Something like `'/oci-cost-adapter/`, but you can use whatever you want. What's important is that the SSM parameters below be located at that path, like `/oci-cost-adapter/oci-user`, `/oci-cost-adapter/oci-tenancy`, and so on.

#### AWS SSM Parameters

Values for these parameters will be found in the OCI CLI credentials, typically located at `~/.oci/config`. You can use those values directly for the user that you would like to have the Lambda authenticate as.

* `oci-user`
* `oci-key-fingerprint`
* `oci-tenancy`
* `oci-region`
* `oci-key-content` - This value _must_ be encrypted, as it is the entire private key for the authenticating user. The content for this parameter should be the body of the `key_file` in the OCI config.

These parameters set up the AnyCost S3 output:

* `s3-bucket` - Set the output bucket for the CBF drop files. For more details on this setup, see [Connecting Custom Data from AnyCost Adaptors](https://docs.cloudzero.com/docs/connections-custom).
* `s3-bucket-prefix` - This will map to the `root_path` in the CBF drop, as described in the [CBF File Drop Specs](https://docs.cloudzero.com/docs/anycost-cbf-drop-specs).

#### Event Parameters

* `lookback_months` - This may be passed as a JSON object key, similar to `{"lookback_months": 2}`, in the Lambda event parameters. If omitted or invalid, `0` will be used, which will fetch the current month. Typically you would invoke it this way every hour or so.

**Note:** OCI continues to post CUR data for a given month 1-3 days into the following month. For complete accuracy, you should run the Lambda with `{"lookback_months": 1}` on or around the 3rd of each month, in addition to any other invocations. This will pick up any cost files posted after the month ends.

For example, cost data files for January will continue to flow into the OCI object storage up through about February 2nd. If this script is only ever run with `{"lookback_months": 0}`, cost data for January that was posted in February will not be processed and never make it to S3. CloudZero will show cost data that is inaccurately low for the last day of the month unless you also perform this "cleanup" run.

Additional runs that pick up no new data do not affect accuracy, they merely incur processing cost.

### Output Notes

OCI billing output doesn't necessarily map cleanly to every CBF field. Some special handling of OCI-specific tenancy and account properties are represented as synthesized resource tags. For details, see [OCI/CBF Field Mappings](OCI-CBF-TABLE.md).

## Contributing

We appreciate feedback and contribution to this repo! Before you get started, please see the following:

* [General contribution guidelines](GENERAL-CONTRIBUTING.md)
* [Code of conduct guidelines](CODE-OF-CONDUCT.md)
* [This repo's contribution guide](CONTRIBUTING.md)

## Support + Feedback

This is a community-supported plugin. Support and help will be provided on a best-effort basis. Please use Github Issues for code-level support or to suggest improvements.

## Vulnerability Reporting

Please do not report security vulnerabilities on the public GitHub issue tracker. Email [security@cloudzero.com](mailto:security@cloudzero.com) instead.

## What is CloudZero?

CloudZero is the only cloud cost intelligence platform that puts engineering in control by connecting technical decisions to business results.:

* [Cost Allocation And Tagging](https://www.cloudzero.com/tour/allocation) Organize and allocate cloud spend in new ways, increase tagging coverage, or work on showback.
* [Kubernetes Cost Visibility](https://www.cloudzero.com/tour/kubernetes) Understand your Kubernetes spend alongside total spend across containerized and non-containerized environments.
* [FinOps And Financial Reporting](https://www.cloudzero.com/tour/finops) Operationalize reporting on metrics such as cost per customer, COGS, gross margin. Forecast spend, reconcile invoices and easily investigate variance.
* [Engineering Accountability](https://www.cloudzero.com/tour/engineering) Foster a cost-conscious culture, where engineers understand spend, proactively consider cost, and get immediate feedback with fewer interruptions and faster and more efficient innovation.
* [Optimization And Reducing Waste](https://www.cloudzero.com/tour/optimization) Focus on immediately reducing spend by understanding where we have waste, inefficiencies, and discounting opportunities.

Learn more about [CloudZero](https://www.cloudzero.com/) on our website [www.cloudzero.com](https://www.cloudzero.com/)

## License

This project is licenced under the Apache 2.0 [LICENSE](LICENSE).