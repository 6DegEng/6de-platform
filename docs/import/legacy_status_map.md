# Legacy Status Map

How legacy xlsx status strings map to the platform's 10-value status enum.

## Status Mapping

| Legacy Value       | Platform Enum     | Notes                              |
|--------------------|-------------------|------------------------------------|
| Active             | `active`          | Direct match                       |
| On Hold            | `on_hold`         | Direct match                       |
| Completed          | `completed`       | Direct match                       |
| Complete           | `completed`       | Synonym                            |
| Closed             | `completed`       | Treated as completed               |
| Prospect           | `prospect`        | Direct match                       |
| Archived           | `archived`        | Direct match                       |
| Archive            | `archived`        | Synonym                            |
| Drafting           | `drafting`        | Session 3b status                  |
| AHJ/Permitting     | `ahj_permitting`  | Session 3b status                  |
| Permitting         | `ahj_permitting`  | Abbreviated form                   |
| Inspection         | `inspection`      | Session 3b status                  |
| Revisions          | `revisions`       | Session 3b status                  |
| Cancelled          | `cancelled`       | Session 3b status                  |
| Canceled           | `cancelled`       | American spelling                  |
| *(empty/missing)*  | `active`          | Default when no status provided    |

## Priority Mapping

| Legacy Value | Platform Enum | Notes                                      |
|--------------|---------------|--------------------------------------------|
| Low          | `low`         | Direct match                               |
| Medium       | `normal`      | Platform uses "normal" not "medium"         |
| Normal       | `normal`      | Direct match                               |
| High         | `high`        | Direct match                               |
| Urgent       | `urgent`      | Direct match                               |
| On Hold      | `normal`      | "On Hold" is a status, not a priority level |

## Lifecycle Buckets (future)

Mature Monday-style trackers group rows into lifecycle buckets that
drive board sections. The mapping from platform status to bucket:

| Bucket     | Statuses                                                    |
|------------|-------------------------------------------------------------|
| PROPOSED   | `prospect`                                                  |
| ACTIVE     | `active`, `drafting`, `ahj_permitting`, `inspection`, `revisions` |
| STAND BY   | `on_hold`                                                   |
| FINISHED   | `completed`                                                 |
| LOST       | `cancelled`                                                 |
| ARCHIVED   | `archived`                                                  |

This grouping is documented here for reference. The `lifecycle_bucket`
column does not exist yet — see the TODO in `modules/projects/workflow.py`.
