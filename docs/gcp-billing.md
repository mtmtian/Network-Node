# Google Cloud billing and monthly credits

Pricing and benefit rules checked against Google documentation on 2026-10-24. This guide contains reusable procedures and illustrative USD estimates, not a deployment inventory or a copy of a personal bill. Keep account identities, billing IDs, billing exports, and credit redemption details out of Git.

## Account and credit association

Three separate settings matter:

- `GCP_ACCOUNT` in the local GCP profile selects the identity used to administer the node.
- The Cloud project's billing association determines which Cloud Billing account receives charges.
- The Google Developer Program benefit selects the billing account receiving monthly promotional credits.

Changing the global gcloud login or joining a Google One family does not change the project's billing association. Google AI Pro includes a monthly $10 Cloud credit through Google Developer Program Premium, but that Premium benefit cannot be shared with family members. Use the subscriber's Developer profile to verify eligibility and redemption.

On the subscriber's [benefits page](https://me.developers.google.com/benefits), verify the destination billing account, available balance, expiry, and service scope. Select **Always use this billing account** if future recurring credits should be applied there automatically. Already-applied credits cannot be transferred to another billing account. Having an active subscription alone does not establish that a particular billing account received the credit.

Follow the [account and billing migration procedure](provider-onboarding.md#google-cloud-account-and-billing-changes) when changing accounts. Re-read the live billing association after the change, verify the existing VM and IP, test actual proxy connectivity, and only then update the profile's administration identity. Do not publish the profile or regenerate clients merely to change billing.

## Estimate the recurring cost

For a single eligible `e2-micro` in `us-west1` with a 30 GB `pd-standard` disk:

| Component | Planning basis |
| --- | --- |
| VM | Covered within the account's eligible monthly Compute Engine Free Tier allowance. Check for other instances sharing that allowance. |
| Standard persistent disk | Covered within the 30 GB-month Free Tier allowance. Additional disks and snapshots need separate accounting. |
| One attached external IPv4 | Public list price is $0.005/hour: approximately $3.60–$3.72 for a 30–31 day month, before any applicable free allowance or account-specific pricing. |
| Premium internet data transfer out | Destination-dependent. Examples at the initial paid tier: $0.12/GiB to North America or much of Asia; $0.23/GiB to mainland China. Use the actual billed SKU and applicable allowance. |
| Other resources | Include unused reserved IPs, additional disks, telemetry charges, and other projects consuming the same credit. |

The deployment default is `NETWORK_TIER=PREMIUM`. Do not assume Standard Tier's traffic allowance applies. A Cloudflare/CDN route is not evidence that Google Cloud egress is free; inspect which egress SKUs actually receive usage. Do not change network tier merely to satisfy an estimate: that is a separate networking change requiring connectivity validation.

An illustrative conservative budget, assuming the VM and disk remain covered by Free Tier, one IPv4 at list price, and no other charges, is:

```text
monthly cost before promotional credit
  = IPv4 hours × $0.005 + billable egress GiB × destination rate
```

For 744 hours and 10 billable GiB at $0.12/GiB, this is $3.72 + $1.20 = $4.92. A $10 credit leaves $6.28 after the IP, enough for about 52 billable GiB at $0.12/GiB or 27 billable GiB at $0.23/GiB. These are single-rate examples, not a guaranteed traffic quota; mixed routes, shared credits, taxes, and other charges change the result.

## Read the actual bill before deciding whether $10 is enough

1. Open Cloud Billing Reports and filter to the node's project. After a billing migration, inspect both old and new billing accounts; neither alone contains the complete transition month's usage.
2. Use a complete prior month and the current month's available usage. Record the reporting cutoff, billing currency, and any partial-day or reporting delay. Do not equate a forecast with a final invoice.
3. Group by SKU and retain Free Tier/recurring discounts while excluding promotional credits. A zero amount payable after credits does not mean the service costs nothing. Some free VM discounts appear as separate negative SKU rows.
4. Inspect VM, disk, IPv4, egress, and telemetry rows together, including their usage units. Reconcile their totals before extrapolating; do not sum only positive VM rows or interpret a TWD `$` label as USD.
5. Compare the recurring amount before promotional credits with the subscriber's available Cloud credit. When moving to a different account or currency, re-check destination pricing and allowances instead of assuming the old account's zero-priced SKUs will carry over.

Monthly credits and ordinary budget alerts are not a hard spending cap. Verify any separately configured enforcement mechanism before claiming that overspending will stop automatically.

## Official references

- [Google AI Pro benefits and family eligibility](https://support.google.com/googleone/answer/14534406?hl=en)
- [Developer Program credit redemption and automatic application](https://developers.google.com/profile/help/benefits?hl=en)
- [Change a project's billing account](https://docs.cloud.google.com/billing/docs/how-to/modify-project)
- [Google Cloud Free Tier](https://docs.cloud.google.com/free/docs/free-cloud-features)
- [Network and external IP pricing](https://cloud.google.com/vpc/network-pricing)
