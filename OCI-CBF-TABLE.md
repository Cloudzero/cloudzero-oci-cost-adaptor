# OCI/CBF Field Mappings

OCI emits both Cost and Usage reports. This tool uses only the Cost reports, as CBF has no fields for usage ("500 MB of this resource", etc). CBF only has fields for the cost of usage, which OCI emits in the cost report, so only that is used.

You can view details of the [OCI Cost Reports schema](https://docs.oracle.com/en-us/iaas/Content/Billing/Concepts/usagereportsoverview.htm#Cost_and_Usage_Reports_Overview__cost_report_schema) on Oracle's documentation site, and the same for [CBF Schema](https://docs.cloudzero.com/docs/anycost-common-bill-format-cbf#data-file-columns) at CloudZero's.

| OCI Cost File Column        | CBF Column                           | Notes                                                                                          |
| --------------------------- | ------------------------------------ | ---------------------------------------------------------------------------------------------- |
|                             | lineitem/type                        | Always set to 'Usage'                                                                          |
| product/description         | lineitem/description                 |                                                                                                |
| lineitem/intervalUsageStart | time/usage_start                     | Always UTC from Oracle                                                                         |
| lineitem/intervalUsageStart | time/usage_end                       | Always UTC from Oracle                                                                         |
| product/resourceId          | resource/id                          |                                                                                                |
| product/service             | resource/service                     |                                                                                                |
| lineItem/tenantId           | resource/account                     |                                                                                                |
| product/region              | resource/region                      |                                                                                                |
| lineItem/tenantId           | action/account                       |                                                                                                |
| usage/BilledQuantity        | usage/amount                         |                                                                                                |
| cost/myCost                 | cost/cost                            |                                                                                                |
| tags/`<tag_key>`            | resource/tag:`<tag_key>`             | OCI tag keys permit more characters than CBF does. Disallowed CBF characters will be stripped. |
|                             | resource/tag:oci_tenancy_name        | Synthesized tag                                                                                |
|                             | resource/tag:oci_compartment_name    | Synthesized tag                                                                                |
|                             | resource/tag:oci_compartment_id      | Synthesized tag                                                                                |
|                             | resource/tag:oci_availability_domain | Synthesized tag                                                                                |
